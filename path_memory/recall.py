import random
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

# How much use-history may lift a memory, as a fraction on top of its relevance.
#
# The original formula added weight (0.7) and cosine (0.1) as peers, so
# popularity outranked relevance by design: warming eight espresso memories with
# one query made the NEXT query, about VAT deadlines, return all five espresso
# memories ahead of the exact matches. Measured on that corpus: VAT cosine 0.75
# vs espresso 0.42 — a 1.8x relevance difference — against a 10x swing from
# use-history alone (multiplier 0.1 unused vs 1.0 used). Relevance never stood a
# chance.
#
# Use-history is now a BOUNDED bonus on top of relevance: a fully-warmed memory
# is worth at most ~1.5x its cosine. Anything more relevant than that still
# wins, so popularity can no longer answer a question it is not about — while
# within a band of comparable relevance the proven-useful memory still leads,
# which is the entire point of a use-built graph.
USE_BONUS = 0.5

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


def _inject_serendipity(scored, limit, creativity):
    """Creativity dial: blend a creativity-scaled fraction of *near-miss* memories
    into the result set. Not the nearest matches (those are the obvious answer)
    and not random noise (that's just irrelevant) — the *adjacent possible*:
    related-but-not-asked-for memories that nudge the reader toward a connection
    they wouldn't have made. Like a painter's happy accident, the spark lives at
    medium distance, not infinite distance.

    `scored` is sorted by composite score, descending. We always keep the top
    precise hit; higher creativity trades more of the tail for near-misses and
    lets the sampling window roam further out. Picks are flagged serendipity=True
    so the caller (and the LLM) can treat them as prompts, not facts — and so
    they never strengthen the use-built graph.
    """
    creativity = max(0.0, min(1.0, creativity))
    n_creative = min(round(creativity * limit), max(limit - 1, 0))
    n_precise = limit - n_creative

    precise = scored[:n_precise]
    for r in precise:
        r["serendipity"] = False
    if n_creative <= 0:
        return precise

    # Near-miss band: the non-precise candidates ranked by raw semantic adjacency
    # (cosine). Sample from the front of that band so picks stay *near*; the
    # window widens with creativity, so higher settings wander further afield.
    leftovers = sorted(scored[n_precise:], key=lambda r: r["cosine"], reverse=True)
    window_size = max(n_creative * 3, int(4 + creativity * len(leftovers)))
    window = leftovers[:window_size]
    picks = random.sample(window, min(n_creative, len(window))) if window else []
    for r in picks:
        r["serendipity"] = True
    return precise + picks


def _collapse_field(scored, limit, min_gap=0.18, min_keep=1, min_abs_frac=0.05):
    """Collapse the 'treacle' — the blurry continuum of relevance — into a clean
    keep/drop boundary, and return only the keep side ('air').

    Raw cosine similarity alone is the blur: near-but-wrong memories (false
    friends) look just like genuinely-relevant ones. The composite score is the
    *resolved* field — it mixes meaning (cosine) with everything the brain knows
    from use (edge-built weight, recency, supersession). Sorted by that, a real
    answer-set forms a tight cluster up top, then the relevance falls off a
    cliff into noise.

    We find that cliff: the largest drop between consecutive candidates. It has
    to clear two tests, and it needs both.

      RELATIVE — the drop must be at least `min_gap` of the pool's score range,
      so the test is scale-free.
      ABSOLUTE — the drop must also be at least `min_abs_frac` of the top score,
      so a field with no real structure cannot be stretched into one.

    The absolute test is not decoration. Normalisation divides by the span, so
    six scores covering a range of 0.0001 normalise to gaps of 0.2 apiece and
    the first one clears a 0.18 threshold: a perfectly uniform field was cut
    after two results and reported as a clean cliff. Every field has a largest
    gap; that is not the same as having a wall.

    Both thresholds are fitted to measurement on a real brain, not derived. On
    an eight-memory field the genuine on-topic-to-noise cliff was 0.2316 raw —
    31% of the top score — while the largest drop WITHIN either cluster was
    0.0357, or 4.8%. A 5% floor sits in that gap with room on both sides. Like
    every other threshold in this engine, honest heuristics from one corpus.

    Normalisation spans the WHOLE candidate pool rather than the top `limit`+1.
    The window was an arbitrary truncation, so its span — and therefore every
    normalised gap measured against it — depended on where the caller happened
    to cut. The cliff is still only searched for within the first `limit`
    positions, since nothing beyond that can be returned anyway.
    """
    window = list(scored)
    if len(window) <= min_keep:
        # Must return the same (results, gap) shape as every other exit. This
        # path is the empty or single-result brain — i.e. a new user's very
        # first query — and returning a bare list here made collapse raise
        # ValueError on it. There is no field to resolve with one candidate, so
        # the gap is None: nothing was cut, nothing is worth naming.
        return scored[:limit], None

    vals = [r["score"] for r in window]
    hi, lo = vals[0], vals[-1]
    span = (hi - lo) or 1.0
    norm = [(v - lo) / span for v in vals]
    floor = abs(hi) * min_abs_frac

    best_i, best_gap = None, 0.0
    for i in range(min_keep, min(limit, len(window) - 1) + 1):
        gap = norm[i - 1] - norm[i]
        # The raw drop is what says this is a wall rather than merely the
        # largest step in a smooth slope.
        if gap > best_gap and (vals[i - 1] - vals[i]) >= floor:
            best_gap, best_i = gap, i

    clean = best_i is not None and best_gap >= min_gap
    # Never return more than asked for: the search window is the whole pool now,
    # so best_i could otherwise sit beyond `limit`.
    cut = min(best_i, limit) if clean else min(limit, len(scored))
    # Return the gap alongside the cut: it is the measure of how cleanly the
    # field separated, and the caller needs it to decide whether this
    # resolution is worth keeping as a named boundary. A shallow gap means it
    # never really split into wall and air.
    return scored[:cut], (best_gap if clean else None)


