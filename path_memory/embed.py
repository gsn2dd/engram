"""
Embedding provider for engram.

A memory brain that hard-requires one embedding vendor is not portable, and
portability is the whole promise — the brain is supposed to outlive the agent,
the model, and the vendor. So the provider is selectable.

    ENGRAM_EMBED_PROVIDER = auto (default) | gemini | openai | bedrock
    ENGRAM_EMBED_DIM      = 768 (default; 1024 for bedrock)

bedrock = Amazon Titan Text Embeddings V2 through AWS Bedrock, using the
instance's own AWS credentials (no API key to leak or expire). Titan offers
256/512/1024 dimensions, not 768, so a bedrock brain is 1024-dim: switching a
brain to it means changing the vector columns and re-embedding everything.

Both providers are pinned to the same dimensionality so the column type stays
fixed, but note the thing that actually matters:

    VECTORS FROM TWO DIFFERENT MODELS ARE NOT COMPARABLE.

Same length, different meaning. Mixing them in one brain does not raise an
error — it quietly degrades recall, which is the single hardest failure to
notice and the exact thing engram's roadmap worries about. Hence
`assert_brain_compatible()`, which refuses to write a vector into a brain built
by a different model unless the operator explicitly overrides it.
"""

import functools
import json
import os
import sys as _sys
import urllib.request
from typing import Optional

GEMINI_MODEL = "gemini-embedding-001"
OPENAI_MODEL = "text-embedding-3-small"
BEDROCK_MODEL = "amazon.titan-embed-text-v2:0"
BEDROCK_REGION = os.environ.get("ENGRAM_BEDROCK_REGION") or os.environ.get("AWS_REGION") or "eu-west-1"

PROVIDER = os.environ.get("ENGRAM_EMBED_PROVIDER", "auto").strip().lower()
DIM = int(os.environ.get("ENGRAM_EMBED_DIM") or (1024 if PROVIDER == "bedrock" else 768))
ALLOW_MIXED = os.environ.get("ENGRAM_EMBED_ALLOW_MIXED", "").lower() in ("1", "true", "yes")


class EmbeddingError(RuntimeError):
    pass


def _gemini_key():
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""


def _openai_key():
    return os.environ.get("OPENAI_API_KEY") or ""


@functools.lru_cache(maxsize=1)
def resolve_provider() -> str:
    """Which provider this process will use. Cached: it must not drift mid-run."""
    if PROVIDER in ("gemini", "openai", "bedrock"):
        return PROVIDER
    if PROVIDER != "auto":
        raise EmbeddingError(
            f"ENGRAM_EMBED_PROVIDER={PROVIDER!r} is not one of: auto, gemini, openai, bedrock"
        )
    # SAY WHICH PROVIDER WAS CHOSEN, AND WHY, BEFORE THE FIRST CALL.
    #
    # `auto` picks whichever key it finds. When only one is present that is a
    # silent decision, and if that key is stale the operator gets an
    # authentication failure from a vendor they did not know they were using.
    # Observed on this project: a container with no GEMINI_API_KEY and a dead
    # OPENAI_API_KEY answered every write with a 401 from OpenAI, and the first
    # hypothesis was "Gemini is failing inside the process" — which it was not,
    # because Gemini was never selected. One line of stderr at selection time
    # is the difference between that hunt and reading the answer.
    #
    # Printed once: resolve_provider is lru_cached, so this fires on first use
    # per process and never chatters.
    if _gemini_key():
        if PROVIDER == "auto":
            print(f"[engram] embedding provider: gemini ({GEMINI_MODEL}) "
                  f"— auto-selected from GEMINI_API_KEY", file=_sys.stderr)
        return "gemini"
    if _openai_key():
        if PROVIDER == "auto":
            print(f"[engram] embedding provider: openai ({OPENAI_MODEL}) "
                  f"— auto-selected because no GEMINI_API_KEY is set. If you "
                  f"meant to use Gemini, this is why writes are going to OpenAI.",
                  file=_sys.stderr)
        return "openai"
    raise EmbeddingError(
        "No embedding provider available. Set GEMINI_API_KEY or OPENAI_API_KEY "
        "(or pin one with ENGRAM_EMBED_PROVIDER)."
    )


_MODELS = {"gemini": GEMINI_MODEL, "openai": OPENAI_MODEL, "bedrock": BEDROCK_MODEL}


def active_model() -> str:
    """The model id to stamp on rows written by this process."""
    return _MODELS[resolve_provider()]


def provider_ready() -> bool:
    """
    True only if embedding would actually work right now.

    `resolve_provider()` is not this check. When ENGRAM_EMBED_PROVIDER is pinned
    it returns that provider whether or not its key is present — the key is only
    consulted at call time. Callers that want to know "can I embed?" before
    starting work need this, otherwise they proceed and fail per item.
    """
    try:
        provider = resolve_provider()
    except EmbeddingError:
        return False
    if provider == "bedrock":
        try:
            import boto3
            return boto3.Session().get_credentials() is not None
        except Exception:
            return False
    return bool(_gemini_key() if provider == "gemini" else _openai_key())


