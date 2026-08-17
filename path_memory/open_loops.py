"""
Open loops — what was concluded and never done.

THE CASE THIS EXISTS FOR. On 2026-08-08 a root cause was diagnosed for a cron
job that had silently stopped working, written down correctly, and closed with
the exact one-line fix. The fix was never applied. Eight days and 192 skipped
runs later the same root cause was diagnosed again from first principles, by an
agent that held the original in its own memory and never looked. Two other
findings that week — a self-test reporting total failure, and a red CI build —
were equally correct and equally unexecuted.

None of that is a recall failure. Recall surfaces the original memory at rank 2
for three different natural phrasings. It is a CLOSING failure: nothing in the
system had any concept of a conclusion that was still outstanding.

WHY THE DETECTOR NEEDS A MODEL, AND WHY IT IS NOT ONLY A MODEL. Measured on the
real corpus: of 865 curated non-templated memories, "should be" appears in 48,
"pending" in 75, "THE FIX" in 56. A regex-only detector flags about a fifth of
everything, and most of those actions were carried out in the same session that
wrote them. The hard half is not finding intent language — it is judging
whether the intent was ever discharged, and that needs reading.

So the shape is the one the dreaming pass already uses and that this engine
keeps arriving at: A CHEAP FILTER NARROWS, A MODEL DECIDES, A BUDGET BOUNDS.
The regex is a way to not pay for 865 judgements; it is not the judgement.

THE BAR IS DELIBERATELY HIGH. A list of maybes is a list nobody reads, and this
whole feature exists because three things nobody read caused a month of silent
breakage. The model is told to return an action only when the memory says
plainly that something was NOT done at the time of writing. "We should probably
think about X" is not an open loop. "The fix is to remove the wrapper" — in a
memory that never says it was removed — is.

SILENCE IS NOT COMPLETION. An open loop ages; it never expires. The only things
that close one are evidence: the memory was superseded, someone closed it
explicitly, or a later memory reported it done.
"""
import os
import re
from typing import Any, Dict, List, Optional

from .db import get_conn
from .llm import complete_text

# Model calls per run. The detector is idempotent and watermark-free — it simply
# never re-judges a memory already in the table — so an unfinished sweep is
# resumed by the next run rather than restarted.
DEFAULT_BUDGET = int(os.environ.get("ENGRAM_LOOPS_BUDGET", "40"))

# The cheap filter. Every phrase here was counted on a real corpus before being
# included; the job is to cut 865 candidates to a couple of hundred, not to be
# right. Being over-inclusive is correct at this stage — the model is the part
# that says no.
MARKERS = re.compile(
    r"\b(the fix is|the fix was|still manual|not started|not yet|"
    r"next step|next:|todo|still open|remains open|open:|needs to be|"
    r"needs doing|should be|worth doing|to be done|outstanding|"
    r"when it pays|revisit|follow.?up|not applied|never applied|"
    r"remains? (open|outstanding|manual)|left to do|still to)\b",
    re.I,
)

PROMPT = """You are auditing an engineering memory to find UNFINISHED WORK.

Answer with one line, exactly one of:
NONE
ACTION: <one short line naming what was to be done>

Say ACTION only if the memory states plainly that something WAS NOT DONE at the
time it was written — an unapplied fix, a deferred task, an explicit "next", a
"still manual" step. The action must be concrete enough that someone could tell
whether it has since happened.

Say NONE for: work the memory reports as completed, general advice or lessons,
vague intentions ("we should think about X"), descriptions of how something
works, and anything where the outstanding step is not clearly stated.

Bias hard toward NONE. A false ACTION costs more than a missed one, because a
list of maybes is a list nobody reads.

Subject: {subject}

Body:
{body}"""


def _judge(subject: str, body: str) -> Optional[str]:
    """Return the action line, or None. Never raises."""
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=80,
            messages=[{"role": "user", "content":
                       PROMPT.format(subject=subject, body=(body or "")[:4000])}],
        )
        text = complete_text(msg, what="open-loop judgement", quiet=True)
        if not text:
            return None
        text = text.strip()
        if text.upper().startswith("ACTION:"):
            action = text.split(":", 1)[1].strip()
            return action or None
        return None
    except Exception:
        return None


# How far back to look for unfinished work. Watching the first day of real
# operation: detection swept months of history and opened ~12 loops an hour with
# nothing closing them, reaching 132 open of which 119 were over a week old.
# That is the failure this feature exists to prevent, reproduced inside it — a
# list too long to read is a list nobody reads.
#
# The cause is not a bad detector; those loops are genuine. It is that mining
# years of a fast-moving project's history yields archaeology, not work.
# Something concluded and abandoned four months ago on a project that has since
# moved on is a fact about the past. Something concluded last week is a job.
DEFAULT_SINCE_DAYS = int(os.environ.get("ENGRAM_LOOPS_SINCE_DAYS", "45"))


