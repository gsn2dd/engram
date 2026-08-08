"""
Keep the boundary that `collapse` resolves.

`recall(collapse=True)` already does the expensive part: it resolves the blurry
relevance field into a clean keep/drop boundary and returns what sits above it.
Then it throws the boundary away. The next identical question pays for the same
resolution again, and nothing in the brain records that this particular set of
memories is a thing that goes together.

This module keeps it. When a collapse resolves cleanly, the resolved set gets a
stable **key** and a human-readable **name**, and both are stored with the
cluster's centroid. That buys three things:

  1. A CHEAP SECOND PATH. Matching a query against a handful of key centroids
     is a scan of the doorways, not of the whole corpus — embeddings resolve to
     a key, and the key resolves to rows by exact id. Fuzzy on the way in,
     exact on the way out.
  2. A STABLE HANDLE. `recall_key("engram-ami")` returns the same doorway
     tomorrow. A cluster nobody can name is a cluster nobody can refer to.
  3. A RECORD THAT THE SET COHERES. The same member set resolving again reuses
     its key and bumps its count — so a doorway that keeps re-forming is
     visibly load-bearing, the same way a well-used edge is.

Honest limits, stated rather than buried:

  * A key is a SNAPSHOT of a resolution. Memories written after it formed may
    belong to the cluster and are not in it. `is_fresh()` reports that; the
    caller decides. Refreshing stale keys is consolidation's job — the offline
    pass that already re-derives edge strengths. Encoding happens now,
    reconsolidation happens later; this follows the same split.
  * The name is generated. It is a label for humans and agents, not an
    authority — the member set is the truth.
"""

import hashlib
import re
import os
import sys
from typing import Dict, List, Optional

from .llm import complete_text

# Below this the resolution wasn't clean enough to be worth naming: a shallow
# cliff means the field never really separated into wall and air.
MIN_GAP_TO_KEEP = float(os.environ.get("ENGRAM_BOUNDARY_MIN_GAP", "0.18"))
# How close a query must sit to a stored centroid to reuse its doorway.
#
# Calibrate this against CENTROIDS, not against memories. A centroid is a mean,
# and averaging washes out the specific wording any one member shares with a
# query — so query-to-centroid similarity runs systematically lower than
# query-to-memory similarity, and a threshold carried over from document
# matching rejects everything. This was set at 0.82 on that intuition and never
# matched a single doorway.
#
# Measured on a 3,826-memory brain with gemini-embedding-001:
#     exact original query -> its own doorway   0.697
#     paraphrases          -> correct doorway   0.662, 0.724
#     unrelated queries    -> nearest doorway   0.499, 0.522
# so 0.60 sits in the gap with room on both sides.
#
# Honest limit, same as `collapse`'s min_gap: this is a heuristic fitted to one
# corpus and one embedding model. Re-measure after changing either. A tighter
# design would use the margin over the runner-up instead of an absolute floor,
# but that degrades exactly when two doorways are near-duplicates — which is
# precisely when either answer would have been fine.
REUSE_SIMILARITY = float(os.environ.get("ENGRAM_BOUNDARY_REUSE_SIM", "0.60"))
# A one-memory "cluster" is just a hit; there is no set to name.
MIN_MEMBERS = int(os.environ.get("ENGRAM_BOUNDARY_MIN_MEMBERS", "2"))

NAME_MODEL = os.environ.get("ENGRAM_BOUNDARY_NAME_MODEL", "claude-opus-5")

NAME_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "2-4 word lowercase-hyphenated handle for what this set of memories is about.",
        },
        "gist": {"type": "string", "description": "One sentence: what a reader gets from this set."},
    },
    "required": ["name", "gist"],
    "additionalProperties": False,
}


def derive_key(member_ids) -> str:
    """
    Stable identity for a resolved set: same members, same key.

    Derived from the membership rather than assigned, so the SECOND time a
    cluster resolves it lands on its existing key instead of creating a rival —
    which is what makes the usage count meaningful.
    """
    joined = ",".join(str(i) for i in sorted(int(m) for m in member_ids))
    return hashlib.sha256(joined.encode()).hexdigest()[:16]


