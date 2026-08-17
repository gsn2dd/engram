"""
The recall bench — does any of this machinery actually earn its place?

Engram's README splits its claims honestly into "proven" and "a bet". The bet is
that recall gets better *because of use*: that the association graph, the
fan-out perspectives, the temporal terms and the level-picking each make the
right memory easier to find than plain cosine similarity would. None of that had
ever been measured on this engine. It was designed, reasoned about, defended in
comments, and shipped — but not scored.

This is the scoring. Fix the corpus, fix the query, fix the embedding, and vary
exactly ONE thing: the recall policy. See docs/RECALL_MEASUREMENT.md for the
full design and its limits.

THE GROUND-TRUTH PROBLEM, and why wikilinks are the answer.

Almost every relevance signal in a brain was produced by the brain itself. Edge
weights come from what recall returned. Access counts come from what recall
returned. Topics come from the dreaming pass reading what recall could reach.
Scoring the ranker against any of those measures the ranker against its own
opinions, and it will always agree with itself.

Wikilinks do not have that problem. When a memory's body says "related: [[4269]]",
something outside the ranking system asserted that these two memories belong
together — usually an agent writing the memory, sometimes a human. The ranker
had no vote. That makes them the only non-circular relevance labels in the
corpus, which is why they are the primary source here despite being fewer and
noisier than the alternatives.

WHAT A QUESTION LOOKS LIKE. For a memory A that links to B, the query is A's
subject line and the correct answer is B. A itself is excluded from the results
(it would trivially rank first for its own subject), so the question being asked
is really: *given what A is about, does the brain surface what A says is
related?* That is a fair proxy for the thing an agent actually needs.

THE EASY/HARD SPLIT is where this gets interesting. Some linked pairs are
semantically adjacent — cosine finds them with no help at all, and no amount of
association machinery can improve on a job already done. The pairs that matter
are the ones where A and B are semantically DISTANT but genuinely related: the
connection cosine cannot see. That is precisely the case the association graph
was built for, and it is the only place it can prove itself. Reporting one
blended number over both would let the easy pairs hide whatever the hard pairs
show.

READ-ONLY BY CONSTRUCTION. Every recall here passes increment_weight=False, so
the bench writes no weights and lays down no edges. A benchmark that warmed the
graph would improve the corpus it is trying to measure, and each rung would be
scored against a brain the previous rung had already altered.
"""
import os
import re
import statistics
import sys
from typing import Dict, List, Optional, Tuple

from importlib import import_module

from .db import get_conn
from .recall import recall

# NOT `from . import recall as _recall_mod`. The package __init__ does
# `from .recall import recall`, which rebinds the name `recall` on the package
# to the FUNCTION — so the obvious import hands back a function and the embed
# cache below fails on a module attribute that isn't there. import_module goes
# to the module registry and is unaffected by the shadowing.
_recall_mod = import_module(f"{__package__}.recall")

WIKILINK = re.compile(r"\[\[(\d+)\]\]")

# The ladder. Each rung is today's behaviour with ONE more term switched on, so
# the difference between consecutive rows is attributable to that term alone.
# Names are what gets printed; keep them short enough to read as a table.
LADDER: List[Tuple[str, Dict]] = [
    ("cosine-only",   {"use_bonus": 0, "temporal": False, "superseded": False,
                       "perspectives": False, "level_pick": False}),
    ("+perspectives", {"use_bonus": 0, "temporal": False, "superseded": False,
                       "level_pick": False}),
    ("+use-history",  {"temporal": False, "superseded": False, "level_pick": False}),
    ("+temporal",     {"superseded": False, "level_pick": False}),
    ("+supersede",    {"level_pick": False}),
    ("shipped",       {}),
    # Answers "does learning from USE beat learning from EXPOSURE?" — the
    # question path_memory/events.py exists to make answerable. It will report
    # no difference until attributed events accumulate, which is not a bug and
    # is why `use_signal_readiness()` exists to say so out loud rather than
    # letting a flat line be read as a verdict.
    ("+use-signal",   {"success_bonus": 0.3}),
]


