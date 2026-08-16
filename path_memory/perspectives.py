"""
Fan-out perspective lenses — the "many ways of looking at one memory" layer.

Each memory is also indexed under several *orthogonal* lenses (its themes, the
questions it answers, the different names it goes by), generated at high
temperature and stored as separate retrieval handles in memory_perspectives.
A memory becomes findable from angles its literal wording would never match.

Add a lens to PERSPECTIVE_LENSES and the rest of the pipeline picks it up
automatically — but keep lenses genuinely orthogonal; redundant lenses only add
cost and noise, not recall.

WHICH LENSES ARE ACTUALLY GENERATED, and why that is now one instead of three.

All three shipped from the start on the reasoning that more angles must mean
better recall. Measured on a 4,125-memory brain (2026-08-16), three experiments,
two ground truths, paired bootstrap throughout:

  * DIRECT LOOKUP — a question the memory answers, which is exactly what the
    `questions` lens is for. questions +0.055 MRR (p=0.015) and hit@1 0.627 ->
    0.707. thematic +0.005 (p=0.184). vantages +0.002 (p=0.399).
  * ASSOCIATIVE HOP — find a different, related memory. No lens configuration
    beat using none at all, and all-three-merged was mildly harmful.
  * `questions` alone scored 0.7993 against 0.7968 for all three merged, so the
    other two contributed nothing even where lenses clearly work.

thematic and vantages changed 4-10 results out of 150. They are inert, and each
costs a model call on every single Memory.save(). So generation defaults to the
one that earns its keep — a 3x reduction in the most expensive part of a write,
with no measured retrieval loss anywhere.

They are kept defined, not deleted: ENGRAM_LENSES can re-enable them, and one
honest gap justifies keeping the door open — `vantages` is designed for
alias-shaped queries ("what does the production line call this?"), and none of
the three experiments probed that. It was retired for being inert on the
queries that were tested, which is not the same as proven useless.
"""
import os

from .embed import embed
from .llm import complete_text

PERSPECTIVE_LENSES = {
    "thematic": (
        "You are the RIGHT-HEMISPHERE lens of a memory system. Re-describe the memory "
        "below NOT by its literal facts but by its gist, deeper themes, what it is really "
        "about, and any analogies or cross-domain resonances it evokes. Be evocative and "
        "associative, 2-3 sentences — surface angles the literal text would miss."
    ),
    "questions": (
        "You are the QUERY lens of a memory system. List 4-7 short natural-language "
        "questions or needs someone would be trying to solve at the moment THIS memory is "
        "exactly what they need, one per line, phrased the way a person would actually ask."
    ),
    "vantages": (
        "You are the VANTAGE lens of a memory system. Name the SAME thing(s) in this memory "
        "as they would be called or framed from different roles, contexts, or disciplines — "
        "the synonyms, aliases, and alternative framings for the same underlying referent "
        "(the way one artifact can be an 'egg' to a user, a 'seed' to the architecture, and "
        "an 'int package' to the production line). List the alternative names/framings and "
        "the viewpoint each comes from, 3-6 short lines."
    ),
}

# Which lenses are generated on save. Comma-separated names in ENGRAM_LENSES
# override; "all" restores the historical three. See the module docstring for
# the measurements behind the default.
ACTIVE_LENSES = tuple(
    PERSPECTIVE_LENSES if os.environ.get("ENGRAM_LENSES", "").strip().lower() == "all"
    else [n.strip() for n in os.environ.get("ENGRAM_LENSES", "questions").split(",")
          if n.strip() in PERSPECTIVE_LENSES]
) or ("questions",)


def _generate(lens_prompt, person, subject, body):
    """One lens. Returns the text, or None if the model did not produce a
    complete one.

    stop_reason is checked because this call has a 220-token ceiling and a lens
    becomes a SEARCH HANDLE — it is embedded and matched against future queries.
    A response cut off at max_tokens returns HTTP 200 with a plausible fragment,
    and storing that fragment gives the memory a permanently mangled handle that
    nothing would ever flag. Half a lens is worse than no lens: the memory still
    has its literal embedding to be found by, but a truncated handle actively
    misdirects recall.
    """
    from anthropic import Anthropic
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=220,
        temperature=1.0,
        messages=[{"role": "user", "content":
            f"{lens_prompt}\n\nEntity: {person or '(none)'}\nSubject: {subject}\nBody: {body[:1500]}"}],
    )
    return complete_text(msg, what=f"lens for {subject!r}")


def store_perspectives(cur, memory_id, person, subject, body):
    """
    Regenerate every fan-out lens for a memory (idempotent — clears old lenses
    first). Uses the caller's cursor so it joins the same transaction as the
    save. A failed lens is skipped, never fatal to the save. Returns the count
    of lenses actually stored.
    """
    # Only the ACTIVE lenses are deleted and rewritten. A brain that once ran
    # with all three keeps those rows: they cost nothing to leave, retrieval
    # selects which types it queries, and deleting measured-inert data would
    # destroy the only evidence available if the question is ever reopened.
    cur.execute("DELETE FROM memory_perspectives WHERE memory_id = %s "
                "AND perspective = ANY(%s)", (memory_id, list(ACTIVE_LENSES)))
    stored = 0
    for name in ACTIVE_LENSES:
        prompt = PERSPECTIVE_LENSES[name]
        try:
            content = _generate(prompt, person, subject, body)
            if not content:
                continue      # incomplete or refused — never store a partial handle
            vec = embed([content])[0]
            vec_str = "[" + ",".join(str(x) for x in vec) + "]"
            cur.execute(
                "INSERT INTO memory_perspectives (memory_id, perspective, content, embedding) "
                "VALUES (%s, %s, %s, %s::vector)",
                (memory_id, name, content, vec_str),
            )
            stored += 1
        except Exception:
            pass  # a missing lens must never block the save
    return stored


def backfill(batch=None):
    """Generate the ACTIVE lens set for every memory missing any of it.
    Returns the number of memories processed.

    Counts only the active lens types. Counting every type would let a memory
    carrying two now-retired lenses and none of the active one look complete —
    the exact row that most needs backfilling, silently skipped.
    """
    from .db import get_conn
    conn = get_conn()
    cur = conn.cursor()
    sql = """SELECT m.id, m.person, m.subject, m.body
             FROM memories m
             LEFT JOIN (SELECT memory_id, count(DISTINCT perspective) n
                        FROM memory_perspectives
                        WHERE perspective = ANY(%s)
                        GROUP BY memory_id) p ON p.memory_id = m.id
             WHERE m.body IS NOT NULL AND COALESCE(p.n, 0) < %s
             ORDER BY m.id"""
    args = [list(ACTIVE_LENSES), len(ACTIVE_LENSES)]
    if batch:
        sql += " LIMIT %s"
        args.append(batch)
    cur.execute(sql, args)
    rows = cur.fetchall()
    for mid, person, subject, body in rows:
        store_perspectives(cur, mid, person, subject, body)
        conn.commit()
    cur.close()
    conn.close()
    return len(rows)
