"""
Embedding provider for engram.

A memory brain that hard-requires one embedding vendor is not portable, and
portability is the whole promise — the brain is supposed to outlive the agent,
the model, and the vendor. So the provider is selectable.

    ENGRAM_EMBED_PROVIDER = auto (default) | gemini | openai
    ENGRAM_EMBED_DIM      = 768 (default)

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
import urllib.request
from typing import Optional

GEMINI_MODEL = "gemini-embedding-001"
OPENAI_MODEL = "text-embedding-3-small"

DIM = int(os.environ.get("ENGRAM_EMBED_DIM", "768"))
PROVIDER = os.environ.get("ENGRAM_EMBED_PROVIDER", "auto").strip().lower()
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
    if PROVIDER in ("gemini", "openai"):
        return PROVIDER
    if PROVIDER != "auto":
        raise EmbeddingError(
            f"ENGRAM_EMBED_PROVIDER={PROVIDER!r} is not one of: auto, gemini, openai"
        )
    if _gemini_key():
        return "gemini"
    if _openai_key():
        return "openai"
    raise EmbeddingError(
        "No embedding provider available. Set GEMINI_API_KEY or OPENAI_API_KEY "
        "(or pin one with ENGRAM_EMBED_PROVIDER)."
    )


def active_model() -> str:
    """The model id to stamp on rows written by this process."""
    return GEMINI_MODEL if resolve_provider() == "gemini" else OPENAI_MODEL


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


def embed(texts) -> list:
    if isinstance(texts, str):
        texts = [texts]
    if resolve_provider() == "gemini":
        return _embed_gemini(texts)
    return _embed_openai(texts)


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