def build_wikilink_set(conn, min_cos=None, exclude_projects=None) -> List[Dict]:
    """Extract (query, expected_ids) pairs from numeric [[id]] references.

    Only numeric links are used. The corpus also carries slug-style links
    ([[feedback_reconcile_dont_overwrite]]) inherited from the file-memory
    convention, but resolving those to ids means guessing, and a guessed label
    is worse than no label — it would put noise into the one non-circular
    source we have.
    """
    cur = conn.cursor()
    cur.execute(
        """SELECT id, subject, body, project FROM memories
           WHERE body ~ '\\[\\[[0-9]+\\]\\]'
             AND archived = false AND embedding IS NOT NULL
             AND subject IS NOT NULL AND subject <> ''"""
    )
    rows = cur.fetchall()

    cur.execute("SELECT id FROM memories WHERE archived = false AND embedding IS NOT NULL")
    live = {r[0] for r in cur.fetchall()}

    cases = []
    for mid, subject, body, project in rows:
        if exclude_projects and project in exclude_projects:
            continue
        targets = {int(t) for t in WIKILINK.findall(body)}
        targets = {t for t in targets if t in live and t != mid}
        if not targets:
            continue
        cases.append({"source_id": mid, "query": subject,
                      "expected": sorted(targets), "project": project})
    cur.close()
    return cases


def pair_cosine(conn, a_id: int, b_id: int) -> Optional[float]:
    """Cosine between two stored memory vectors. Used to split easy pairs
    (cosine already finds them) from hard ones (only association can)."""
    cur = conn.cursor()
    cur.execute(
        """SELECT 1 - (a.embedding <=> b.embedding)
           FROM memories a, memories b WHERE a.id = %s AND b.id = %s""",
        (a_id, b_id),
    )
    row = cur.fetchone()
    cur.close()
    return float(row[0]) if row and row[0] is not None else None


def score_case(case: Dict, policy: Dict, limit: int, tiers=None) -> Dict:
    """Run one query under one policy; report where the expected ids landed.

    Excludes the source memory itself — it would rank first for its own subject
    line and tell us nothing.
    """
    hits = recall(case["query"], limit=limit + 1, increment_weight=False,
                  tiers=tiers, policy=policy)
    ranked = [h["id"] for h in hits if h["id"] != case["source_id"]][:limit]
    expected = set(case["expected"])

    ranks = [i + 1 for i, mid in enumerate(ranked) if mid in expected]
    best = min(ranks) if ranks else None
    return {
        "source_id": case["source_id"],
        "n_expected": len(expected),
        "found": len(ranks),
        "best_rank": best,
        "returned": len(ranked),
    }


def aggregate(results: List[Dict], k_values=(1, 3, 5, 10)) -> Dict:
    """hit@k, MRR and recall over a set of scored cases.

    MRR uses the BEST-ranked expected id per query, which is the standard
    reciprocal-rank definition and the one that answers "did the brain put
    something genuinely related near the top".
    """
    n = len(results) or 1
    out = {f"hit@{k}": sum(1 for r in results
                           if r["best_rank"] is not None and r["best_rank"] <= k) / n
           for k in k_values}
    out["mrr"] = sum(1.0 / r["best_rank"] for r in results if r["best_rank"]) / n
    total_expected = sum(r["n_expected"] for r in results) or 1
    out["recall_all"] = sum(r["found"] for r in results) / total_expected
    out["n"] = len(results)
    return out


