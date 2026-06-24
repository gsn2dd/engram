from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from .db import get_conn
from .embed import embed_one
from .temporal import temporal_status
from .links import record_traversal, spreading_activate

# Claudine's ranking formula: score = 0.7*weight + 0.2*recency + 0.1*coverage_match
W_WEIGHT   = 0.7
W_RECENCY  = 0.2
W_COVERAGE = 0.1

RECENCY_HALF_LIFE_DAYS = 30   # weight halves every 30 days of non-use

# Calendar time is a soft ranking signal, not just a display label. A
# "current" anchored memory (the event is happening now) gets a small
# boost; "past" gets a small penalty, since its body text may still read
# present/future tense even though the date has gone by. Atemporal and
# "upcoming" memories are unaffected -- this nudges close calls, it doesn't
# override a real gap in the composite score.
TEMPORAL_FACTOR = {
    None:       1.0,
    "upcoming": 1.0,
    "current":  1.05,
    "past":     0.92,
}

# A superseded memory isn't deleted — the distillation that replaced it is just
# a better answer, so it should normally lose a close call to its replacement.
# The row stays fully recallable (by id, or if it's the only match) in case the
# replacement dropped a detail that's still needed.
SUPERSEDED_FACTOR = 0.4


def _recency_score(last_accessed) -> float:
    """Normalise last_accessed to [0,1]. Never-accessed = 0."""
    if last_accessed is None:
        return 0.0
    if last_accessed.tzinfo is None:
        last_accessed = last_accessed.replace(tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc) - last_accessed).days
    return max(0.0, 1.0 - days / (RECENCY_HALF_LIFE_DAYS * 2))


