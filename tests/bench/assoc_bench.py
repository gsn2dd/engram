#!/usr/bin/env python3
"""
The one measurement engram actually rests on: does the USE-BUILT GRAPH surface
answers that similarity cannot?

Everything else engram does (collapse, supersession, temporal re-tensing) a
determined vector store could bolt on. The single structural claim — the reason
the whole path-memory machinery exists — is this: memories recalled together lay
down edges, and spreading activation later surfaces what is linked BY USE even
when it is nowhere near in embedding space. We have DEMONSTRATED that (see
demo_theatre.py --warm). Demonstrating is not measuring. This measures it, and
reports the answer whichever way it falls — the same discipline that retired
success_bonus when the data said it hurt (docs/WHAT_WE_MEASURED.md).

WHY THIS IS NOT CIRCULAR — the trap every association benchmark falls into.

An edge is laid between two memories because some query returned them together.
If we then tested against pairs we ourselves declared related, warming would be
marking its own homework. Two independences keep that from happening:

  1. GROUND TRUTH is the corpus's own causal wikilinks. The theatre corpus was
     generated with [[N]] cross-references meaning "N is the CAUSE of this" —
     the roof leak that caused the closure that cut the bar takings. Those links
     were written by the corpus generator, months before this bench existed, and
     have nothing to do with which queries we warm on. (The [[N]] are 1-based
     indices into the corpus array; validated by reading the pairs — every one
     resolves to a genuine cause.)

  2. THE WARMING QUERIES are warm_graph.SESSIONS — eight jobs someone at this
     theatre would do, hand-written as sequences of real questions, authored
     WITHOUT reference to the wikilinks. A session never says "recall the cause
     and its consequence together"; it says "I am preparing the funding bid" and
     asks what that job asks. If warming then links a causal pair, it is because
     doing the job really did pull both up — independent corroboration, not a
     plant.

So a win here means: work that never mentioned a causal link nonetheless built
the edge that recall needed, and similarity alone would have missed the answer.

WHAT WE REFUSE TO DO. Report only the pairs that improved. A causal pair can be
helped by the graph ONLY if some session happened to co-recall its two ends;
most pairs are never touched, and for those the graph does nothing. Hiding them
would turn a coverage number into a hit rate. So every FAR pair is counted,
covered or not, and coverage is printed as its own line. The headline is the
honest net, not the flattering subset.

WHAT A WIN DOES AND DOES NOT ESTABLISH. It establishes that on THIS corpus, with
THIS simulated work, the use-built graph recovers answers cosine misses. It does
not establish a universal ratio — that depends on how much a brain's real work
co-recalls its causally-linked memories, which is a property of the user's life,
not of engram. The claim engram can honestly make is existence and mechanism:
"linked-by-use retrieval finds things similarity cannot, and here is it doing
so, measured." This bench is the evidence for that sentence and nothing larger.

Run:
    python3 tests/bench/assoc_bench.py            # seed if needed, warm, measure
    python3 tests/bench/assoc_bench.py --rounds 5 # warm harder before measuring
"""
import argparse
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from path_memory.db import get_conn
from path_memory.links import compact_links, record_traversal, spreading_activate
from path_memory.recall import recall
from warm_graph import SESSIONS

CORPUS = os.path.join(HERE, "theatre_corpus.json")
PROJECT = "harrowgate"
WIKILINK = re.compile(r"\[\[(\d+)\]\]")


def ensure_seeded(conn):
    """Seed the theatre brain if it is not already present. Idempotent — a brain
    that is already seeded is left exactly as it is (the embeddings cost money to
    regenerate and would not change)."""
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM memories WHERE project = %s", (PROJECT,))
    have = cur.fetchone()[0]
    cur.close()
    with open(CORPUS) as fh:
        want = len(json.load(fh)["memories"])
    if have >= want:
        return have
    print(f"Seeding the theatre brain ({want} memories, embeds each — ~1 min)...")
    import demo_theatre
    demo_theatre.seed()
    return want