def _centroid(cur, member_ids) -> Optional[str]:
    """Mean embedding of the members, as a pgvector literal."""
    cur.execute(
        "SELECT avg(embedding)::text FROM memories WHERE id = ANY(%s) AND embedding IS NOT NULL",
        (list(member_ids),),
    )
    row = cur.fetchone()
    return row[0] if row and row[0] else None


def _name_cluster(subjects: List[str], query: Optional[str]) -> Dict[str, str]:
    """
    Name the resolved set.

    Naming is a meaning judgment — what are these memories collectively about? —
    so it goes to a model. The fallback is deliberately dumb rather than clever:
    a wrong-but-obvious label beats a plausible invented one, because the name
    is the handle a human will later trust.
    """
    fallback = {
        "name": (subjects[0][:40].lower().replace(" ", "-") if subjects else "unnamed-cluster"),
        "gist": "",
    }
    try:
        from anthropic import Anthropic
    except Exception:
        return fallback
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return fallback

    # Subjects come straight out of the brain and can carry tabs, newlines and
    # stray control characters from whatever ingested them. Feeding those in raw
    # produced names and gists with the debris embedded — and the name is the
    # handle a human is meant to type, so it has to be clean at the source
    # rather than tidied at the point of display.
    def _flatten(text: str) -> str:
        return " ".join(str(text or "").split())[:160]

    listing = "\n".join(f"- {_flatten(s)}" for s in subjects[:25] if _flatten(s))
    try:
        response = Anthropic().messages.create(
            model=NAME_MODEL,
            # Thinking is on by default and counts against max_tokens; leave
            # headroom or the JSON truncates mid-object.
            max_tokens=1500,
            system=(
                "You name clusters of memories that a retrieval system resolved as belonging "
                "together. The name is a durable handle someone will type later, so favour the "
                "concrete subject over an abstract category. Never invent detail that is not in "
                "the list."
            ),
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": NAME_SCHEMA},
            },
            messages=[{
                "role": "user",
                "content": (f"Query that resolved this set: {query or '(none)'}\n\n"
                            f"Member subjects:\n{listing}"),
            }],
        )
    except Exception:
        return fallback

    # The max_tokens comment above anticipated truncation but nothing checked
    # for it: a cut-off response produced invalid JSON, fell through to the
    # generic except, and returned the dumb fallback. Safe, but indistinguishable
    # from "no model configured" — a degradation path that is also the error
    # path is how a failure becomes invisible.
    text = complete_text(response, what="cluster naming")
    if not text:
        return fallback
    try:
        import json
        parsed = json.loads(text)
        name = " ".join(str(parsed.get("name") or "").split()).lower()
        # Keep the handle typeable: it is an identifier people and agents pass
        # around, not prose.
        name = re.sub(r"[^a-z0-9-]+", "-", name).strip("-")[:60]
        gist = " ".join(str(parsed.get("gist") or "").split())[:400]
        return {"name": name or fallback["name"], "gist": gist}
    except Exception:
        return fallback


def record(cur, results, query: Optional[str] = None, cut_gap: Optional[float] = None,
           name: bool = True) -> Optional[str]:
    """
    Persist the boundary a collapse just resolved. Returns the key, or None if
    this resolution wasn't worth keeping.

    Never raises: failing to remember a doorway must not fail the recall that
    found it.
    """
    try:
        member_ids = [r["id"] for r in results if r.get("id") is not None]
        if len(member_ids) < MIN_MEMBERS:
            return None
        if cut_gap is not None and cut_gap < MIN_GAP_TO_KEEP:
            # No clean wall — it was all air. Nothing was resolved, so there is
            # no boundary to keep.
            return None

        key = derive_key(member_ids)
        cur.execute("SELECT key FROM collapse_keys WHERE key = %s", (key,))
        if cur.fetchone():
            # Seen before: the same set re-resolved. That is the signal worth
            # recording — bump it rather than rewriting it.
            cur.execute(
                "UPDATE collapse_keys SET query_count = query_count + 1, last_used = now(), "
                "stale = false WHERE key = %s", (key,))
            return key

        centroid = _centroid(cur, member_ids)
        cur.execute("SELECT subject FROM memories WHERE id = ANY(%s)", (member_ids,))
        subjects = [r[0] or "" for r in cur.fetchall()]
        named = _name_cluster(subjects, query) if name else {"name": None, "gist": ""}

        cur.execute(
            """INSERT INTO collapse_keys
                   (key, name, gist, centroid, member_ids, cut_gap, example_query)
               VALUES (%s,%s,%s,%s::vector,%s,%s,%s)
               ON CONFLICT (key) DO NOTHING""",
            (key, named["name"], named["gist"], centroid, member_ids, cut_gap, query),
        )
        return key
    except Exception as exc:
        print(f"[engram] could not record boundary: {exc}", file=sys.stderr)
        return None


