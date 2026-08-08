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