def index_to_id(conn):
    """Map each corpus ARRAY POSITION to the live memory id, by subject text.

    The wikilinks are array indices; the live ids are whatever the seed assigned.
    Subject text is the join key that survives reseeding. A duplicate subject
    would make the mapping ambiguous, so those positions are dropped rather than
    guessed — a wrong id is worse than a missing pair, because it would put a
    false 'answer' into the one non-circular thing we have.
    """
    with open(CORPUS) as fh:
        mems = json.load(fh)["memories"]
    cur = conn.cursor()
    cur.execute(
        "SELECT id, subject FROM memories WHERE project = %s AND archived = false",
        (PROJECT,),
    )
    by_subject = {}
    dupes = set()
    for mid, subject in cur.fetchall():
        if subject in by_subject:
            dupes.add(subject)
        by_subject[subject] = mid
    cur.close()
    idx_id, ambiguous = {}, 0
    for i, m in enumerate(mems):
        s = m["subject"]
        if s in dupes:
            ambiguous += 1
            continue
        if s in by_subject:
            idx_id[i] = by_subject[s]
    return mems, idx_id, ambiguous


def ground_truth_pairs(conn):
    """The corpus's own causal links, remapped to live ids and priced by cosine.

    Returns [{consequence_id, cause_id, query, cosine}], where `query` is the
    consequence's subject — the natural thing someone would ask when facing the
    effect — and the CAUSE is the answer we want found. cosine is between the two
    memories, so the caller can split the pairs similarity already handles (NEAR)
    from the ones only association can reach (FAR).
    """
    mems, idx_id, ambiguous = index_to_id(conn)
    cur = conn.cursor()
    pairs = []
    for i, m in enumerate(mems):
        if i not in idx_id:
            continue
        for t in WIKILINK.findall(m.get("body", "")):
            j = int(t) - 1  # [[N]] is 1-based into the corpus array
            if j == i or j not in idx_id:
                continue
            cons_id, cause_id = idx_id[i], idx_id[j]
            cur.execute(
                "SELECT 1 - (a.embedding <=> b.embedding) FROM memories a, memories b "
                "WHERE a.id=%s AND b.id=%s", (cons_id, cause_id))
            row = cur.fetchone()
            if not row or row[0] is None:
                continue
            pairs.append({"consequence_id": cons_id, "cause_id": cause_id,
                          "query": m["subject"], "cosine": float(row[0])})
    cur.close()
    # De-dup identical (consequence,cause) pairs that a body may reference twice.
    seen, uniq = set(), []
    for p in pairs:
        k = (p["consequence_id"], p["cause_id"])
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq, ambiguous


def reset_scoped_edges(conn):
    """Delete ONLY edges internal to the theatre brain, so the run starts from a
    known-cold graph and is reproducible.

    Emphatically scoped: mindspace's real association graph shares this table
    (its edges connect real memory ids, not theatre ones), and wiping it to
    measure a demo would be indefensible. Both endpoints must be theatre
    memories for a row to be touched.
    """
    cur = conn.cursor()
    scope = ("(from_id IN (SELECT id FROM memories WHERE project=%s) AND "
             " to_id  IN (SELECT id FROM memories WHERE project=%s))")
    cur.execute(f"DELETE FROM path_edge_summary WHERE {scope}", (PROJECT, PROJECT))
    e = cur.rowcount
    cur.execute(f"DELETE FROM memory_links WHERE {scope}", (PROJECT, PROJECT))
    conn.commit()
    cur.close()
    return e