def detect(budget: int = DEFAULT_BUDGET, project: Optional[str] = None,
           tiers=("curated", "insight", "decision", "project"),
           since_days: Optional[int] = DEFAULT_SINCE_DAYS) -> Dict[str, Any]:
    """Judge memories not yet judged. Returns a report.

    Records a row for EVERY memory judged, including the ones that carry no
    commitment (`not_actionable`). Without that the detector would re-read the
    whole corpus on every run and the budget would never reach new material.

    `since_days=None` mines the whole history — useful once, deliberately not
    the default.
    """
    conn = get_conn()
    cur = conn.cursor()
    sql = ["""SELECT m.id, m.subject, m.body, m.project
                FROM memories m
                LEFT JOIN open_loops o ON o.memory_id = m.id
               WHERE o.memory_id IS NULL
                 AND m.archived = false
                 AND m.tier = ANY(%s)
                 AND m.body IS NOT NULL"""]
    params: List[Any] = [list(tiers)]
    if since_days:
        sql.append("AND m.created_at > now() - (%s * interval '1 day')")
        params.append(since_days)
    if project:
        sql.append("AND m.project = %s")
        params.append(project)
    # Newest first: an unfinished loop from last week is far more likely to
    # still matter than one from a project that closed months ago.
    sql.append("ORDER BY m.created_at DESC LIMIT %s")
    params.append(budget * 12)   # prefilter rejects most, so over-fetch
    cur.execute(" ".join(sql), params)
    rows = cur.fetchall()

    judged = opened = spent = 0
    found: List[Dict[str, Any]] = []
    for mid, subject, body, proj in rows:
        if spent >= budget:
            break
        blob = f"{subject or ''}\n{body or ''}"
        if not MARKERS.search(blob):
            # Cheap rejection. Recorded so it is never reconsidered, which is
            # what makes repeated runs converge instead of re-reading.
            cur.execute("""INSERT INTO open_loops (memory_id, project, status)
                           VALUES (%s, %s, 'not_actionable')
                           ON CONFLICT (memory_id) DO NOTHING""", (mid, proj))
            judged += 1
            continue
        action = _judge(subject or "", body or "")
        spent += 1
        judged += 1
        status = "open" if action else "not_actionable"
        cur.execute("""INSERT INTO open_loops (memory_id, action, project, status)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (memory_id) DO NOTHING""",
                    (mid, action, proj, status))
        if action:
            opened += 1
            found.append({"memory_id": mid, "subject": subject, "action": action})
    conn.commit()
    cur.close()
    conn.close()
    return {"judged": judged, "opened": opened, "llm_calls": spent, "found": found}


def age_out(older_than_days: int = DEFAULT_SINCE_DAYS) -> int:
    """Move loops older than the detection window to `dismissed`.

    NOT `closed`. Nothing here claims the work was done — the distinction is the
    whole point, and `close_reason` says so explicitly. This only removes
    archaeology from the active list so the active list stays readable, which is
    the difference between a working reminder and the pile of unread findings
    that motivated the feature.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""UPDATE open_loops o
                      SET status = 'dismissed', closed_at = now(),
                          close_reason = 'aged out of the active window — NOT known to be done'
                     FROM memories m
                    WHERE m.id = o.memory_id AND o.status = 'open'
                      AND m.created_at < now() - (%s * interval '1 day')""",
                (older_than_days,))
    n = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return n


def close_superseded() -> int:
    """Close loops whose memory has been superseded. Free, and correct: a
    superseding memory is by definition a later statement about the same thing.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""UPDATE open_loops o
                      SET status = 'closed', closed_at = now(),
                          closed_by = m.superseded_by,
                          close_reason = 'superseded'
                     FROM memories m
                    WHERE m.id = o.memory_id
                      AND o.status = 'open'
                      AND m.superseded_by IS NOT NULL""")
    n = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return n


def close(memory_id: int, reason: str = "done", by: Optional[int] = None) -> bool:
    """Mark one loop closed."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""UPDATE open_loops
                      SET status = 'closed', closed_at = now(),
                          closed_by = %s, close_reason = %s
                    WHERE memory_id = %s AND status = 'open'""",
                (by, reason, memory_id))
    ok = cur.rowcount > 0
    conn.commit()
    cur.close()
    conn.close()
    return ok


def open_loops(project: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    """The outstanding list, oldest first — an open loop gets more important
    with age, not less, which is the opposite of how a feed is usually ordered.

    Also reports whether any later memory cites this one. That is not proof the
    work was done, and is deliberately not treated as closure; it is the
    difference between "nobody has looked at this since" and "this was
    revisited and still not finished", which are different kinds of stale.
    """
    conn = get_conn()
    cur = conn.cursor()
    sql = ["""SELECT o.memory_id, o.action, o.project, m.subject, m.created_at,
                     (SELECT count(*) FROM memories c
                       WHERE c.id > o.memory_id AND c.archived = false
                         AND c.body LIKE '%%[[' || o.memory_id || ']]%%')
                FROM open_loops o JOIN memories m ON m.id = o.memory_id
               WHERE o.status = 'open'"""]
    params: List[Any] = []
    if project:
        sql.append("AND o.project = %s")
        params.append(project)
    sql.append("ORDER BY m.created_at ASC LIMIT %s")
    params.append(limit)
    cur.execute(" ".join(sql), params)
    out = [{"memory_id": r[0], "action": r[1], "project": r[2], "subject": r[3],
            "created_at": r[4], "cited_since": r[5]} for r in cur.fetchall()]
    cur.close()
    conn.close()
    return out


def stats() -> Dict[str, Any]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT status, count(*) FROM open_loops GROUP BY status")
    by_status = dict(cur.fetchall())
    cur.execute("""SELECT count(*) FROM open_loops o JOIN memories m ON m.id = o.memory_id
                    WHERE o.status = 'open' AND m.created_at < now() - interval '7 days'""")
    stale = cur.fetchone()[0]
    cur.close()
    conn.close()
    return {"by_status": by_status, "open": by_status.get("open", 0),
            "open_over_7_days": stale}
