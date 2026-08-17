"""
The recall form — what a memory looks like when it is injected, as opposed to
what it is.

THE PROBLEM, measured rather than assumed. Recall does not inject whole
memories; it injects a preview, and that preview was `body[:220]`. On the brain
this was built against, curated bodies average 767 characters, p90 is 2,256 and
the longest is 38,606 — so a typical memory arrived with 90% of itself missing
and the cut made by POSITION rather than importance. A worked example: a memory
recording a measured ranking result injected as

    "2026-08-16. First time engram has ever been scored against ground truth it
     did not generate itself. The distinctive claim — recall improves because of
     use — was false as shipped. It is now true, and the difference is one"

while the numbers the memory exists for sat at character 2,100 and never reached
the context at all. Truncation is a summariser that always keeps the preamble.

WHAT THIS IS NOT. It is not compression of the archive. Storage is not scarce —
115MB for 4,166 memories, of which all prose ever written is 5MB, against 28MB
of vectors. Compressing text to save disk would break trigram search and add a
decode to every read for a 5% saving.

THE DESIGN DECISION THAT MAKES IT SAFE: the embedding stays on the FULL BODY.
Nothing about retrieval changes — a memory is found exactly as often, ranked
exactly as high, because its vector is untouched. Only what gets shown changes.
That decouples two questions that are usually tangled: what makes a memory
FINDABLE, and what makes it USEFUL once found. Compressing the stored text would
have entangled them again, and today's lens work showed how badly text length
and shape distort a vector.

WHAT A GOOD RECALL FORM CONTAINS. The conclusion, plus anything a model cannot
regenerate: numbers, ids, file paths, dates, names. It drops explanatory prose,
which is the part a reader can reconstruct from the conclusion — and which is
also most of the length. This is the spark/fact/texture split applied at the
only point where it is safe: at DISPLAY, where being wrong is recoverable
because the body is still there.

WRITE-TIME OR OFFLINE. `Memory.save(recall_form=...)` accepts one, because the
writer knew what mattered and needs no model call to say so. When absent, the
dreaming pass fills it in, most-recalled first — the memories that get injected
are exactly the ones worth compressing, so the budget goes where it is felt.
"""
import os
from typing import Optional

from .db import get_conn
from .llm import complete_text

# Long enough to carry a finding with its numbers, short enough that five of
# them are cheap. The old truncation was 220 characters of whatever came first;
# this is a similar order of magnitude spent deliberately.
TARGET_CHARS = int(os.environ.get("ENGRAM_RECALL_FORM_CHARS", "400"))

PROMPT = """Rewrite this memory as the SHORTEST text that still tells a future
reader what they need, in {target} characters or fewer.

KEEP, always:
- the conclusion or outcome — what is now true
- anything that cannot be regenerated from general knowledge: numbers,
  measurements, ids, file paths, dates, names, commit hashes, thresholds

DROP:
- reasoning, narrative, and explanation of how the conclusion was reached
- background a competent reader could reconstruct from the conclusion itself

Do not add anything. Do not use a preamble like "This memory describes".
Write plain prose or terse clauses. Reply with the rewritten text only.

Subject: {subject}

Body:
{body}"""


def _trim(text: str, target: int) -> str:
    """Cut to the last complete sentence at or under `target`.

    Enforced rather than requested. Asked for 400 characters, Haiku produced a
    measured average of 768 across the first 89 real memories — which would have
    made the recall form COST context rather than save it: five injected
    memories went from ~1,100 characters under the old truncation to ~3,840.
    A limit that is only a suggestion in a prompt is not a limit.

    Sentence-boundary rather than hard slice, and the model is told to put the
    conclusion first, so what survives a trim is the part worth keeping — which
    is exactly what `body[:220]` could not promise.
    """
    text = (text or "").strip()
    if len(text) <= target:
        return text
    cut = text[:target]
    for end in (". ", "? ", "! ", ".\n", "; "):
        i = cut.rfind(end)
        if i > target * 0.5:
            return cut[:i + 1].strip()
    return cut.rstrip() + "…"


def generate(subject: str, body: str, target: int = TARGET_CHARS) -> Optional[str]:
    """Write a recall form, or None if the model did not produce a usable one.

    Returns None rather than a fragment: a truncated recall form is worse than
    no recall form, because the caller falls back to the body and gets a
    complete-if-blunt preview instead of a mangled clever one.
    """
    if not body or len(body) <= target:
        return None          # already short enough to inject whole
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": PROMPT.format(
                target=target, subject=subject or "", body=(body or "")[:6000])}],
        )
        text = complete_text(msg, what="recall form", quiet=True)
        if not text:
            return None
        text = _trim(text, target)
        # A "summary" longer than what it summarises has failed at its one job.
        return text if 0 < len(text) < len(body) else None
    except Exception:
        return None


def backfill(budget: int = 20, tiers=("curated", "insight", "decision", "project"),
             min_len: Optional[int] = None) -> dict:
    """Fill in missing recall forms, MOST-RECALLED FIRST.

    Ordering by weight rather than by date is the point: the memories that
    actually get injected are the ones worth spending a model call on, and a
    memory nobody has ever recalled costs nothing by staying uncompressed.
    """
    min_len = min_len or TARGET_CHARS
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """SELECT id, subject, body FROM memories
            WHERE recall_form IS NULL AND archived = false
              AND body IS NOT NULL AND length(body) > %s
              AND tier = ANY(%s)
            ORDER BY weight DESC, created_at DESC
            LIMIT %s""",
        (min_len, list(tiers), budget))
    rows = cur.fetchall()
    written = skipped = 0
    for mid, subject, body in rows:
        form = generate(subject or "", body or "")
        if not form:
            skipped += 1
            continue
        cur.execute("UPDATE memories SET recall_form = %s WHERE id = %s", (form, mid))
        written += 1
    conn.commit()
    cur.close()
    conn.close()
    return {"considered": len(rows), "written": written, "skipped": skipped}


def preview(row: dict, chars: int = 220) -> str:
    """What to SHOW for a recalled memory.

    The recall form when there is one, else the old positional truncation. The
    fallback is deliberate and permanent: a brain with no model key, or one
    whose backfill has not reached a memory yet, must still return something
    readable rather than nothing.
    """
    form = (row.get("recall_form") or "").strip()
    if form:
        return form
    body = (row.get("body") or "").replace("\n", " ")
    return body[:chars] + ("..." if len(body) > chars else "")