def warm_scoped(rounds, limit=5):
    """Run the work sessions, but scoped to the theatre brain so every edge laid
    has both ends inside the corpus. Same mechanism as warm_graph.warm(); the
    scope is what keeps the demo's warming out of the real graph.

    `limit` is the recall depth DURING use, and it turns out to matter more than
    rounds: an edge is only laid between memories that co-appear in one query's
    top-`limit`, so a shallow window links only near-neighbours (which cosine
    already relates) and a causally-linked-but-dissimilar pair never co-appears.
    Widening it is legitimate — it is still just "how much a real recall shows" —
    and it is the honest lever for whether the graph can reach FAR pairs at all.
    """
    queries = 0
    for _ in range(rounds):
        for _task, qs in SESSIONS:
            for q in qs:
                recall(q, project=PROJECT, limit=limit, increment_weight=True)
                queries += 1
    conn = get_conn()
    compact_links(conn)
    conn.close()
    return queries


def warm_session_scoped(rounds, limit=5, spine=2):
    """EXPERIMENTAL warming: link across the queries of a session, not within one.

    This is the hypothesis the within-query mechanism cannot express. Production
    recall lays an edge only between two memories that appear in the SAME query's
    top-k (recall.py: zip(real_ids, real_ids[1:])). Top-k is similarity-ranked,
    so those two memories are near-neighbours — the graph ends up re-stating what
    cosine already knows, and a causally-linked-but-DISSIMILAR pair is never
    co-returned to be linked at all.

    NOTE ON GLOBAL STATE: warming EDGES are scoped to the theatre brain, but the
    compact_links() fold is global — it folds any pending raw footprints from the
    host brain's normal use into summary edges too. That is the same maintenance
    consolidate() runs on a timer (additive, lossless), so it is benign, but it
    is why this bench does not claim to leave the host graph byte-for-byte
    identical: it does not score or alter the host's SUMMARY edges, and it may
    compact footprints that were already due for compaction.

    A work session is a sequence of DIFFERENT questions for one job. The boiler
    deferral surfaces under 'what have we deferred', the damp costumes under
    'what problems with damp' — different queries, never the same top-k, but the
    same job. Linking the top `spine` hits of each query to the next query's, in
    order, lays exactly the cross-topic edge the demo narrative claims and the
    within-query mechanism cannot. increment_weight is OFF here because we are
    recording the session structure ourselves, not the per-query footprint.

    Legitimacy: the sessions are authored WITHOUT reference to the causal
    wikilinks (warm_graph's contract), so a causal pair only gets linked if the
    job genuinely pulled both ends — real co-use, not a plant.
    """
    conn = get_conn()
    queries = 0
    for _ in range(rounds):
        for _task, qs in SESSIONS:
            per_query = []
            for q in qs:
                hits = recall(q, project=PROJECT, limit=limit, increment_weight=False)
                per_query.append([h["id"] for h in hits[:spine]])
                queries += 1
            # Chain the job together: every key memory of one question links to
            # every key memory of the next. Consecutive, not all-pairs, so a long
            # session does not detonate into a clique that would inflate coverage.
            for cur_hits, nxt_hits in zip(per_query, per_query[1:]):
                for a in cur_hits:
                    for b in nxt_hits:
                        if a != b:
                            record_traversal(conn, a, b, link_type="session_cooccur")
    compact_links(conn)
    conn.close()
    return queries


def direct_edge(conn, a_id, b_id):
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM path_edge_summary WHERE (from_id=%s AND to_id=%s) "
        "OR (from_id=%s AND to_id=%s) LIMIT 1", (a_id, b_id, b_id, a_id))
    hit = cur.fetchone() is not None
    cur.close()
    return hit


