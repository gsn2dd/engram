import os
import sys as _sys
from typing import Optional

NOUN_TYPES = ("person", "place", "project", "thing")

def classify_noun(person: Optional[str], subject: str, body: str) -> str:
    """
    Auto-classify noun_type by inspecting entity and content.
    Uses Claude Haiku for speed and low cost. Falls back to 'thing'.
    """
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        prompt = (
            f"Classify the primary entity in this memory.\n\n"
            f"Entity: {person or '(none)'}\n"
            f"Subject: {subject}\n"
            f"Content (first 300 chars): {body[:300]}\n\n"
            f"Choose one: person | place | project | thing\n"
            f"- person: a human being\n"
            f"- place: a geographic location\n"
            f"- project: an initiative, product, codebase, or ongoing work\n"
            f"- thing: an idea, concept, object, or anything else\n\n"
            f"Reply with one word only."
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=5,
            messages=[{"role": "user", "content": prompt}],
        )
        # A 5-token ceiling on a one-word answer is tight enough that truncation
        # is a live possibility, and the old code hid it: "project" cut short
        # fails the NOUN_TYPES membership test and silently became "thing". That
        # is a wrong classification presented as a decision. Fall back to the
        # heuristic instead — it is at least designed to guess — and say so.
        if msg.stop_reason in ("max_tokens", "model_context_window_exceeded", "refusal"):
            print(f"[engram] classify got {msg.stop_reason} for {subject!r} — using heuristic",
                  file=_sys.stderr)
            return _heuristic(person, subject, body)
        result = "".join(b.text for b in msg.content
                         if getattr(b, "type", None) == "text").strip().lower()
        return result if result in NOUN_TYPES else _heuristic(person, subject, body)
    except Exception:
        return _heuristic(person, subject, body)


def _heuristic(person, subject, body) -> str:
    text = f"{person or ''} {subject} {body}".lower()
    if any(w in text for w in ("city", "town", "village", "country", "region", "place", "street", "river")):
        return "place"
    if any(w in text for w in ("project", "repo", "package", "product", "initiative", "codebase", "release")):
        return "project"
    if person and person[0].isupper() and " " in person:
        return "person"
    return "thing"
