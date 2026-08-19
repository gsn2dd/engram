# What we measured, and how we know

Engram is full of numbers: a bonus of 0.1, a floor of 5%, a cap of 400
characters, one lens instead of three. Every one of them is a decision, and a
decision without its evidence attached decays into folklore — someone later
reads `USE_BONUS = 0.1`, assumes it was reasoned, and either trusts it too much
or changes it for a better-sounding reason.

This is the map from each number to the measurement that produced it. It exists
because this engine has twice shipped a ranking term that was argued for
carefully and was simply wrong, and in both cases nothing recorded what evidence
would have settled it.

**The rule this file encodes:** if a number cannot point at a measurement, it is
a guess wearing a decimal point. Fix that by measuring, or by saying plainly in
the comment that it is a guess.

---

## Ranking

### `USE_BONUS = 0.1`, with rank normalisation

**The claim being tested:** that use-history makes recall better — engram's
central and most distinctive bet.

**It was false as shipped.** With `USE_BONUS = 0.5` and weight normalised
against the pool maximum, the ranker scored *below plain cosine similarity*.

| | hit@5 | MRR |
|---|---|---|
| cosine only | 0.479 | 0.308 |
| old (0.5, max-norm) | 0.315 | **0.241** |
| new (0.1, rank-norm) | 0.493 | **0.344** |

*(mindspace, held-out half, n=73)*

Probed with a memory's **exact subject line** (n=120), the old ranking returned
that memory first **13.3%** of the time against cosine's **85.8%**. It was
burying exact matches under globally-popular ones.

**Root cause was the shape of the transform, not its coefficient.** Accumulated
weight is heavy-tailed — measured: mean 0.19, max 5.83, only 15% of memories
carrying any weight at all. Dividing by the maximum handed a handful of memories
nearly the whole bonus on every query. Rank normalisation is outlier-immune and
claims only what the design ever meant: the *order* of use, not the magnitude.

**Replicated on a second brain** (`engram_test`, 3,841 memories, a different
weight distribution — 534 weighted, max 3.45):

```
cosine only            MRR 0.3738
old (0.5, max-norm)    MRR 0.2228
new (0.1, rank-norm)   MRR 0.3866

new vs old      +0.1637   p=0.000   SIGNIFICANT
old vs cosine   -0.1510            old was significantly WORSE than no ranking
new vs cosine   +0.0128   p=0.271   not significant
```

**What this does and does not establish.** The bug and the fix both generalise,
decisively. That use-history *beats* plain cosine does not: positive on both
brains, significant on neither. The hard pairs — the ones cosine cannot find,
which is the whole reason an association graph exists — improve +45% MRR on
mindspace and +28% on the second brain. Consistent direction twice, significance
neither time.

So the honest status of the central claim is **not harmful (proven twice) and
probably helpful on hard associative pairs**. Not "proven". The README should
not say proven.

*Where: `path_memory/recall.py`, `path_memory/bench.py`, `docs/RECALL_MEASUREMENT.md`.*

### `success_bonus = 0.0` — built, wired, and retired

Ranking on "this memory was actually used" sounds strictly better than ranking
on "this memory was returned". Measured, it is worse: the term moves **37 of 152**
ground-truth results and **35 get worse**. The verdict *strengthened* as marks
accumulated from 6 memories to 25 — the opposite of an under-powered test.

Two structural reasons, both measured:

1. **The signal is conditional on retrieval.** A memory can only be marked used
   if recall showed it first. Marked memories average weight 2.292 and 27.9
   accesses against a corpus average of 0.197 and 1.2 — **12× and 23×**. The
   signal lands on what the ranker already favours, so boosting it amplifies its
   preferences instead of correcting them.
2. **It is query-independent.** The real evidence is *(query, memory)* pairs;
   collapsing that to one scalar per memory reduces to "popular ranks higher" —
   the same defect already fixed twice above.

The use signal keeps its value as **evaluation** data: it is how we know recall
demonstrably helps on ~24% of real prompts.

