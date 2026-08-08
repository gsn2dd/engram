"""
The dreaming pass — what the brain does while nothing is using it.

The existing `consolidate()` already does the mechanical half: compact
co-recall footprints into the path graph, decay what went unused, archive what
faded. This is the other half — the part that finds connections and clarifies
the corpus for later recall:

    1. AGE the doorways   — flag resolutions the corpus has outgrown.
    2. PROMOTE            — a doorway that keeps re-forming becomes a topic.
                            Repeated resolution is the evidence that a set is a
                            durable thing rather than one query's accident.
    3. READ               — extract the subjects memories are actually ABOUT.
                            Transcripts included: a subject shows up in
                            conversation long before anyone writes a curated
                            memory about it. This is a model call, and it is
                            the only expensive stage.
    4. BACKFILL           — spread each known subject across the whole corpus
                            by literal term match. Free, exact, and reaches
                            backwards to memories written long before the topic
                            existed — which is what makes a sub-classification
                            useful on an old corpus, not just on new writes.
    5. SUMMARISE          — write a topic's gist back as a NEW memory, marked
                            origin='recycle'. Consolidation does not annotate
                            the trace, it writes a new one.

Why this runs offline rather than at write time: at encoding you cannot tell
which memories will turn out to belong together, and you cannot tell which half
of a memory mattered. After the corpus has been read a few times, you can.
Encoding now, reconsolidation later — the same split biology uses.

TWO FAILURE MODES DESIGNED AGAINST, both from the fact that a summary competes
with its own members in recall:

  * DOUBLE-COUNTING. A summary and its four members all ranking for one query
    fills the context with the same content four times. Summaries are marked
    origin='recycle' so recall can pick a level.
  * SUMMARIES OF SUMMARIES. Left unchecked, the pass would summarise its own
    output — a copy of a copy, drifting a little each time, hourly, with
    nothing flagging it. `derived_depth` caps it, and derived memories are
    excluded from being members of a new summary.

Everything is BOUNDED. This runs on a timer against a growing corpus, so every
stage takes a limit and the model-calling stages share one budget. An unbounded
nightly job on a brain that keeps growing is a bill that keeps growing.
"""

import os
import re
import sys
from typing import Dict, List, Optional

from .db import get_conn
from . import boundary

# Model calls per run, shared across the stages that name things. The tagging
# and ageing stages are free and are not counted.
DEFAULT_LLM_BUDGET = int(os.environ.get("ENGRAM_DREAM_LLM_BUDGET", "12"))

# A doorway must have re-formed this many times before it is a topic rather
# than one question someone happened to ask twice.
PROMOTE_AT = int(os.environ.get("ENGRAM_DREAM_PROMOTE_AT", "3"))

# Cluster/tag thresholds. Same caveat as everywhere else in this engine: fitted
# to one corpus and one embedding model, honest heuristics rather than theory.
CLUSTER_SIM = float(os.environ.get("ENGRAM_DREAM_CLUSTER_SIM", "0.62"))
TAG_SIM = float(os.environ.get("ENGRAM_DREAM_TAG_SIM", "0.60"))
MIN_CLUSTER = int(os.environ.get("ENGRAM_DREAM_MIN_CLUSTER", "3"))

# Derived memories may not be summarised again beyond this depth.
MAX_DERIVED_DEPTH = int(os.environ.get("ENGRAM_DREAM_MAX_DEPTH", "1"))


def _watermark(cur) -> int:
    """How far the reading stage has already got through the record set."""
    cur.execute("""CREATE TABLE IF NOT EXISTS dream_state (
                       id            integer PRIMARY KEY DEFAULT 1,
                       last_memory_id integer DEFAULT 0,
                       last_run_at    timestamptz,
                       CHECK (id = 1))""")
    cur.execute("INSERT INTO dream_state (id) VALUES (1) ON CONFLICT DO NOTHING")
    cur.execute("SELECT coalesce(last_memory_id, 0) FROM dream_state WHERE id = 1")
    return cur.fetchone()[0]


def _advance(cur, memory_id: int) -> None:
    cur.execute(
        "UPDATE dream_state SET last_memory_id = GREATEST(coalesce(last_memory_id,0), %s), "
        "last_run_at = now() WHERE id = 1", (memory_id,))


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").strip().lower()).strip("-")[:60]


