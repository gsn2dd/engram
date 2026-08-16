"""
Recall events — separating what was SHOWN from what was USED.

THE PROBLEM THIS EXISTS TO FIX. `recall()` strengthens node weights and lays
down association edges for everything it returns. That is exposure, not use, and
the two are not the same thing: a memory can be returned, read, and ignored.
Learning from exposure makes the graph a record of the ranker's own habits —
and with an always-on prompt-time recall hook, a self-confirming one, because
what gets surfaced gets strengthened and therefore surfaced again.

The evidence that they differ is not theoretical. Given the provably correct
memory, a model still often answers wrong — it can ignore what it was handed,
misread it, or be confused by it. So "this was returned" is evidence about the
RANKER; "this was used" is evidence about the MEMORY. Only the second is worth
learning from, and this engine was learning from the first.

HOW ATTRIBUTION IS ALLOWED TO WORK. Recording what was shown is free and
synchronous. Deciding what was used is neither — it depends on what happened
next, which has not happened yet when recall returns. So `used` is filled in
LATE, by whoever can actually tell:

  explicit  — the agent reports it (MCP `mark_used`). Highest precision,
              lowest volume; agents forget, which is exactly why this cannot be
              the only path.
  citation  — a structural signal in what followed: the answer cited the
              memory, or a memory written afterwards linked to it.
  model     — an offline pass reads the exchange and judges. Budgeted, like
              every other model call in this engine.

NULL `used` means "nobody has judged this yet" and is deliberately different
from `[]`, which means "judged, and nothing shown was used" — the single most
informative outcome available, because it is a recall that failed while looking
like it worked.

WHY THE RANKER DOES NOT YET READ ANY OF THIS. There is no use data. On the brain
this was built against, `success_count` summed to 5 across 4,125 memories — the
column existed and nothing ever wrote to it. Turning a ranking term on before
there is data to justify it is precisely the mistake that put a use-history
bonus of 0.5 into production and left it there, unmeasured, making recall worse
than plain cosine. So: capture now, measure later, and only then rank. See
`readiness()` for the trigger, and docs/RECALL_MEASUREMENT.md for the ladder
that will judge it.
"""
import json
from typing import Any, Dict, List, Optional

from .db import get_conn

# How many attributed events before the success-signal rung is worth running.
# Not a statistical result — a floor below which any difference the bench
# reported would be noise, chosen to be small enough to reach in ordinary use
# and large enough to beat a handful of lucky sessions.
READY_AT = 200


def record(query: str, results: List[Dict[str, Any]], project: Optional[str] = None,
           session_id: Optional[str] = None, source: Optional[str] = None,
           conn=None) -> Optional[int]:
    """Log what one recall showed. Returns the event id, or None if logging
    failed.

    NEVER RAISES. This sits on the read path of a memory system whose first duty
    is to answer; an analytics write must not be able to take recall down with
    it. A lost event is a gap in a dataset, a raised exception is a broken brain.
    """
    if not results:
        return None
    owns = conn is None
    try:
        conn = conn or get_conn()
        shown = [{"id": r["id"], "rank": i + 1, "score": r.get("score")}
                 for i, r in enumerate(results) if not r.get("serendipity")]
        if not shown:
            return None
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO recall_events (query, project, session_id, source, shown)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (query, project, session_id, source, json.dumps(shown)),
        )
        event_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        return event_id
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return None
    finally:
        if owns and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def mark_used(event_id: int, used_ids: List[int], how: str = "explicit",
              strengthen: bool = True) -> bool:
    """Record which of an event's shown memories actually got used.

    An empty `used_ids` is a legitimate and valuable answer — it says the recall
    failed while appearing to succeed — so it is stored rather than skipped.

    `strengthen` reinforces the used memories through Memory.used(). It is a
    parameter because attribution and reinforcement are separable: a low-
    confidence attributor should be able to record its judgement for analysis
    without feeding it into the graph.
    """
    used_ids = sorted({int(i) for i in (used_ids or [])})
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """UPDATE recall_events
                  SET used = %s, attributed_at = now(), attribution = %s
                WHERE id = %s""",
            (json.dumps(used_ids), how, event_id),
        )
        updated = cur.rowcount
        conn.commit()
        cur.close()
        if updated and used_ids and strengthen:
            from .memory import Memory
            Memory.used(used_ids)
        return bool(updated)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def unattributed(limit: int = 50, session_id: Optional[str] = None,
                 older_than_seconds: int = 0) -> List[Dict[str, Any]]:
    """Events nobody has judged yet — the attributor's work queue.

    `older_than_seconds` exists because attribution needs the conversation that
    FOLLOWED the recall. Judging an event the moment it is written would be
    reading the answer before it was given.
    """
    conn = get_conn()
    cur = conn.cursor()
    sql = ["SELECT id, created_at, query, project, session_id, source, shown "
           "FROM recall_events WHERE used IS NULL"]
    params: list = []
    if session_id:
        sql.append("AND session_id = %s")
        params.append(session_id)
    if older_than_seconds:
        sql.append("AND created_at < now() - (%s * interval '1 second')")
        params.append(older_than_seconds)
    sql.append("ORDER BY created_at LIMIT %s")
    params.append(limit)
    cur.execute(" ".join(sql), params)
    rows = [{"id": r[0], "created_at": r[1], "query": r[2], "project": r[3],
             "session_id": r[4], "source": r[5], "shown": r[6]}
            for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def readiness() -> Dict[str, Any]:
    """Is there enough attributed data to ask whether use-signal ranking helps?

    This is here so the mechanism cannot quietly become another dormant feature.
    `success_count` sat in the schema for months with a total of 5 across the
    whole corpus and nothing calling it; the way that happens is that no one
    ever states what "enough" would look like.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM recall_events")
    total = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM recall_events WHERE used IS NOT NULL")
    attributed = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM recall_events WHERE used = '[]'::jsonb")
    empty = cur.fetchone()[0]
    cur.execute("SELECT coalesce(sum(success_count), 0) FROM memories")
    successes = cur.fetchone()[0]
    cur.close()
    conn.close()
    return {
        "events": total,
        "attributed": attributed,
        # Recalls judged to have helped with nothing. A high share here is the
        # single most actionable number this table produces: it is recall
        # failing while looking like it worked.
        "attributed_empty": empty,
        "memory_use_marks": successes,
        "ready_at": READY_AT,
        "ready": attributed >= READY_AT,
    }
