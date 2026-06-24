"""
Temporal anchoring — for claims whose correct tense depends on the calendar,
not on how long ago the row was written or last accessed.

Example: "next year's Olympics" is upcoming, current, or past depending on
today's date vs the Games' own dates — not on the memory's age. Generic
weight decay (path_memory.aging) answers "how much should we still trust
this." This module answers "what tense should this be read in, right now."

A memory only carries a temporal anchor if temporal_anchor_start is set.
temporal_anchor_end defaults to temporal_anchor_start for single-day events.
"""
from datetime import date
from typing import Optional, List, Dict, Any
from .db import get_conn

STATUS_UPCOMING = "upcoming"
STATUS_CURRENT = "current"
STATUS_PAST = "past"


def temporal_status(
    anchor_start: Optional[date],
    anchor_end: Optional[date] = None,
    today: Optional[date] = None,
) -> Optional[str]:
    """
    Compute live tense status for a calendar-anchored claim.

    Returns None if anchor_start is None (claim isn't calendar-anchored).
    """
    if anchor_start is None:
        return None
    end = anchor_end or anchor_start
    today = today or date.today()
    if today < anchor_start:
        return STATUS_UPCOMING
    if today > end:
        return STATUS_PAST
    return STATUS_CURRENT


def needs_retensing_sweep(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Find active, calendar-anchored memories and report their live status.

    This is the actual scanner that closes the gap left by the production pipeline's
    `what_went_before.refresh_required`, which is only ever populated by a
    human or AI judgment call at recycle time — nothing upstream currently
    detects relative-date staleness on its own. Run this periodically (or
    before a recycle pass) to surface anchors whose status may now mismatch
    the frozen wording in `body`.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """SELECT id, person, subject, body, temporal_anchor_start, temporal_anchor_end
           FROM memories
           WHERE archived = false AND temporal_anchor_start IS NOT NULL
           ORDER BY temporal_anchor_start
           LIMIT %s""",
        (limit,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    results = []
    for row in rows:
        status = temporal_status(row[4], row[5])
        results.append({
            "id": row[0],
            "person": row[1],
            "subject": row[2],
            "body": row[3],
            "temporal_anchor_start": row[4],
            "temporal_anchor_end": row[5],
            "temporal_status": status,
        })
    return results