class _Budget:
    """A hard ceiling on model calls for one run, so a growing corpus cannot
    quietly turn an hourly job into an unbounded bill."""

    def __init__(self, total: int):
        self.total = total
        self.spent = 0

    def take(self) -> bool:
        if self.spent >= self.total:
            return False
        self.spent += 1
        return True


# ---------------------------------------------------------------- stage 1 ---

def age_doorways(cur) -> int:
    """Flag doorways the corpus has outgrown. Stale is not wrong — the members
    still cohere — it is incomplete."""
    return boundary.mark_stale_since(cur)


# ---------------------------------------------------------------- stage 2 ---

def promote_doorways(cur, budget: _Budget, limit: int = 10) -> List[Dict]:
    """
    A doorway that keeps re-forming becomes a topic.

    This is the whole reason `query_count` is tracked. A set that resolves once
    is a query's answer; a set that resolves again and again is a subject the
    work keeps returning to, and that is what a sub-classification IS. Usage
    decides, not a human enumerating categories up front.
    """
    cur.execute(
        """SELECT k.key, k.name, k.gist, k.member_ids, k.query_count
           FROM collapse_keys k
           WHERE k.query_count >= %s AND k.name IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM topics t WHERE t.slug = k.name)
           ORDER BY k.query_count DESC LIMIT %s""",
        (PROMOTE_AT, limit),
    )
    promoted = []
    for key, name, gist, member_ids, count in cur.fetchall():
        # A doorway spans whatever its members span; a topic sits inside one
        # project. Use the members' dominant project.
        cur.execute(
            """SELECT project FROM memories WHERE id = ANY(%s) AND project IS NOT NULL
               GROUP BY project ORDER BY count(*) DESC LIMIT 1""", (member_ids,))
        row = cur.fetchone()
        if not row:
            continue
        project, slug = row[0], _slugify(name)
        if not slug:
            continue
        cur.execute(
            """INSERT INTO topics (project, slug, label, gist, centroid, source, member_count)
               SELECT %s, %s, %s, %s, avg(m.embedding), 'promoted', count(*)
               FROM memories m WHERE m.id = ANY(%s) AND m.embedding IS NOT NULL
               ON CONFLICT (project, slug) DO NOTHING""",
            (project, slug, name, gist, member_ids),
        )
        for mid in member_ids:
            cur.execute(
                """INSERT INTO memory_topics (memory_id, project, slug, confidence, assigned_by)
                   VALUES (%s,%s,%s,1.0,'promoted') ON CONFLICT DO NOTHING""",
                (mid, project, slug))
        promoted.append({"project": project, "slug": slug, "from_doorway": key,
                         "resolved_times": count})
    return promoted


# ---------------------------------------------------------------- stage 3 ---

TOPIC_SCHEMA = {
    "type": "object",
    "properties": {
        "memories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "topics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Lowercase-hyphenated subjects this memory is ABOUT.",
                    },
                },
                "required": ["id", "topics"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["memories"],
    "additionalProperties": False,
}

EXTRACT_SYSTEM = """You tag engineering memories with the specific subjects they are about.

A subject is a THING the work concerns: a place (banbury, belgrade), a named
component (intgen, first-officer, sitemap), a feature, a system, a customer. It
is not a register or a mood — "engineering-notes", "bug-fixes" and
"session-summary" are useless as tags because they apply to everything.

Rules:
- 0 to 3 topics per memory. Zero is a valid and common answer; do not invent a
  tag for a memory that is not about any particular thing.
- Prefer the narrowest true subject. If a memory is about the Banbury hub build,
  tag `banbury`, not `town-builds`.
- Use the same tag for the same thing every time, so tags accumulate rather than
  fragment.
- lowercase-hyphenated, 1-3 words."""