def run(limit: int = 10, tiers=None, max_cases: Optional[int] = None,
        hard_split: bool = True, verbose: bool = True) -> Dict:
    """Run the full ladder over the wikilink ground-truth set.

    Returns {rung_name: {"all": metrics, "easy": metrics, "hard": metrics}}.
    """
    conn = get_conn()
    cases = build_wikilink_set(conn)
    if max_cases:
        cases = cases[:max_cases]

    # Split by how far apart the linked pair sits in embedding space. `hard`
    # means cosine alone has no easy route from A to B — the only case where
    # anything beyond similarity can possibly help.
    if hard_split:
        for c in cases:
            sims = [s for s in (pair_cosine(conn, c["source_id"], t)
                                for t in c["expected"]) if s is not None]
            c["pair_cos"] = max(sims) if sims else 0.0
        median = statistics.median([c["pair_cos"] for c in cases]) if cases else 0.0
        for c in cases:
            c["hard"] = c["pair_cos"] < median
    else:
        median = None
        for c in cases:
            c["hard"] = False

    if verbose:
        print(f"[bench] {len(cases)} wikilink cases, "
              f"{sum(len(c['expected']) for c in cases)} labelled pairs, "
              f"limit={limit}, median pair-cosine={median:.4f}"
              if median is not None else f"[bench] {len(cases)} cases", flush=True)

    # Embed each distinct query ONCE and reuse across every rung. The query text
    # is identical from rung to rung, so re-embedding would be pure cost — and
    # worse, it would let embedding jitter show up as a policy difference.
    cache: Dict[str, list] = {}
    original = _recall_mod.embed_one

    def cached_embed(text):
        if text not in cache:
            cache[text] = original(text)
        return cache[text]

    _recall_mod.embed_one = cached_embed
    try:
        report = {}
        for name, pol in LADDER:
            scored = [score_case(c, pol, limit, tiers) for c in cases]
            block = {"all": aggregate(scored)}
            if hard_split:
                block["easy"] = aggregate([s for s, c in zip(scored, cases) if not c["hard"]])
                block["hard"] = aggregate([s for s, c in zip(scored, cases) if c["hard"]])
            report[name] = block
            if verbose:
                a = block["all"]
                extra = ""
                if hard_split:
                    extra = (f"   hard: hit@5 {block['hard']['hit@5']:.3f} "
                             f"mrr {block['hard']['mrr']:.3f}")
                print(f"  {name:<14} hit@1 {a['hit@1']:.3f}  hit@5 {a['hit@5']:.3f}  "
                      f"hit@10 {a['hit@10']:.3f}  mrr {a['mrr']:.3f}{extra}", flush=True)
    finally:
        _recall_mod.embed_one = original
        conn.close()

    return report


def health_probe(sample_size: int = 20, topk: int = 10, seed_sql: str = "") -> Dict:
    """Can the brain still find a memory from a paraphrase of itself?

    This is the cheap daily canary, NOT a policy measurement — it answers "is the
    embedding pipeline intact", nothing more. Its ancestor lived outside the
    engine, embedded its probe queries with a DIFFERENT provider than the corpus,
    and therefore reported total recall failure for three days after an embedding
    migration before dying unnoticed. Two rules follow from that, and they are
    the whole reason this function is in the engine rather than in a cron script:

      1. It embeds through the SAME provider as the corpus, because it calls
         recall() rather than reimplementing it.
      2. It returns a verdict, not just a number. A diagnostic nobody reads is
         not a diagnostic.

    It deliberately uses the memory's own SUBJECT as the probe rather than a
    model-written paraphrase: no model call, no budget, no second failure mode.
    That makes it easier than the real task, which is correct for a canary —
    anything below the floor here is a pipeline fault, not a ranking opinion.

    THE POPULATION IS RESTRICTED, and each restriction was forced by a measured
    false alarm rather than chosen up front. Sampling every tier scored hit@5
    0.55 on a demonstrably healthy brain, because the misses were not recall
    failures at all: a dreaming-pass summary subjected "Topic summary:
    worldtownguide" carries no distinguishing signal, and a captured transcript
    whose subject is a bare `gs://...` URL is not a question anyone could
    answer. Curated memories with real subject lines scored hit@10 1.00 and 0.88
    on two samples of the same corpus. A canary that cries wolf over its own
    sampling is worse than none, because it trains its reader to ignore it —
    which is exactly how its predecessor died.

    THE THRESHOLD IS MEASURED, not picked. On this corpus:

        healthy                          hit@10 = 0.88
        query vectors in a foreign space hit@10 = 0.00   (768 dims permuted)

    That is the real fault being watched for — it is what the 2026-07-14
    embedding migration did — and the gap between the two states is the whole
    interval. 0.60 sits clear of sampling noise on the healthy side and nowhere
    near the fault side. It is a floor for "something is broken", never a
    quality target.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""SELECT id, subject FROM memories
            WHERE embedding IS NOT NULL AND archived = false
              AND subject IS NOT NULL AND length(subject) > 20
              AND subject !~ '^[a-z]+://'
              AND tier = 'curated' {seed_sql}
            ORDER BY random() LIMIT %s""",
        (sample_size,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    ranks = []
    for mid, subject in rows:
        hits = recall(subject, limit=topk, increment_weight=False)
        ids = [h["id"] for h in hits]
        ranks.append(ids.index(mid) + 1 if mid in ids else None)

    n = len(ranks) or 1
    hit5 = sum(1 for r in ranks if r and r <= 5) / n
    hit10 = sum(1 for r in ranks if r and r <= topk) / n
    found = [r for r in ranks if r]
    return {
        "n": len(ranks),
        "hit@5": hit5,
        "hit@10": hit10,
        "avg_rank": (sum(found) / len(found)) if found else None,
        # Judged on hit@10, not hit@5. The fault this watches for takes recall to
        # zero outright; ranking 4th instead of 2nd is corpus competition between
        # near-duplicate memories, which is normal and not a fault. See the
        # measured figures in the docstring.
        "verdict": "OK" if hit10 >= 0.60 else "FAIL",
    }


LENS_TYPES = ("questions", "thematic", "vantages")


def as_question(subject: str, body: str) -> Optional[str]:
    """Rephrase a memory's topic as a question someone would actually ask.

    The lens types are built for different query SHAPES — the `questions` lens
    is explicitly "what would someone be trying to solve when this memory is
    what they need". Scoring it only against subject-line probes would be
    testing it on the one phrasing it was not designed for, and then retiring
    it for underperforming. This generates the other phrasing so the comparison
    is fair.

    Deliberately derived from the SOURCE memory only. The answer being looked
    for is a different memory it links to, so the generator never sees the
    target and cannot leak it into the query.
    """
    import os
    from .llm import complete_text
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=60,
            messages=[{"role": "user", "content":
                "Write ONE short natural question (8-16 words) that someone working on "
                "this topic would actually type. Do not copy long phrases verbatim. "
                "Reply with only the question.\n\n"
                f"Subject: {subject}\nBody: {body[:600]}"}],
        )
        return complete_text(msg, what="bench question", quiet=True)
    except Exception:
        return None