### `SUPERSEDED_FACTOR`, `TEMPORAL_FACTOR`, level-picking

**Not individually validated.** They are no-ops on the ground truth available,
because the wikilink set contains almost no superseded, calendar-anchored or
derived memories. Absence of effect *on a set that cannot exercise them* is not
evidence against them — and saying so is the point of listing them here.

---

## Perspectives — one lens, not three

**The claim:** a memory indexed under several lenses is findable from angles its
literal text would miss. It was also the most expensive claim in the engine: one
model call per lens on every single write.

Direct lookup — a question the memory answers, which is the `questions` lens's
own design brief (n=150, paired bootstrap):

| lens | MRR | hit@1 | vs none |
|---|---|---|---|
| none | 0.745 | 0.627 | — |
| **questions** | **0.799** | **0.707** | **+0.055, p=0.015** |
| all three | 0.797 | 0.707 | +0.052, p=0.020 |
| thematic | 0.750 | 0.633 | +0.005, p=0.184 |
| vantages | 0.747 | 0.633 | +0.002, p=0.399 |

`thematic` and `vantages` changed 4–10 results out of 150. Questions-only
(0.7993) edged all-three (0.7968), because merging is `max()` — an inert lens
cannot help the right memory it fails to match, but can still promote a wrong
one it happens to match.

**Result: a 3× cut in the cost of a write, with no measured retrieval loss.**

**A near-miss worth recording.** On the *associative* task, two "significant"
lens wins appeared in opposite directions depending on whether the probe was a
subject line or a question. Across ten comparisons, one hit each way is what
chance produces. Both were discarded; only the lookup result replicated.

**Honest caveat:** `vantages` targets alias-shaped queries and no experiment
probed those. It was retired for being inert on what was tested, which is not
the same as disproven. `ENGRAM_LENSES=all` restores it.

---

## Association — the use-built graph does not beat similarity on retrieval

This is the claim engram rests on, so it gets the harshest test: memories
recalled together lay down edges, and spreading activation later surfaces what
is linked *by use* even when it is far away in embedding space — the thing a
vector store structurally cannot do. `tests/bench/assoc_bench.py` measures it
non-circularly, and the answer is **no, not measurably, on this corpus.**

**The test.** Ground truth is the theatre corpus's own causal `[[N]]`
wikilinks — "the roof leak caused the closure that cut the bar takings" —
authored by the corpus generator, independent of anything the bench warms on.
The graph is warmed by `warm_graph`'s eight work-sessions, authored *without
reference to those links*. So a causal pair can only be helped if real
simulated work happened to co-recall both ends: no plant, and coverage is
reported as its own number rather than folded into a hit rate.

**The result**, on the 29 FAR pairs (cosine below median — where similarity is
weakest and association should earn its keep): cosine-only hit@10 = **9/29**;
adding spreading activation = **11/29**. A lift of two, **not significant**
(paired bootstrap P(lift≤0) ≈ 0.12), and it costs **~7 extra memories injected
per query**. On NEAR pairs the graph adds nothing (28/29 either way).