def measure_pair(conn, p, k, seeds, hops, decay):
    """Cold (cosine+weight) vs warm (cosine seeds -> spreading activation).

    cold_hit / cold_rank: does plain recall put the cause in the top-k?
    surfaced: does spreading activation from the top cosine hits reach the cause
              at all — the additive recovery the demo claims.
    extras:   how many memories activation added that were NOT already in cold
              (the precision cost of switching activation on).
    covered:  is there a use-built edge between consequence and cause — the
              ceiling on what activation could possibly recover for this pair.
    """
    cold = recall(p["query"], project=PROJECT, limit=k, increment_weight=False)
    cold_ids = [r["id"] for r in cold]
    cold_hit = p["cause_id"] in cold_ids
    cold_rank = cold_ids.index(p["cause_id"]) + 1 if cold_hit else None

    seed_ids = cold_ids[:seeds] or [p["consequence_id"]]
    act = spreading_activate(conn, seed_ids, hops=hops, decay=decay, limit=k)
    act_ids = [a["id"] for a in act]
    extras = [i for i in act_ids if i not in cold_ids]
    surfaced = p["cause_id"] in act_ids
    warm_hit = cold_hit or surfaced

    return {
        "cosine": p["cosine"],
        "cold_hit": cold_hit, "cold_rank": cold_rank,
        "surfaced": surfaced, "warm_hit": warm_hit,
        "extras": len(extras),
        "covered": direct_edge(conn, p["consequence_id"], p["cause_id"]),
    }


def bootstrap_delta(cold_flags, warm_flags, iters=2000):
    """Paired bootstrap on the per-pair hit indicators: fraction of resamples in
    which warm's hit rate is NOT above cold's. A small value means the lift is
    unlikely to be resampling noise. Deterministic LCG (no Math.random equiv in
    the harness, and a fixed seed makes the number reproducible anyway).
    """
    n = len(cold_flags)
    if n == 0:
        return 1.0
    deltas_le0 = 0
    state = 0x2545F4914F6CDD1D
    for _ in range(iters):
        s_cold = s_warm = 0
        for _ in range(n):
            state = (6364136223846793005 * state + 1442695040888963407) & ((1 << 64) - 1)
            idx = (state >> 11) % n
            s_cold += cold_flags[idx]
            s_warm += warm_flags[idx]
        if (s_warm - s_cold) <= 0:
            deltas_le0 += 1
    return deltas_le0 / iters


def run(rounds=3, k=10, seeds=3, hops=2, decay=0.5, warm_limit=5,
        mode="query", verbose=True):
    conn = get_conn()
    ensure_seeded(conn)
    pairs, ambiguous = ground_truth_pairs(conn)
    if len(pairs) < 4:
        print(f"Only {len(pairs)} causal pairs resolved — cannot measure.")
        return {"error": "insufficient pairs"}

    cosines = [p["cosine"] for p in pairs]
    median = statistics.median(cosines)

    removed = reset_scoped_edges(conn)
    if verbose:
        print(f"{len(pairs)} causal pairs from the corpus "
              f"({ambiguous} positions dropped for duplicate subjects); "
              f"median pair-cosine {median:.3f}")
        how = ("within each query's top-k (production mechanism)" if mode == "query"
               else "ACROSS each session's queries (experimental session_cooccur)")
        print(f"reset {removed} intra-theatre edges to cold; "
              f"warming {rounds} rounds of {len(SESSIONS)} work sessions "
              f"(recall depth {warm_limit}; edges scoped to the theatre brain)")
        print(f"edge rule: {how}...")

    if mode == "session":
        queries = warm_session_scoped(rounds, limit=warm_limit)
    else:
        queries = warm_scoped(rounds, limit=warm_limit)
    cur = conn.cursor()
    cur.execute(
        "SELECT count(*) FROM path_edge_summary WHERE "
        "from_id IN (SELECT id FROM memories WHERE project=%s) AND "
        "to_id   IN (SELECT id FROM memories WHERE project=%s)", (PROJECT, PROJECT))
    edges = cur.fetchone()[0]
    cur.close()
    if verbose:
        print(f"{queries} queries -> {edges} use-built edges among theatre memories\n")

    rows = [dict(p, **measure_pair(conn, p, k, seeds, hops, decay)) for p in pairs]
    conn.close()

    far = [r for r in rows if r["cosine"] < median]
    near = [r for r in rows if r["cosine"] >= median]

    def block(name, rs):
        if not rs:
            return None
        cold = sum(r["cold_hit"] for r in rs)
        warm = sum(r["warm_hit"] for r in rs)
        # Two different notions of "the graph could help", kept distinct because
        # conflating them produced the nonsense "2 recovered of 0" earlier:
        #   direct_edges — a use-built edge sits directly between the pair (1 hop)
        #   recovered    — a cosine MISS that activation actually reached (up to
        #                  `hops`, so it can exceed direct_edges by going through
        #                  an intermediate). This is the real win count.
        direct_edges = sum(r["covered"] for r in rs)
        misses = len(rs) - cold
        recovered = sum(1 for r in rs if not r["cold_hit"] and r["surfaced"])
        p_val = bootstrap_delta([int(r["cold_hit"]) for r in rs],
                                [int(r["warm_hit"]) for r in rs])
        return {"name": name, "n": len(rs),
                "cold_hits": cold, "warm_hits": warm,
                "direct_edges": direct_edges, "misses": misses,
                "recovered": recovered,
                "avg_extras": round(statistics.mean(r["extras"] for r in rs), 1),
                "p": p_val}

    out = {"pairs": len(pairs), "median_cosine": round(median, 3),
           "edges": edges, "k": k,
           "far": block("FAR (cosine < median — similarity is weakest here)", far),
           "near": block("NEAR (cosine >= median — similarity already finds these)", near),
           "all": block("ALL pairs", rows)}

    if verbose:
        _print(out)
    return out