def perspective_bench(limit: int = 10, verbose: bool = True,
                      query_style: str = "subject") -> Dict:
    """Do the fan-out lenses actually help recall — and do all three help?

    This tests engram's FIRST README claim: that a memory indexed from several
    perspectives is "findable from angles its literal text would never match".
    It is also the most expensive claim in the engine, because generating the
    lenses costs model calls on every single Memory.save().

    Two design points, both necessary or the number is meaningless:

      * ONLY CASES WHOSE TARGET HAS LENSES COUNT. Roughly half this corpus has
        no perspectives at all, and including those cases would dilute whatever
        effect exists toward zero and let a real result hide behind an average.
      * THE LENS TYPES ARE MEASURED SEPARATELY. They are not one feature; they
        are three prompts producing three different kinds of text, and there is
        no reason to assume they succeed or fail together. Merging them into a
        single on/off number is how you end up keeping a harmful one because a
        useful one carried it.

    Ground truth is the same wikilink set as run() — labels the ranker had no
    vote in.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""SELECT DISTINCT memory_id FROM memory_perspectives
                   WHERE embedding IS NOT NULL""")
    has_lenses = {r[0] for r in cur.fetchall()}
    cur.close()

    cases = [c for c in build_wikilink_set(conn)
             if any(t in has_lenses for t in c["expected"])]

    if query_style == "question":
        cur = conn.cursor()
        kept = []
        for c in cases:
            cur.execute("SELECT subject, body FROM memories WHERE id = %s", (c["source_id"],))
            row = cur.fetchone()
            q = as_question(row[0], row[1]) if row else None
            if q:
                c = dict(c, query=q)
                kept.append(c)
        cur.close()
        cases = kept

    if verbose:
        print(f"[perspectives] {len(cases)} cases whose target has lenses "
              f"({len(has_lenses)} memories carry any), query_style={query_style}",
              flush=True)

    cache: Dict[str, list] = {}
    original = _recall_mod.embed_one

    def cached_embed(text):
        if text not in cache:
            cache[text] = original(text)
        return cache[text]

    _recall_mod.embed_one = cached_embed
    base = {"temporal": False, "superseded": False, "level_pick": False}
    report = {}
    try:
        rungs = [("no lenses", False), ("all lenses", True)]
        rungs += [(f"only {t}", (t,)) for t in LENS_TYPES]
        for name, setting in rungs:
            scored = [score_case(c, dict(base, perspectives=setting), limit)
                      for c in cases]
            report[name] = aggregate(scored)
            if verbose:
                a = report[name]
                print(f"  {name:<16} hit@1 {a['hit@1']:.3f}  hit@5 {a['hit@5']:.3f}  "
                      f"hit@10 {a['hit@10']:.3f}  mrr {a['mrr']:.3f}", flush=True)
    finally:
        _recall_mod.embed_one = original
        conn.close()
    return report


