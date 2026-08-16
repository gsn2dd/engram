"""
Write-time quality warnings — told, never enforced.

WHY WARNINGS AND NOT VALIDATION. A memory system's first duty is that everything
gets in. Rejecting a write, or making the caller confirm one, taxes the exact
behaviour the system depends on — and the callers that matter most (an ingest
endpoint, a browser capture, a bulk JSON fold) have no one standing by to
approve anything. So `remember` always succeeds and always returns the id. The
warnings ride along and may be ignored with no consequence.

WHY NOT AN APPROVAL ROUND-TRIP. Two reasons, both learned here rather than
assumed. First, it would put a model call on the write path — the same mistake
that had `recall(collapse=True)` naming every new boundary synchronously, so a
user exploring a fresh brain paid an API call per query for a label nobody
asked for. That naming moved offline to the dreaming pass, and summarising
belongs there for the same reason. Second, an agent asked "is this draft OK?"
at the moment it wants to move on will say yes. You would pay two round-trips
for a signal that is almost constant.

WHY THIS EXISTS AT ALL — the case that motivated it. On the brain this was built
against, 1,899 of 2,719 curated memories (70%) turned out to be
`L2 <file> :: <function> :: <date>` records: one subject template, differing
only by date. Asked for one by its exact subject line, recall returns a SIBLING
first — 19 of 40 sampled were not ranked #1 by their own title. They are not
individually findable and never were.

Every check below is what would have caught that at memory number two instead of
number 1,899. That is the design brief: cheap enough to run on every write, and
aimed at the failure modes that only become visible in aggregate, which is
exactly when it is too late to fix them by hand.

NO MODEL CALLS, and no recomputation. Every check is SQL against the row that
was just written, so the embedding is read rather than generated. Budget is
single-digit milliseconds; a warning system that slows writes would be traded
away the first time someone benchmarked the brain.
"""
import re
from typing import Any, Dict, List

# A subject shared by this many memories is a template, not a label. Set low on
# purpose: the point is to fire on the second or third, while the habit is still
# cheap to change. By the time it would fire at a high threshold, the corpus
# already has thousands of unfindable rows in it.
TEMPLATE_AT = 5
TEMPLATE_PREFIX = 40

# Cosine at or above this is a near-duplicate in practice. Measured on a real
# corpus: unrelated curated memories average 0.66, and 0.90 was the maximum
# between two randomly drawn ones, so 0.95 is comfortably clear of coincidence.
NEAR_DUPLICATE = 0.95

# Longer than this and the injected preview shows a fraction of the memory, so
# whichever part happens to come first is what a future agent will actually see.
LONG_BODY = 2000

# Digits carry the variation in a templated subject ("... :: 2026-07-25"), so
# they are removed before comparing. Without this, every date-stamped record
# looks unique and the check that exists to catch exactly that case never fires.
_DIGITS = re.compile(r"\d+")
_URLISH = re.compile(r"^[a-z][a-z0-9+.-]*://|^/|^[a-z_/.-]+\.(py|js|ts|sql|md|json)\b", re.I)


def _norm_prefix(subject: str) -> str:
    return _DIGITS.sub("#", (subject or "").strip())[:TEMPLATE_PREFIX]


def inspect(conn, memory_id: int) -> List[Dict[str, Any]]:
    """Inspect a memory that has just been written. Returns a list of
    {code, message} warnings, empty when nothing is worth saying.

    NEVER RAISES. This runs after a successful save; a warning system that can
    turn a stored memory into an error has inverted its own priorities.
    """
    try:
        return _inspect(conn, memory_id)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return []


def _inspect(conn, memory_id: int) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    # The embedding is fetched as a VALUE, not referenced as a subquery. Written
    # the obvious way — `ORDER BY embedding <=> (SELECT embedding FROM ...)` —
    # the planner cannot use the HNSW index and computes the distance for every
    # row: measured at 55ms against 4,125 memories, and growing linearly. As a
    # bound parameter the same query is an index scan.
    cur.execute(
        """SELECT subject, body, project, embedding::text
           FROM memories WHERE id = %s""", (memory_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        return []
    subject, body, project, vec = row
    has_vec = vec is not None
    subject = subject or ""
    body = body or ""
    out: List[Dict[str, Any]] = []

    # 1. TEMPLATED SUBJECT — the L2 case. Compared on a digit-normalised prefix
    #    so date-stamped siblings collapse together instead of each looking new.
    prefix = _norm_prefix(subject)
    if len(prefix) >= 12:
        cur.execute(
            """SELECT count(*) FROM (
                   SELECT 1 FROM memories
                    WHERE id <> %s AND archived = false
                      AND regexp_replace(left(subject, %s), '\\d+', '#', 'g')
                          = regexp_replace(%s, '\\d+', '#', 'g')
                    LIMIT %s) s""",
            (memory_id, TEMPLATE_PREFIX, prefix, TEMPLATE_AT * 4))
        n = cur.fetchone()[0]
        if n >= TEMPLATE_AT:
            out.append({
                "code": "templated_subject",
                "message": (f"subject shares a template with {n}+ existing memories — "
                            f"these compete with each other and none is individually "
                            f"findable by its own title. Put what makes THIS one "
                            f"different into the subject."),
            })

    # 2. NEAR-DUPLICATE BODY. Uses the stored vector, so no embedding call.
    if has_vec:
        cur.execute(
            """SELECT id, subject, 1 - (embedding <=> %s::vector) AS sim
                 FROM memories
                WHERE id <> %s AND archived = false AND embedding IS NOT NULL
                  -- A memory this one has already superseded is not a duplicate
                  -- to report: that IS the resolution, and repeating the warning
                  -- would ask the caller to fix something already fixed.
                  AND (superseded_by IS NULL OR superseded_by <> %s)
                ORDER BY embedding <=> %s::vector
                LIMIT 1""", (vec, memory_id, memory_id, vec))
        near = cur.fetchone()
        if near and near[2] is not None and float(near[2]) >= NEAR_DUPLICATE:
            out.append({
                "code": "near_duplicate",
                "message": (f"near-identical to memory {near[0]} ({float(near[2]):.3f} "
                            f"similarity): \"{(near[1] or '')[:60]}\". If this replaces "
                            f"it, call supersede({near[0]}, {memory_id}) so recall "
                            f"prefers the new one."),
            })

    # 3. WEAK SUBJECT. The subject is the strongest retrieval handle a memory
    #    has — it is what the health probe queries with and what gets injected
    #    in full. A path or a bare URL is not a description of anything.
    if len(subject.strip()) < 15:
        out.append({"code": "weak_subject",
                    "message": "subject is very short — it is the main retrieval "
                               "handle and what a future agent sees first."})
    elif _URLISH.match(subject.strip()):
        out.append({"code": "weak_subject",
                    "message": "subject looks like a path or URL rather than a "
                               "description — it will not match how anyone asks for it."})

    # 4. NO PROJECT SCOPE.
    if not project:
        out.append({"code": "no_project",
                    "message": "no project scope — this memory is a candidate for "
                               "every query in every project on this brain."})

    # 5. LONG BODY. Recall injects a preview, so past this length most of the
    #    memory never reaches the context and the cut is made by position, not
    #    importance.
    if len(body) > LONG_BODY:
        out.append({"code": "long_body",
                    "message": f"body is {len(body)} chars — recall injects a preview, "
                               f"so put the conclusion FIRST; the tail may never be seen."})

    cur.close()
    return out


def messages(conn, memory_id: int) -> List[str]:
    """Just the human-readable strings, for callers that pass them to a model."""
    return [w["message"] for w in inspect(conn, memory_id)]