def _print(o):
    for key in ("far", "near", "all"):
        b = o[key]
        if not b:
            continue
        print("=" * 74)
        print(b["name"])
        print("=" * 74)
        cold_pct = 100 * b["cold_hits"] / b["n"]
        warm_pct = 100 * b["warm_hits"] / b["n"]
        print(f"  pairs: {b['n']}")
        print(f"  cosine-only hit@{o['k']}:  {b['cold_hits']}/{b['n']}  ({cold_pct:.0f}%)")
        print(f"  + use-built graph:   {b['warm_hits']}/{b['n']}  ({warm_pct:.0f}%)"
              f"   <- the claim, measured")
        print(f"  recovered: {b['recovered']} of {b['misses']} cosine misses reached "
              f"via activation")
        print(f"  direct causal edges the work built: {b['direct_edges']}/{b['n']} "
              f"(the structural ceiling on 1-hop help)")
        print(f"  precision cost: {b['avg_extras']} extra memories shown per query "
              f"on average")
        print(f"  paired bootstrap: P(lift <= 0) = {b['p']:.3f}")
        print()
    far = o["far"]
    print("-" * 74)
    if far and far["warm_hits"] > far["cold_hits"] and far["p"] < 0.05:
        print(f"VERDICT: on the pairs similarity handles worst, the use-built graph "
              f"lifts\n         recall {far['cold_hits']} -> {far['warm_hits']} of "
              f"{far['n']} (p={far['p']:.3f}). The mechanism earns its place.")
    elif far and far["warm_hits"] > far["cold_hits"]:
        print(f"VERDICT: a lift on FAR pairs ({far['cold_hits']} -> {far['warm_hits']}) "
              f"but not significant\n         (p={far['p']:.3f}) at this corpus size — "
              f"suggestive, not proven. Warm harder or say so.")
    else:
        print("VERDICT: no lift on FAR pairs. On this corpus the use-built graph did "
              "not\n         beat similarity — report that, do not bury it.")
    print("-" * 74)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--seeds", type=int, default=3,
                    help="how many cosine hits seed the spreading activation")
    ap.add_argument("--warm-limit", dest="warm_limit", type=int, default=5,
                    help="recall depth during warming — how many memories a use "
                         "co-recalls, which decides which pairs get an edge")
    ap.add_argument("--mode", choices=("query", "session"), default="query",
                    help="query = production's within-top-k edges; "
                         "session = experimental cross-query session edges")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    o = run(rounds=args.rounds, k=args.k, seeds=args.seeds,
            warm_limit=args.warm_limit, mode=args.mode, verbose=not args.json)
    if args.json:
        print(json.dumps(o, indent=2, default=str))


if __name__ == "__main__":
    main()