def is_fresh(cur, key: str) -> bool:
    """
    True if no memory has been written since this doorway was resolved.

    A stale key is not wrong — its members are still real memories that cohered.
    It is INCOMPLETE: something newer might belong. Callers that need certainty
    re-resolve; callers that want speed take it and know what they took.
    """
    cur.execute("SELECT formed_at FROM collapse_keys WHERE key = %s", (key,))
    row = cur.fetchone()
    if not row:
        return False
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM memories WHERE NOT archived AND created_at > %s)", (row[0],))
    return not cur.fetchone()[0]


def by_name(cur, name: str) -> Optional[Dict]:
    """Exact lookup by handle — the cheap path, no vectors involved at all."""
    cur.execute(
        "SELECT key, name, gist, member_ids, formed_at FROM collapse_keys "
        "WHERE name = %s ORDER BY query_count DESC LIMIT 1", (name,))
    row = cur.fetchone()
    if not row:
        return None
    cur.execute(
        "UPDATE collapse_keys SET query_count = query_count + 1, last_used = now() WHERE key = %s",
        (row[0],))
    return {"key": row[0], "name": row[1], "gist": row[2], "member_ids": row[3],
            "formed_at": row[4], "fresh": is_fresh(cur, row[0])}


def by_vector(cur, query_vec, threshold: float = REUSE_SIMILARITY) -> Optional[Dict]:
    """
    Find an existing doorway close enough to this query to reuse.

    This is the reversal: embeddings resolve to a KEY, and the key resolves to
    rows by exact id. The vector comparison runs over the doorways — a handful
    of rows — not over the corpus.
    """
    vec = "[" + ",".join(str(x) for x in query_vec) + "]"
    cur.execute(
        """SELECT key, name, gist, member_ids, formed_at, 1 - (centroid <=> %s::vector) AS sim
           FROM collapse_keys
           WHERE centroid IS NOT NULL AND NOT stale
           ORDER BY centroid <=> %s::vector LIMIT 1""",
        (vec, vec),
    )
    row = cur.fetchone()
    if not row or row[5] < threshold:
        return None
    cur.execute(
        "UPDATE collapse_keys SET query_count = query_count + 1, last_used = now() WHERE key = %s",
        (row[0],))
    return {"key": row[0], "name": row[1], "gist": row[2], "member_ids": row[3],
            "formed_at": row[4], "similarity": row[5], "fresh": is_fresh(cur, row[0])}


def members(cur, member_ids) -> List[Dict]:
    """The exact-lookup half: rows by id, no scoring, no scan."""
    cur.execute(
        """SELECT id, person, subject, body, created_at, project
           FROM memories WHERE id = ANY(%s) AND NOT archived""",
        (list(member_ids),),
    )
    return [{"id": r[0], "person": r[1], "subject": r[2], "body": r[3],
             "created_at": r[4], "project": r[5]} for r in cur.fetchall()]


def mark_stale_since(cur) -> int:
    """
    Flag doorways that predate the newest memory, for consolidation to redo.

    Called by the offline pass, not by recall: a key going stale is not an
    error, it is the brain having learned something since. Deciding what that
    means is exactly the work that belongs in the pass that also decays edges
    and compacts footprints — the part of memory that runs while nothing is
    using it.
    """
    cur.execute(
        """UPDATE collapse_keys SET stale = true
           WHERE NOT stale AND EXISTS (
               SELECT 1 FROM memories m
               WHERE NOT m.archived AND m.created_at > collapse_keys.formed_at)""")
    return cur.rowcount