def extract_topics(cur, budget: _Budget, project: Optional[str] = None,
                   batch: int = 40, limit: int = 3, since_id: int = 0) -> List[Dict]:
    """
    Read memories and extract the subjects they are about.

    THIS REPLACED A CLUSTERING IMPLEMENTATION, and the reason is worth keeping,
    because the clustering approach looked obviously right and was not.

    Measured on a real 2,128-memory project: the similarity curve around a seed
    is essentially FLAT — 0.816 down to 0.754 across its 24 nearest neighbours,
    largest drop 0.020. There is no cliff to cut at, because every memory in one
    project is written in the same register about the same domain. Worse, the
    nearest neighbours of a memory about *Banbury* were not the other Banbury
    memories; they were other WTG engineering memories.

    So embeddings cluster by REGISTER, not by SUBJECT — and subject is exactly
    what a sub-classification needs. A fixed threshold gathered everything above
    it (one run produced a 40-member "topic" spanning three unrelated subjects);
    the cliff found nothing at all. Both failures have the same cause.

    Reading is what works: "banbury" is present in the text as a named thing.
    That is a judgment about meaning on a single memory, so it goes to a model —
    and once a topic EXISTS, back-filling it across the corpus is a structural
    match on a known term, which is cheap and exact (see `backfill_topics`).
    """
    import json

    projects = [project] if project else None
    if not projects:
        cur.execute(
            """SELECT project FROM memories
               WHERE project IS NOT NULL AND NOT archived
               GROUP BY project ORDER BY count(*) DESC""")
        projects = [r[0] for r in cur.fetchall()]

    found = []
    for proj in projects:
        if len(found) >= limit or budget.spent >= budget.total:
            break
        # Transcripts are included deliberately: a subject appears in
        # conversation long before anyone writes a curated memory about it, so
        # the raw exchanges are where a new topic shows up first.
        # Read FORWARD from the watermark, oldest first. The record set is
        # traversed once; an hour with nothing new costs nothing at all,
        # because the query returns no rows and no model is ever called.
        cur.execute(
            """SELECT m.id, m.subject, left(m.body, 400)
               FROM memories m
               WHERE m.project = %s AND NOT m.archived AND m.id > %s
                 AND m.origin IS DISTINCT FROM 'recycle'
               ORDER BY m.id ASC LIMIT %s""",
            (proj, since_id, batch))
        rows = cur.fetchall()
        if not rows:
            continue
        if not budget.take():
            break

        listing = "\n\n".join(
            f"id: {r[0]}\nsubject: {' '.join((r[1] or '').split())[:140]}\n"
            f"body: {' '.join((r[2] or '').split())[:300]}"
            for r in rows)
        extracted = _extract(listing, proj)
        if not extracted:
            continue

        counts: Dict[str, int] = {}
        for item in extracted:
            for raw in item.get("topics") or []:
                slug = _slugify(raw)
                if slug:
                    counts[slug] = counts.get(slug, 0) + 1

        for item in extracted:
            mid = item.get("id")
            for raw in item.get("topics") or []:
                slug = _slugify(raw)
                # A tag seen once in a batch is usually a one-off phrasing, not
                # a subject the work returns to. Requiring it twice keeps the
                # topic list from fragmenting into near-synonyms.
                if not slug or counts.get(slug, 0) < 2:
                    continue
                cur.execute(
                    """INSERT INTO topics (project, slug, label, source)
                       VALUES (%s,%s,%s,'discovered')
                       ON CONFLICT (project, slug) DO UPDATE SET last_seen = now()""",
                    (proj, slug, slug.replace("-", " ")))
                cur.execute(
                    """INSERT INTO memory_topics (memory_id, project, slug, confidence, assigned_by)
                       VALUES (%s,%s,%s,1.0,'read') ON CONFLICT DO NOTHING""",
                    (mid, proj, slug))
                found.append({"project": proj, "slug": slug, "memory_id": mid})
        highest = max((r[0] for r in rows), default=0)
        if highest:
            _advance(cur, highest)
    return found


def _extract(listing: str, project: str) -> List[Dict]:
    """One batched extraction call. Batched because per-memory calls would make
    this stage cost proportional to the corpus."""
    try:
        from anthropic import Anthropic
    except Exception:
        return []
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return []
    try:
        response = Anthropic().messages.create(
            model=os.environ.get("ENGRAM_DREAM_MODEL", "claude-opus-5"),
            max_tokens=8000,
            system=EXTRACT_SYSTEM,
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": TOPIC_SCHEMA}},
            messages=[{"role": "user",
                       "content": f"Project: {project}\n\n{listing}"}],
        )
        if response.stop_reason == "refusal":
            return []
        text = next((b.text for b in response.content if b.type == "text"), None)
        import json as _json
        return (_json.loads(text) or {}).get("memories", []) if text else []
    except Exception as exc:
        print(f"[dream] extraction failed: {exc}", file=sys.stderr)
        return []


# ---------------------------------------------------------------- stage 4 ---

