import os
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
        result = msg.content[0].text.strip().lower()
        return result if result in NOUN_TYPES else "thing"
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
