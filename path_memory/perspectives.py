"""
Fan-out perspective lenses — the "many ways of looking at one memory" layer.

Each memory is also indexed under several *orthogonal* lenses (its themes, the
questions it answers, the different names it goes by), generated at high
temperature and stored as separate retrieval handles in memory_perspectives.
A memory becomes findable from angles its literal wording would never match.

Add a lens to PERSPECTIVE_LENSES and the rest of the pipeline picks it up
automatically — but keep lenses genuinely orthogonal; redundant lenses only add
cost and noise, not recall.
"""
import os
from .embed import embed

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


def _generate(lens_prompt, person, subject, body):
    from anthropic import Anthropic
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=220,
        temperature=1.0,
        messages=[{"role": "user", "content":
            f"{lens_prompt}\n\nEntity: {person or '(none)'}\nSubject: {subject}\nBody: {body[:1500]}"}],
    )
    return msg.content[0].text.strip()


def store_perspectives(cur, memory_id, person, subject, body):
    """
    Regenerate every fan-out lens for a memory (idempotent — clears old lenses
    first). Uses the caller's cursor so it joins the same transaction as the
    save. A failed lens is skipped, never fatal to the save. Returns the count
    of lenses actually stored.
    """
    cur.execute("DELETE FROM memory_perspectives WHERE memory_id = %s", (memory_id,))
    stored = 0
    for name, prompt in PERSPECTIVE_LENSES.items():
        try:
            content = _generate(prompt, person, subject, body)
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
    """Generate the full lens set for every memory missing any of them.
    Returns the number of memories processed."""
    from .db import get_conn
    conn = get_conn()
    cur = conn.cursor()
    sql = """SELECT m.id, m.person, m.subject, m.body
             FROM memories m
             LEFT JOIN (SELECT memory_id, count(DISTINCT perspective) n
                        FROM memory_perspectives GROUP BY memory_id) p ON p.memory_id = m.id
             WHERE m.body IS NOT NULL AND COALESCE(p.n, 0) < %s
             ORDER BY m.id"""
    args = [len(PERSPECTIVE_LENSES)]
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