def backfill_topics(cur, limit_per_topic: int = 400) -> int:
    """
    Spread each known topic across the whole corpus by literal term match.

    Once extraction has established that `banbury` is a subject, finding every
    other memory that mentions Banbury is not a judgment call — it is a
    structural fact about the text, and exact matching does it perfectly across
    thousands of rows for nothing. This is the division that matters: the model
    decides WHICH subjects exist, matching decides WHERE they appear.

    Embeddings are deliberately not used here. Measured on this corpus, a
    memory's nearest neighbours share its register, not its subject — so
    centroid similarity swept 400 unrelated memories into one topic, down to
    code-map entries that merely sounded like the same kind of writing.
    """
    cur.execute("SELECT project, slug, label FROM topics")
    topics = cur.fetchall()
    tagged = 0
    for proj, slug, label in topics:
        term = (label or slug).replace("-", " ").strip()
        if len(term) < 4:
            # Too short to match safely: 'ai' would hit half the corpus.
            continue
        cur.execute(
            """SELECT m.id FROM memories m
               WHERE m.project = %s AND NOT m.archived
                 AND m.origin IS DISTINCT FROM 'recycle'
                 AND (m.subject ILIKE %s OR m.body ILIKE %s)
                 AND NOT EXISTS (SELECT 1 FROM memory_topics mt
                                 WHERE mt.memory_id = m.id AND mt.project = %s AND mt.slug = %s)
               LIMIT %s""",
            (proj, f"%{term}%", f"%{term}%", proj, slug, limit_per_topic))
        for (mid,) in cur.fetchall():
            cur.execute(
                """INSERT INTO memory_topics (memory_id, project, slug, confidence, assigned_by)
                   VALUES (%s,%s,%s,1.0,'match') ON CONFLICT DO NOTHING""",
                (mid, proj, slug))
            tagged += 1
        # A centroid built from real members is now meaningful, and gives the
        # cheap path for anything that mentions the subject without naming it.
        cur.execute(
            """UPDATE topics t SET centroid = sub.c, member_count = sub.n, last_seen = now()
               FROM (SELECT avg(m.embedding) AS c, count(*) AS n FROM memories m
                     JOIN memory_topics mt ON mt.memory_id = m.id
                     WHERE mt.project = %s AND mt.slug = %s AND m.embedding IS NOT NULL) sub
               WHERE t.project = %s AND t.slug = %s AND sub.n > 0""",
            (proj, slug, proj, slug))
    return tagged


# ---------------------------------------------------------------- stage 5 ---

