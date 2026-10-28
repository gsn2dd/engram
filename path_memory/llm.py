"""
The one place that decides whether a model response is usable.

Every Messages API call returns HTTP 200 whether the model finished or was cut
off mid-sentence at max_tokens. Code that reads `.content` without asking why
the model stopped cannot tell a complete answer from a fragment, and nothing
downstream can tell afterwards either — the fragment is simply stored, embedded
or acted on as though it were the answer.

An audit of every call site we own (2026-08-08) found that most of them made
exactly that mistake, and that the ones which did handle it each did so
slightly differently. Hence one helper rather than the same four lines copied
into every caller: a new call site gets the check by using this, and the
failure modes are named in one place.

    text = complete_text(response, what="topic extraction")
    if text is None:
        ...   # incomplete or refused — NOT the same as "the model said nothing"
"""
import sys as _sys
from typing import Optional

# The model ran out of room. The content is a fragment of the intended answer,
# and for anything structured (JSON, a label, a name) it is not merely shorter
# — it is invalid.
INCOMPLETE = ("max_tokens", "model_context_window_exceeded")


def complete_text(response, what: str = "response", quiet: bool = False) -> Optional[str]:
    """Return the text of a response that finished cleanly, or None.

    None means "do not use this": the model was cut off, declined, or produced
    no text at all. It deliberately does NOT distinguish those cases in its
    return value, because every caller so far treats them the same way; the
    distinction goes to stderr, where a human debugging a quiet failure will
    find it.

    Callers that must tell "the model answered, and the answer was empty" from
    "the model never answered" should check stop_reason themselves — that
    distinction is real and cost us a bug in the dreaming pass, where [] and a
    failed call were conflated and a batch was re-read forever.
    """
    stop = getattr(response, "stop_reason", None)

    if stop in INCOMPLETE:
        if not quiet:
            print(f"[engram] {what}: response was cut off ({stop}) — discarded",
                  file=_sys.stderr)
        return None

    if stop == "refusal":
        if not quiet:
            print(f"[engram] {what}: model declined — discarded", file=_sys.stderr)
        return None

    # pause_turn means a server-tool loop hit its iteration limit and expects
    # the response to be sent back to continue. None of our call sites use
    # server tools, so reaching it means something changed and the caller is
    # not equipped to continue the turn.
    if stop == "pause_turn":
        if not quiet:
            print(f"[engram] {what}: paused mid-turn (server tool loop) — "
                  f"this caller cannot continue it", file=_sys.stderr)
        return None

    # Never index content[0] blindly: the first block is not guaranteed to be
    # text, and on some stop reasons the list is empty.
    text = "".join(
        block.text for block in getattr(response, "content", []) or []
        if getattr(block, "type", None) == "text"
    ).strip()
    return text or None


# ---------------------------------------------------------------------------
# Subscription fallback (2026-10-23).
#
# The API account ran out of credit on 2026-09-28 and every background call
# (lenses, noun type, open loops, dreaming, recall forms) has failed quietly
# since: 4 weeks of memories with no `questions` lens. David asked for the
# shortfall to be covered by his Claude subscription. The subscription cannot
# pay for API credit, but the Claude Code CLI on this box is signed in to it,
# so a billing failure here re-runs the same request through `claude -p`.
#
# Only billing failures fall back: anything else (a bad request, a network
# error) is still the caller's to handle. Once one billing failure is seen the
# process stops trying the API, rather than paying a round trip per call.
#
# The CLI runs with no settings (so none of this box's hooks fire — the
# mindspace hooks would otherwise recall, ingest and re-embed these calls),
# no tools, no MCP and no session file. ENGRAM_CLI_DAILY_CAP bounds how much of
# David's interactive allowance the background jobs may use in a day.
# ---------------------------------------------------------------------------
import glob as _glob
import json as _json
import os as _os
import shutil as _shutil
import subprocess as _subprocess
from datetime import date as _date
from types import SimpleNamespace as _NS

_BILLING_MARKERS = ("credit balance is too low", "usage limits", "spend limit")
_api_out_of_credit = False
_CAP_FILE = _os.path.expanduser("~/.cache/engram/cli_fallback_calls.json")


def _is_billing_error(exc) -> bool:
    text = str(exc).lower()
    return any(m in text for m in _BILLING_MARKERS)


def _take_cli_slot() -> bool:
    cap = int(_os.environ.get("ENGRAM_CLI_DAILY_CAP", "400"))
    today = _date.today().isoformat()
    try:
        with open(_CAP_FILE) as f:
            state = _json.load(f)
    except Exception:
        state = {}
    if state.get("day") != today:
        state = {"day": today, "n": 0}
    if state["n"] >= cap:
        return False
    state["n"] += 1
    try:
        _os.makedirs(_os.path.dirname(_CAP_FILE), exist_ok=True)
        with open(_CAP_FILE, "w") as f:
            _json.dump(state, f)
    except Exception:
        pass
    return True


def _cli_exe():
    # cron's PATH has no nvm, so look there too (newest node first).
    found = _shutil.which("claude")
    if found:
        return found
    hits = sorted(_glob.glob(_os.path.expanduser("~/.nvm/versions/node/*/bin/claude")))
    return hits[-1] if hits else None


def _cli_model(model: str) -> str:
    m = (model or "").lower()
    for family in ("haiku", "sonnet", "opus", "fable"):
        if family in m:
            return family
    return "haiku"