def recall(
    query: str,
    person: Optional[str] = None,
    noun_type: Optional[str] = None,
    node_type: Optional[str] = None,
    origin: Optional[str] = None,
    project: Optional[str] = None,
    limit: int = 5,
    increment_weight: bool = True,
) -> List[Dict[str, Any]]:
    """
    Semantic recall with Claudine's composite ranking:
        score = (0.7 * weight + 0.2 * recency + 0.1 * cosine_similarity) * temporal_factor

    Returns top-limit results, sorted by composite score.
    Set increment_weight=False for read-only queries (e.g. admin inspection).
    """
    vec     = embed_one(query)
    vec_str = "[" + ",".join(str(x) for x in vec) + "]"

    # Build the filter clause twice: once for the literal-embedding query (bare
    # column names) and once for the perspective query (m.-prefixed, since it
    # joins memory_perspectives mp to memories m).
    filters   = ["embedding IS NOT NULL", "archived = false",
                 "(expires_at IS NULL OR expires_at > now())"]
    p_filters = ["mp.embedding IS NOT NULL", "m.embedding IS NOT NULL",
                 "m.archived = false", "(m.expires_at IS NULL OR m.expires_at > now())"]
    params: list = []
    p_params: list = []

    def _filter(col, pcol, val):
        filters.append(f"{col} = %s");   params.append(val)
        p_filters.append(f"{pcol} = %s"); p_params.append(val)

    if person:    _filter("person",    "m.person",    person)
    if noun_type: _filter("noun_type", "m.noun_type", noun_type)
    if node_type: _filter("node_type", "m.node_type", node_type)
    if origin:    _filter("origin",    "m.origin",    origin)
    if project:   _filter("project",   "m.project",   project)

    where   = " AND ".join(filters)
    p_where = " AND ".join(p_filters)
    # Fetch more than limit so composite re-ranking can reorder
    fetch_n = limit * 4
    params.append(fetch_n)
    p_params.append(fetch_n)

    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        f"""SELECT id, person, subject, body, noun_type, node_type, node_key,
                   source_links, origin,
                   1 - (embedding <=> '{vec_str}'::vector) AS cosine,
                   weight, access_count, success_count, fail_count,
                   last_accessed, created_at,
                   temporal_anchor_start, temporal_anchor_end, superseded_by
            FROM memories
            WHERE {where}
            ORDER BY embedding <=> '{vec_str}'::vector
            LIMIT %s""",
        params,
    )
    by_id = {r[0]: list(r) for r in cur.fetchall()}

    # Fan-out perspective handles: a memory can match via any of its lenses
    # (thematic / questions / vantages) even when its literal embedding doesn't.
    # Merge perspective hits in, keeping the best cosine per memory. Fully
    # guarded with a rollback so it can never poison core recall.
    try:
        cur.execute(
            f"""SELECT m.id, m.person, m.subject, m.body, m.noun_type, m.node_type, m.node_key,
                       m.source_links, m.origin,
                       1 - (mp.embedding <=> '{vec_str}'::vector) AS cosine,
                       m.weight, m.access_count, m.success_count, m.fail_count,
                       m.last_accessed, m.created_at,
                       m.temporal_anchor_start, m.temporal_anchor_end, m.superseded_by
                FROM memory_perspectives mp JOIN memories m ON m.id = mp.memory_id
                WHERE {p_where}
                ORDER BY mp.embedding <=> '{vec_str}'::vector
                LIMIT %s""",
            p_params,
        )
        for pr in cur.fetchall():
            mid = pr[0]
            if mid in by_id:
                if pr[9] > by_id[mid][9]:        # boost to the better lens cosine
                    by_id[mid][9] = pr[9]
            else:
                by_id[mid] = list(pr)
    except Exception:
        conn.rollback()

    rows = list(by_id.values())

    results = []
    for row in rows:
        cosine  = float(row[9])
        weight  = float(row[10])
        recency = _recency_score(row[14])
        status  = temporal_status(row[16], row[17])
        factor  = TEMPORAL_FACTOR.get(status, 1.0)
        if row[18] is not None:                  # superseded -> ranks below its replacement
            factor *= SUPERSEDED_FACTOR
        score   = (W_WEIGHT * weight + W_RECENCY * recency + W_COVERAGE * cosine) * factor

        results.append({
            "id":            row[0],
            "person":        row[1],
            "subject":       row[2],
            "body":          row[3],
            "noun_type":     row[4],
            "node_type":     row[5],
            "node_key":      row[6],
            "source_links":  row[7],
            "origin":        row[8],
            "score":         round(score, 4),
            "cosine":        round(cosine, 4),
            "weight":        weight,
            "access_count":  row[11],
            "success_count": row[12],
            "fail_count":    row[13],
            "last_accessed": row[14],
            "created_at":    row[15],
            "temporal_anchor_start": row[16],
            "temporal_anchor_end":   row[17],
            # Re-derived against today's date on every recall, never frozen
            # at write time — see path_memory.temporal.
            "temporal_status": status,
            "superseded_by":  row[18],
        })

    # Re-rank by composite score
    results.sort(key=lambda r: r["score"], reverse=True)
    results = results[:limit]

    # Being recalled together IS the traversal -- record a footprint between
    # each consecutive pair of hits. This is how the path graph grows from
    # real usage, not just from an explicit chain-building step.
    hit_ids = [r["id"] for r in results]
    for a, b in zip(hit_ids, hit_ids[1:]):
        record_traversal(conn, a, b)

    if increment_weight and results:
        ids = [r["id"] for r in results]
        cur.execute(
            """UPDATE memories SET
                 access_count = access_count + 1,
                 weight = weight + (1.0 / (access_count + 2)),
                 last_accessed = now()
               WHERE id = ANY(%s)""",
            (ids,),
        )
        conn.commit()

    cur.close()
    conn.close()
    return results


def recall_with_activation(query: str, hops: int = 2, decay: float = 0.5, **kwargs) -> Dict[str, Any]:
    """recall() plus spreading activation from the top hit: surfaces memories
    linked-by-use to what just matched, even if they're nowhere near it
    semantically -- the thing cosine similarity alone can never find.
    Returns {"results": [...], "activated": [...]}."""
    results = recall(query, **kwargs)
    activated = []
    if results:
        conn = get_conn()
        seed_ids = [results[0]["id"]]
        hit_ids = {r["id"] for r in results}
        activated = [
            a for a in spreading_activate(conn, seed_ids, hops=hops, decay=decay)
            if a["id"] not in hit_ids
        ]
        conn.close()
    return {"results": results, "activated": activated}