def summarise_topics(cur, budget: _Budget, limit: int = 3) -> List[Dict]:
    """
    Write a topic's summary back into the brain as a new memory.

    A summary that IS a memory participates in everything for free — it can be
    recalled, weighted, decayed, linked, project-scoped and superseded. The
    alternative (a column on a side table) makes it inert.

    Guards: only summarise real memories (never derived ones), record what it
    was derived from so it is auditable rather than an unattributable
    assertion, and cap the depth so the pass cannot summarise its own output
    into progressively vaguer copies.
    """
    from .memory import Memory
    # Re-summarise a topic only when it has actually grown since its last
    # summary. Without that test the pass rewrites the same summary every hour,
    # burning calls and filling the chain with identical links.
    cur.execute(
        """SELECT t.project, t.slug, t.label, t.gist, count(mt.memory_id) AS n,
                  (SELECT s.id FROM memories s
                    WHERE s.origin = 'recycle' AND s.project = t.project
                      AND s.subject = 'Topic summary: ' || t.slug
                      AND s.superseded_by IS NULL
                    ORDER BY s.created_at DESC LIMIT 1) AS prev_id,
                  (SELECT coalesce(array_length(s.derived_from, 1), 0) FROM memories s
                    WHERE s.origin = 'recycle' AND s.project = t.project
                      AND s.subject = 'Topic summary: ' || t.slug
                      AND s.superseded_by IS NULL
                    ORDER BY s.created_at DESC LIMIT 1) AS prev_covered
           FROM topics t JOIN memory_topics mt
             ON mt.project = t.project AND mt.slug = t.slug
           GROUP BY t.project, t.slug, t.label, t.gist
           HAVING count(mt.memory_id) >= %s
           ORDER BY n DESC LIMIT %s""",
        (MIN_CLUSTER, limit))
    written = []
    for proj, slug, label, gist, n, prev_id, prev_covered in cur.fetchall():
        if prev_id and n <= (prev_covered or 0):
            continue  # nothing new to say about this topic
        cur.execute(
            """SELECT m.id, m.subject FROM memories m
               JOIN memory_topics mt ON mt.memory_id = m.id
               WHERE mt.project = %s AND mt.slug = %s AND NOT m.archived
                 AND m.origin IS DISTINCT FROM 'recycle'
                 AND coalesce(m.derived_depth,0) < %s
               ORDER BY m.weight DESC NULLS LAST LIMIT 30""",
            (proj, slug, MAX_DERIVED_DEPTH))
        rows = cur.fetchall()
        if len(rows) < MIN_CLUSTER:
            continue
        member_ids = [r[0] for r in rows]
        body = (f"{gist or ''}\n\nCovers {len(member_ids)} memories in {proj}:\n"
                + "\n".join(f"- [{r[0]}] {r[1]}" for r in rows))
        try:
            mid = Memory.save(
                subject=f"Topic summary: {slug}",
                body=body, person=None, project=proj, origin="recycle",
                perspectives=False, redact=True, tier="insight",
                source_system="dream",
            )
        except Exception as exc:
            print(f"[dream] could not write summary for {proj}/{slug}: {exc}", file=sys.stderr)
            continue
        cur.execute(
            "UPDATE memories SET derived_from = %s, derived_depth = 1 WHERE id = %s",
            (member_ids, mid))
        # Chain to the previous summary rather than replacing it. The old one
        # stays readable and superseded, so a topic accumulates a history of how
        # its understanding changed — and consecutive links can be diffed to see
        # what a period of work actually added. Recall prefers the head; the
        # tail is the record.
        if prev_id:
            cur.execute("UPDATE memories SET superseded_by = %s WHERE id = %s", (mid, prev_id))
            cur.execute(
                """INSERT INTO memory_links (from_id, to_id, link_type, strength)
                   SELECT %s,%s,'supersedes',1.0
                   WHERE NOT EXISTS (SELECT 1 FROM memory_links
                                     WHERE from_id=%s AND to_id=%s AND link_type='supersedes')""",
                (mid, prev_id, mid, prev_id))
        cur.execute(
            """INSERT INTO memory_topics (memory_id, project, slug, confidence, assigned_by)
               VALUES (%s,%s,%s,1.0,'dream') ON CONFLICT DO NOTHING""",
            (mid, proj, slug))
        written.append({"project": proj, "slug": slug, "memory_id": mid,
                        "covers": len(member_ids), "supersedes": prev_id})
    return written


# ---------------------------------------------------------------- stage 6 ---