def _cli_create(model=None, messages=(), system=None, output_config=None, **_ignored):
    """Run one single-turn text request through `claude -p`; return an object
    shaped enough like a Messages response for complete_text() and callers.
    max_tokens and temperature have no CLI equivalent and are ignored."""
    if len(messages) != 1 or messages[0].get("role") != "user" \
            or not isinstance(messages[0].get("content"), str):
        raise RuntimeError("CLI fallback handles one plain-text user turn only")
    exe = _cli_exe()
    if not exe:
        raise RuntimeError("CLI fallback: claude not found")
    if not _take_cli_slot():
        raise RuntimeError("CLI fallback: daily cap reached")
    cmd = [exe, "-p", "--setting-sources", "", "--tools", "", "--strict-mcp-config",
           "--no-session-persistence", "--output-format", "json",
           "--model", _cli_model(model),
           "--system-prompt", system if isinstance(system, str) and system
           else "Do exactly what the user message asks. Output only the answer."]
    schema = ((output_config or {}).get("format") or {}).get("schema")
    if schema:
        cmd += ["--json-schema", _json.dumps(schema)]
    effort = (output_config or {}).get("effort")
    if effort:
        cmd += ["--effort", effort]
    env = {k: v for k, v in _os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    env["PATH"] = _os.path.dirname(exe) + ":" + env.get("PATH", "/usr/bin:/bin")
    workdir = _os.path.dirname(_CAP_FILE)
    _os.makedirs(workdir, exist_ok=True)
    proc = _subprocess.run(cmd, input=messages[0]["content"], capture_output=True,
                           text=True, timeout=600, env=env, cwd=workdir)
    try:
        out = _json.loads(proc.stdout)
    except Exception:
        raise RuntimeError(f"CLI fallback failed: {proc.stderr.strip()[:200]}")
    if out.get("is_error"):
        raise RuntimeError(f"CLI fallback error: {str(out.get('result'))[:200]}")
    if schema and out.get("structured_output") is not None:
        text = _json.dumps(out["structured_output"])
    else:
        text = out.get("result") or ""
    return _NS(stop_reason="end_turn",
               content=[_NS(type="text", text=text)], via="claude-cli")


# ---------------------------------------------------------------------------
# Bedrock first, when a spending guard is configured (2026-10-28).
#
# An engram that runs under an agent harness may point ENGRAM_BEDROCK_GUARD at
# the folder holding the harness's `bedrock_guard` package (caps, ledger, kill
# switch). Then every background call goes: Bedrock (the guard's background
# model, whatever model the caller named) -> the subscription CLI -> the
# caller's own no-model fallback. The API key route is not used at all: the
# harness owner's rule is that the box's routine runs on the subscription, with
# Bedrock under hard caps. Without the variable nothing below changes.
# ---------------------------------------------------------------------------
_guard_mod = None


def _guard():
    global _guard_mod
    lib = _os.environ.get("ENGRAM_BEDROCK_GUARD")
    if not lib:
        return None
    if _guard_mod is None:
        if lib not in _sys.path:
            _sys.path.insert(0, lib)
        try:
            import bedrock_guard
            _guard_mod = bedrock_guard
        except Exception as e:
            print(f"[engram] ENGRAM_BEDROCK_GUARD set but not importable: {e}", file=_sys.stderr)
            _guard_mod = False
    return _guard_mod or None


def _as_response(d):
    return _NS(stop_reason=d.get("stop_reason"), via="bedrock",
               content=[_NS(**{k: v for k, v in b.items()}) for b in d.get("content") or []])


def _bedrock_create(g, caller, model=None, messages=(), max_tokens=1024, system=None,
                    temperature=None, output_config=None, **_ignored):
    return _as_response(g.invoke(caller=caller, messages=list(messages), max_tokens=max_tokens,
                                 system=system, temperature=temperature,
                                 output_config=output_config))


def _caller_name():
    # the engram module that asked, for the ledger: engram:dream, engram:open_loops ...
    f = _sys._getframe(2)
    return "engram:" + _os.path.splitext(_os.path.basename(f.f_code.co_filename))[0]


def available() -> bool:
    """True when some route can answer: an API key, or the Bedrock guard."""
    return bool(_os.environ.get("ANTHROPIC_API_KEY") or _os.environ.get("ANTHROPIC_AUTH_TOKEN")
                or _guard())


def create_message(client=None, **kwargs):
    """client.messages.create(**kwargs), falling back to the subscription CLI
    when the API account is out of credit. Use in place of the direct call.
    With ENGRAM_BEDROCK_GUARD set: Bedrock (guarded) -> subscription CLI, no API."""
    global _api_out_of_credit
    g = _guard()
    if g is not None:
        caller = _caller_name()
        try:
            return _bedrock_create(g, caller, **kwargs)
        except Exception as e:
            print(f"[engram] Bedrock not used for {caller} ({e.__class__.__name__}: "
                  f"{str(e)[:160]}) — trying the subscription CLI", file=_sys.stderr)
        return _cli_create(**kwargs)
    if not _api_out_of_credit:
        try:
            if client is None:
                from anthropic import Anthropic
                client = Anthropic()
            return client.messages.create(**kwargs)
        except Exception as e:
            if not _is_billing_error(e):
                raise
            _api_out_of_credit = True
            print("[engram] API out of credit — using the Claude subscription CLI",
                  file=_sys.stderr)
    return _cli_create(**kwargs)