def _embed_gemini(texts):
    key = _gemini_key()
    if not key:
        raise EmbeddingError("provider is gemini but GEMINI_API_KEY/GOOGLE_API_KEY is unset")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:embedContent?key={key}")
    out = []
    for text in texts:
        body = json.dumps({
            "content": {"parts": [{"text": text}]},
            "outputDimensionality": DIM,
        }).encode()
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.load(response)
        values = data.get("embedding", {}).get("values")
        if not values or len(values) != DIM:
            raise EmbeddingError(f"gemini returned an unusable embedding: {str(data)[:200]}")
        out.append(values)
    return out


def _embed_openai(texts):
    if not _openai_key():
        raise EmbeddingError("provider is openai but OPENAI_API_KEY is unset")
    from openai import OpenAI
    response = OpenAI(api_key=_openai_key()).embeddings.create(
        model=OPENAI_MODEL, input=list(texts), dimensions=DIM)
    return [item.embedding for item in response.data]


@functools.lru_cache(maxsize=1)
def _bedrock_client():
    import boto3
    return boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)


def _embed_bedrock(texts):
    if DIM not in (256, 512, 1024):
        raise EmbeddingError(f"bedrock (Titan V2) supports 256/512/1024 dims, not {DIM}")
    out = []
    for text in texts:
        # Titan V2 takes up to 8k tokens; 40k characters keeps well inside it.
        text = (text or " ")[:40000]
        while True:
            body = json.dumps({"inputText": text, "dimensions": DIM, "normalize": True})
            try:
                resp = _bedrock_client().invoke_model(modelId=BEDROCK_MODEL, body=body)
                break
            except Exception as exc:
                # Titan caps input at 8192 tokens; dense text (code, JSON) can pass
                # the character cut and still be too long. Shorten and retry.
                if "Too many input tokens" not in str(exc) or len(text) < 2000:
                    raise
                text = text[: int(len(text) * 0.8)]
        values = json.loads(resp["body"].read()).get("embedding")
        if not values or len(values) != DIM:
            raise EmbeddingError(f"bedrock returned an unusable embedding (len {len(values or [])})")
        out.append(values)
    return out


_EMBEDDERS = {"gemini": _embed_gemini, "openai": _embed_openai, "bedrock": _embed_bedrock}


def embed(texts) -> list:
    """Embed one or more texts with the resolved provider.

    A FAILURE NAMES THE PROVIDER AND HOW IT WAS CHOSEN. Without that, a stale
    key produces a bare authentication error from a vendor the operator may not
    have realised was in play — the raw urllib/openai exception says nothing
    about engram's selection. Diagnosing one of these cost a session's
    investigation that started from the wrong hypothesis entirely, so the
    context is attached to the exception rather than left in a log the reader
    may not have.
    """
    if isinstance(texts, str):
        texts = [texts]
    provider = resolve_provider()
    try:
        return _EMBEDDERS[provider](texts)
    except EmbeddingError:
        raise
    except Exception as exc:
        how = ("pinned by ENGRAM_EMBED_PROVIDER" if PROVIDER != "auto"
               else "auto-selected from the keys present in this environment")
        raise EmbeddingError(
            f"embedding failed via {provider} "
            f"({_MODELS[provider]}, {how}): "
            f"{exc.__class__.__name__}: {exc}"
        ) from exc


def embed_one(text: str) -> list:
    return embed([text])[0]


def brain_model(cur) -> Optional[str]:
    """The model this brain's existing vectors were built with, if any."""
    cur.execute(
        "SELECT embedding_model FROM memories "
        "WHERE embedding_model IS NOT NULL AND embedding IS NOT NULL LIMIT 1"
    )
    row = cur.fetchone()
    return row[0] if row else None


def assert_brain_compatible(cur) -> None:
    """
    Refuse to add a vector to a brain built by a different model.

    Silently mixing vector spaces is worse than an outage: recall keeps
    working, just worse, and nothing tells you. If you genuinely mean to
    switch, re-embed the brain — or set ENGRAM_EMBED_ALLOW_MIXED=1 and accept
    that recall quality across the boundary is undefined.
    """
    if ALLOW_MIXED:
        return
    existing = brain_model(cur)
    mine = active_model()
    if existing and existing != mine:
        raise EmbeddingError(
            f"This brain was built with '{existing}' but this process embeds with "
            f"'{mine}'. Vectors from different models are not comparable. Re-embed "
            f"the brain, pin ENGRAM_EMBED_PROVIDER to the original, or set "
            f"ENGRAM_EMBED_ALLOW_MIXED=1 to override."
        )