def summarise_periods(cur, budget: _Budget, hours_back: int = 48,
                      min_memories: int = 4, max_memories: int = 60,
                      limit: int = 2) -> List[Dict]:
    """
    Summarise what happened in a PERIOD, across every project.

    The third axis, and the only one that needs no discovery at all: project
    says which body of work, topic says which subject, period says WHEN — and
    time hands you the grouping for free. No clustering, no extraction, no
    threshold to calibrate; only the writing costs anything.

    It earns its place because it cuts ACROSS the other two. A working session
    is rarely one project and one subject, and "that afternoon we were doing the
    AMI and it drifted into WTG" is a real and useful handle that neither a
    project nor a topic can express. It is also how episodic recall actually
    behaves: people locate a memory by the occasion first and the subject
    second.

    The period key doubles as the handle — `by_name(cur, '2026-08-08T15')`
    resolves the hour directly, no vector involved.

    KNOWN LIMIT, and it is a data problem rather than a code one: this groups by
    `created_at`, which is when a memory was RECORDED, not when the thing
    happened. Bulk-ingested transcripts all carry their import time, so a
    backfill of 557 exchanges lands in a single "hour" and summarising it
    produces mush. `max_memories` skips those rather than pretending — an hour
    with sixty-odd memories in it was a working session; an hour with hundreds
    was an import. The real fix is an event-time column on ingested rows, which
    belongs with the ingestion layer, not here.
    """
    from .memory import Memory
    cur.execute(
        """SELECT to_char(date_trunc('hour', created_at), 'YYYY-MM-DD"T"HH24') AS period,
                  array_agg(id ORDER BY id), count(*)
           FROM memories
           WHERE NOT archived AND origin IS DISTINCT FROM 'recycle'
             AND created_at > now() - (%s || ' hours')::interval
           GROUP BY 1 HAVING count(*) BETWEEN %s AND %s
           ORDER BY 1 DESC LIMIT %s""",
        (hours_back, min_memories, max_memories, limit))
    written = []
    for period, member_ids, n in cur.fetchall():
        cur.execute(
            "SELECT 1 FROM memories WHERE origin='recycle' AND subject = %s",
            (f"Session summary: {period}",))
        if cur.fetchone():
            continue
        cur.execute(
            """SELECT id, coalesce(project,'(none)'), subject FROM memories
               WHERE id = ANY(%s) ORDER BY id LIMIT 40""", (member_ids,))
        rows = cur.fetchall()
        if not budget.take():
            break
        subjects = [f"[{r[1]}] {r[2] or ''}" for r in rows]
        named = boundary._name_cluster(subjects, query=f"work done in the hour {period}")
        projects_seen = sorted({r[1] for r in rows})
        body = (f"{named['gist']}\n\nProjects touched: {', '.join(projects_seen)}\n\n"
                + "\n".join(f"- [{r[0]}] {r[1]}: {r[2]}" for r in rows))
        try:
            mid = Memory.save(subject=f"Session summary: {period}", body=body,
                              person=None, project=None, origin="recycle",
                              perspectives=False, tier="insight", source_system="dream")
        except Exception as exc:
            print(f"[dream] could not write period summary {period}: {exc}", file=sys.stderr)
            continue
        cur.execute("UPDATE memories SET derived_from=%s, derived_depth=1 WHERE id=%s",
                    (list(member_ids), mid))
        # Register the hour as a doorway so it is reachable by its own key,
        # exactly like a query-resolved cluster.
        try:
            boundary.record(cur, [{"id": i} for i in member_ids],
                            query=f"period {period}", cut_gap=1.0, name=False)
            cur.execute("UPDATE collapse_keys SET name=%s, gist=%s WHERE key=%s",
                        (period, named["gist"], boundary.derive_key(member_ids)))
        except Exception:
            pass
        written.append({"period": period, "memory_id": mid, "covers": n,
                        "projects": projects_seen, "label": named["name"]})
    return written


# ------------------------------------------------------------------- run ----

def dream(project: Optional[str] = None, llm_budget: int = DEFAULT_LLM_BUDGET,
          tag_limit: int = 500, consolidate_too: bool = True) -> Dict:
    """
    One dreaming pass. Safe to run on a timer; every stage is bounded.

    Returns what it did, so a scheduled run leaves a legible trace rather than
    silently reshaping the corpus.
    """
    budget = _Budget(llm_budget)
    conn = get_conn()
    cur = conn.cursor()
    report: Dict = {"llm_budget": llm_budget}
    try:
        report["doorways_aged"] = age_doorways(cur)

        # Nothing new since the last pass means there is nothing to read, and a
        # pass that reads nothing must not spend a model call. Most hours on a
        # quiet brain should cost exactly zero.
        since_id = _watermark(cur)
        # Exclude the pass's OWN output. Summaries are memories, so counting
        # them here means every run creates the evidence that another run is
        # needed — the job would never once conclude that nothing happened,
        # which is precisely the case it exists to make cheap.
        cur.execute("SELECT max(id) FROM memories "
                    "WHERE NOT archived AND origin IS DISTINCT FROM 'recycle'")
        newest = cur.fetchone()[0] or 0
        report["watermark"] = since_id
        report["newest_memory"] = newest
        if newest <= since_id:
            report["skipped"] = "no new memories since last pass"
            report["promoted"] = promote_doorways(cur, budget)
            report["backfilled"] = backfill_topics(cur, limit_per_topic=tag_limit)
            conn.commit()
            report["llm_calls_used"] = budget.spent
            cur.close(); conn.close()
            if consolidate_too:
                from .aging import consolidate
                report["consolidate"] = consolidate()
            return report

        report["promoted"] = promote_doorways(cur, budget)
        report["extracted"] = extract_topics(cur, budget, project=project, since_id=since_id)
        report["backfilled"] = backfill_topics(cur, limit_per_topic=tag_limit)
        report["summaries"] = summarise_topics(cur, budget)
        report["periods"] = summarise_periods(cur, budget)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        report["error"] = str(exc)
        print(f"[dream] pass failed and was rolled back: {exc}", file=sys.stderr)
    finally:
        cur.close()
        conn.close()

    report["llm_calls_used"] = budget.spent
    if consolidate_too:
        from .aging import consolidate
        report["consolidate"] = consolidate()
    return report