def recall(
    query: str,
    person: Optional[str] = None,
    noun_type: Optional[str] = None,
    node_type: Optional[str] = None,
    origin: Optional[str] = None,
    project: Optional[str] = None,
    tiers=None,
    limit: int = 5,
    increment_weight: bool = True,
    creativity: float = 0.0,
    collapse: bool = False,
) -> List[Dict[str, Any]]:
    """
    Semantic recall with a composite ranking:
        score = (0.7 * weight + 0.2 * recency + 0.1 * cosine_similarity) * temporal_factor

    Returns top-limit results, sorted by composite score.
    Set increment_weight=False for read-only queries (e.g. admin inspection).

    creativity (0..1): structured serendipity. 0 = precise best matches only. As
    it rises, a growing share of the result *tail* is swapped for near-miss
    memories — semantically adjacent but not the obvious answer — to spark
    connections the literal query would never surface. Those picks are flagged
    serendipity=True and deliberately never strengthen the use-built graph.

    tiers: restrict to these memory tiers (a string or an iterable of them,
    e.g. ('curated','insight','decision','project') to search knowledge but
    not the raw transcript archive). None searches every tier. This came back
    from the mindspace lineage, where an exact-match single-tier default
    silently hid every insight/decision memory — including the dreaming pass's
    own summaries, i.e. the compressed form of the corpus was the one thing
    recall could never see.

    collapse: when True, don't blindly return a fixed top-`limit`. Resolve the
    relevance field into keep ('air') vs drop ('wall') by finding the natural
    cliff in the composite scores, and return only the air — so a query with
    three real answers gets three, not five padded with noise. `limit` becomes
    an upper bound, not a quota. Mutually exclusive with creativity (collapse
    wins); both at once makes no sense — one trims treacle, the other adds it.
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
    if tiers:
        _t = [tiers] if isinstance(tiers, str) else list(tiers)
        filters.append("tier = ANY(%s)");     params.append(_t)
        p_filters.append("m.tier = ANY(%s)"); p_params.append(_t)
    # Resolve the project the same way Memory.save does. Without this a memory
    # written with project="My Project" (stored as "my-project") is invisible to
    # a recall using the identical string the caller just wrote — and any
    # registered alias misses too. Reproduced: save then recall with the same
    # argument returned zero rows.
    if project:
        _resolved_project = project
        try:
            _rconn = get_conn()
            _rcur = _rconn.cursor()
            from . import projects as _projects
            _resolved_project = _projects.resolve(_rcur, project) or project
            _rcur.close(); _rconn.close()
        except Exception:
            pass
        _filter("project", "m.project", _resolved_project)

    where   = " AND ".join(filters)
    p_where = " AND ".join(p_filters)
    # Fetch more than limit so composite re-ranking can reorder; widen the pool
    # when creativity is on (near-miss candidates) or collapse is on (so the
    # relevance cliff is actually visible in the pool, not cut off at `limit`).
    fetch_n = limit * (12 if ((creativity and creativity > 0) or collapse) else 4)
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
                   temporal_anchor_start, temporal_anchor_end, superseded_by,
                   derived_from
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
                       m.temporal_anchor_start, m.temporal_anchor_end, m.superseded_by,
                       m.derived_from
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

    # Normalise weight against the strongest candidate in THIS pool rather than
    # using it raw. Raw weight dominates on a young brain: eight memories warmed
    # by one query then outranked an exact match on the next, returning 5/5
    # wrong results and staying wrong for a week. Dividing by the pool maximum
    # makes a uniformly-cold pool contribute nothing (cosine decides, which is
    # correct when there is no use-history to consult) while preserving the
    # relative ordering that makes a warm brain good.
    _max_weight = max((float(r[10]) for r in rows), default=0.0) or 1.0

    results = []
    for row in rows:
        cosine  = float(row[9])
        weight  = float(row[10])
        recency = _recency_score(row[14])
        status  = temporal_status(row[16], row[17])
        factor  = TEMPORAL_FACTOR.get(status, 1.0)
        if row[18] is not None:                  # superseded -> ranks below its replacement
            factor *= SUPERSEDED_FACTOR
        # Relevance GATES use-history rather than competing with it.
        #
        # The additive form made weight (0.7) outrank cosine (0.1), so a
        # popular memory beat a relevant one outright: warming eight espresso
        # memories with one query made the next query, about VAT deadlines,
        # return all five espresso memories ahead of the exact match. Popularity
        # is a global signal; the query is asking about relevance.
        #
        # Multiplying keeps the intended behaviour — among memories that DO
        # match, a proven-useful one still outranks a fresher-but-unused one,
        # which is the whole point of a use-built graph — while making it
        # impossible for use-history to rescue something the query is not about.
        score   = cosine * (1.0 + USE_BONUS * (W_WEIGHT * (weight / _max_weight)
                                               + W_RECENCY * recency)) * factor

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
            "derived_from":   row[19],
        })

    # Re-rank by composite score
    results.sort(key=lambda r: r["score"], reverse=True)

    # PICK A LEVEL. The dreaming pass writes a topic's gist back as a new
    # memory covering N others (derived_from), so a summary and its own members
    # can rank for the same query — the same content twice, once condensed and
    # once in full. Whichever ranked higher is the level this query wants: keep
    # it, drop the other level of the SAME material. Without this, compression
    # makes recall worse, which would make the dreaming pass not worth running.
    # Applied before trimming so a suppressed member's slot goes to new
    # material rather than being silently lost.
    covered: set = set()
    kept_ids: set = set()
    levelled = []
    for r in results:
        if r["id"] in covered:
            continue
        members = r.get("derived_from")
        if members:
            # Both directions matter. A summary ranked above its members
            # suppresses them (covered) — and a summary ranked BELOW one of
            # its members is itself the losing level and gets dropped, or the
            # detail and its own condensation would both be returned.
            if any(m in kept_ids for m in members):
                continue
            covered.update(members)
        kept_ids.add(r["id"])
        levelled.append(r)
    results = levelled
    cut_gap = None
    if collapse:
        # Resolve the treacle: cut at the natural relevance cliff, keep the air.
        results, cut_gap = _collapse_field(results, limit)
        for r in results:
            r["serendipity"] = False
    elif creativity and creativity > 0 and len(results) > limit:
        results = _inject_serendipity(results, limit, creativity)
    else:
        results = results[:limit]
        for r in results:
            r["serendipity"] = False

    # Being recalled together IS the traversal -- record a footprint between each
    # consecutive pair of GENUINE hits. Creative near-misses are sparks, not
    # retrievals: they neither form edges nor get strengthened, so creativity can
    # never distort the use-built graph.
    real_ids = [r["id"] for r in results if not r.get("serendipity")]
    for a, b in zip(real_ids, real_ids[1:]):
        record_traversal(conn, a, b)

    if increment_weight and real_ids:
        cur.execute(
            """UPDATE memories SET
                 access_count = access_count + 1,
                 weight = weight + (1.0 / (access_count + 2)),
                 last_accessed = now()
               WHERE id = ANY(%s)""",
            (real_ids,),
        )
        conn.commit()

    # Keep the boundary this collapse resolved. Without this the expensive
    # resolution is discarded and the next identical question pays for it
    # again, and nothing in the brain records that these memories go together.
    if collapse and cut_gap is not None:
        from . import boundary as _boundary
        # name=False: recording the boundary is two cheap writes, but NAMING it
        # is a synchronous model call. On the read path, unbudgeted, once per
        # novel result set — so a user exploring a new brain with collapse on
        # paid a model call per query, in latency and in money, for a label
        # nothing had asked for. The doorway is still recorded; the dreaming
        # pass names it later, offline, inside a budget, and only if it proves
        # durable enough to be worth a name.
        key = _boundary.record(cur, results, query=query, cut_gap=cut_gap, name=False)
        if key:
            conn.commit()
            for r in results:
                r["collapse_key"] = key

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