def use_signal_readiness(limit: int = 10) -> Dict:
    """Can the use-signal question be answered yet? Answered by MEASUREMENT.

    The first version of this counted attributed events against a threshold of
    200. That was the wrong quantity and a guessed number — the two failures
    this file exists to avoid. The ranking term does not read events; it reads
    `success_count` ON MEMORIES. At the observed attribution rate, 200 events
    would have produced roughly ten marked memories out of thousands, and the
    rung would still have reported "no difference" — indistinguishable from the
    idea not working.

    So instead of a proxy threshold, run the rung and count how many bench
    results it CHANGES. Zero changed results means the question is unanswerable
    on the data available, whatever the event count says. Any other number and
    the comparison is real. Nothing is guessed.
    """
    from . import events
    r = events.readiness()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM memories WHERE success_count > 0 AND archived = false")
    r["memories_marked_used"] = cur.fetchone()[0]
    cur.close()

    changed = better = worse = 0
    cases = []
    try:
        cases = build_wikilink_set(conn)
        cache: Dict[str, list] = {}
        original = _recall_mod.embed_one

        def cached_embed(text):
            if text not in cache:
                cache[text] = original(text)
            return cache[text]

        _recall_mod.embed_one = cached_embed
        try:
            for c in cases:
                off = score_case(c, {"success_bonus": 0.0}, limit)
                on = score_case(c, {"success_bonus": 0.3}, limit)
                if off["best_rank"] != on["best_rank"]:
                    changed += 1
                    # Direction matters more than movement. A term that moves
                    # results only downward is not "not yet measurable" — it is
                    # measurably harmful, and those are opposite conclusions.
                    o = off["best_rank"] or 10 ** 6
                    n = on["best_rank"] or 10 ** 6
                    if n < o:
                        better += 1
                    elif n > o:
                        worse += 1
        finally:
            _recall_mod.embed_one = original
    except Exception:
        changed = -1
    finally:
        conn.close()

    r["bench_cases"] = len(cases)
    r["results_changed_by_the_term"] = changed
    r["better"], r["worse"] = better, worse
    if changed > 0 and better > worse:
        r["verdict"] = (f"ANSWERABLE — the term moves {changed}/{len(cases)} results, "
                        f"{better} better vs {worse} worse. Run the ladder and read "
                        f"the +use-signal rung before changing the default.")
    elif changed > 0:
        r["verdict"] = (
            f"HARMFUL SO FAR — the term moves {changed}/{len(cases)} results and "
            f"{worse} of them get WORSE ({better} better). With only "
            f"{r['memories_marked_used']} memories carrying a use mark it is "
            f"promoting memories the ranker ALREADY favours (marked memories "
            f"average 12x the weight and 23x the accesses of the corpus), because "
            f"a memory can only be marked used if it was shown first. More marks "
            f"make this worse, not better — the term is mis-shaped, not "
            f"under-powered. Leave success_bonus at 0; see DEFAULT_POLICY.")
    elif changed == 0:
        r["verdict"] = (
            f"NOT ANSWERABLE — only {r['memories_marked_used']} memories carry a "
            f"use mark, so the term changes NOTHING on {len(cases)} bench cases. "
            f"A rung run now would report 'no difference' for lack of data, which "
            f"is not the same as the idea failing. Leave success_bonus at 0.")
    else:
        r["verdict"] = "could not evaluate (no ground truth or no database)"
    r["ready"] = changed > 0
    return r


if __name__ == "__main__":
    if "--use-signal" in sys.argv:
        r = use_signal_readiness()
        print(f"[use-signal] events={r['events']} attributed={r['attributed']} "
              f"(judged-useless={r['attributed_empty']}) "
              f"memories_marked_used={r.get('memories_marked_used')} "
              f"bench_results_changed={r.get('results_changed_by_the_term')}"
              f"/{r.get('bench_cases')}\n  {r['verdict']}")
        sys.exit(0)

    if "--perspectives" in sys.argv:
        style = "question" if "--question-style" in sys.argv else "subject"
        perspective_bench(query_style=style)
        sys.exit(0)

    if "--health" in sys.argv:
        r = health_probe()
        print(f"[health] n={r['n']} hit@5={r['hit@5']:.2f} hit@10={r['hit@10']:.2f} "
              f"avg_rank={r['avg_rank']} -> {r['verdict']}")
        sys.exit(0 if r["verdict"] == "OK" else 1)

    lim = 10
    for i, a in enumerate(sys.argv):
        if a == "--limit":
            lim = int(sys.argv[i + 1])
    run(limit=lim)