**Why, measured three ways.** The binding constraint is *coverage*: only
**2–7 of 58** causal pairs ever got a use-built edge. Widening the warming
window 5→15 exploded the edge count 152→901 but did **not** lift recall —
more edges, more noise, same two recoveries. Switching the edge rule from
production's within-query co-recall (`recall.py`: `zip(real_ids,
real_ids[1:])`) to an experimental **cross-session** rule did not help either
(9→10, fewer edges). The reason is structural and rule-independent: **co-recall
is organised by topic, and the causal pairs deliberately cross topics.** The
roof-leak lives in the building job, the bar-takings in the bar job — different
sessions, never co-recalled. Use recapitulates similarity, so the graph built
from use recapitulates similarity, and the pairs that would most benefit from a
non-similarity link are exactly the ones no realistic use co-locates.

**What this does and does not retire.** It does not delete spreading activation:
the demo (`demo_theatre.py --warm`) shows it surfacing genuinely associated
context, which has qualitative value. It retires the *quantitative* claim —
"linked-by-use retrieval beats similarity" is **not** supported by measurement
here, and the docs and demo must not assert it. Like `success_bonus`, a
believed-in mechanism was built, measured, and found not to earn a ranking role
on the evidence available. If it is ever to beat cosine, the edge would have to
come from something other than similarity-ranked co-recall — a direction, not a
result.

---

## Injection — what actually reaches the context

### `recall_form`, cap enforced at 400 characters

Recall never injected whole memories; it injected `body[:220]`. Curated bodies
average 767 characters, p90 is 2,256, longest 38,606 — so a typical memory
arrived **90% missing with the cut made by position rather than importance**.
One real finding injected its date and a preamble while the measured numbers it
existed to record sat at character 2,100 and never reached the context.

**The cap is enforced in code, not requested in a prompt.** Asked for 400
characters, the model averaged **768** across the first 89 real memories — which
would have made the feature *cost* context rather than save it. Trimmed at the
last sentence boundary: now 341 average, 401 max.

**The design decision that makes it safe:** the embedding stays on the full
body, so findability is provably untouched. Only what is shown changes.

### Excluding what the conversation already holds

Across 73 injections, **191 of 365 memory-slots (52%)** were memories the same
session had already been given, still sitting in context from an earlier turn.
The fix does not shrink the budget — it fetches deeper and fills the freed slots
with material the session has not seen.

### Prompt caching — not applicable, and why

Tool definitions are static and sit *inside* the cacheable prefix; tool results
and injected recall are *appended after* it, and appending cannot invalidate a
prefix. The one pattern that would break it is putting recalled memories in the
**system prompt**, which changes every turn in front of everything else.

---

## Diagnostics

### Canary threshold: hit@10 ≥ 0.60

Measured against a simulated fault rather than chosen:

```
healthy                            hit@10 = 0.88
query vectors in a foreign space   hit@10 = 0.00   (768 dims permuted)
```

That fault is the real one — it is what an embedding-provider migration does.
The population is restricted to curated memories with real subject lines, and
**each restriction came from an observed false alarm**: sampling every tier
scored 0.55 on a demonstrably healthy brain because the misses were a
dreaming-pass summary subjected "Topic summary: worldtownguide" and a transcript
whose subject was a bare `gs://` URL.

### Collapse floor: 5% of the top score

On a real eight-memory field the genuine on-topic-to-noise cliff was 0.2316 raw
— **31% of the top score** — while the largest drop *within* either cluster was
0.0357, or **4.8%**. The floor sits between them with room on both sides.

### Open-loop detection window: 45 days

225 memories remain unjudged across all history against 36 inside the window, so
an unbounded pass spends its budget on archaeology. Mining a fast-moving
project's back-catalogue yields facts about the past; last week yields jobs.

---

## Things that are still guesses

Listed so they are not mistaken for measurements.

- **`min_gap = 0.18`** in collapse — the relative threshold, unlike the absolute
  floor beside it, was never fitted.
- **`PROMOTE_AT = 3`**, `CLUSTER_SIM = 0.62`, `TAG_SIM = 0.60`, `MIN_CLUSTER = 3`
  in the dreaming pass — honest heuristics, stated as such in the source.
- **`NEAR_DUPLICATE = 0.95`** in write-time warnings — anchored to a measurement
  (unrelated curated memories average 0.66, max 0.90 between two random ones)
  but the threshold itself is a judgement in that gap.
- **`TEMPLATE_AT = 5`** — chosen to fire early rather than derived.

---

## The limit on all of it

Every number above except the `engram_test` replication was fitted to **one
corpus**: mindspace. One author, one domain, one writing style, one embedding
model. `engram_test` is the same corpus at a different time, so it tests
robustness to use-history state, not to domain or authorship.

A genuinely independent brain — different domain, different author, hard-but-
possible ground truth — is the outstanding gap, and until it exists
"generalises" here means "across use-history states", which is narrower than it
sounds. `tests/bench/build_second_brain.py` is the attempt; see its docstring
for two calibrations that failed and why.
