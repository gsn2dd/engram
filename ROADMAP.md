# Roadmap

Engram's honest open question is **how recall holds up over time** — once a
brain has been used for weeks and has grown a real association graph. Almost
everything planned next can only be meaningfully *built and tested against an
aged brain*, not a fresh one. So this is less a feature list and more a set of
experiments waiting for a warm graph.

## The open question

> As the graph grows to thousands of memories and the decay-and-strengthening
> loop runs for weeks, does the **right** memory stay easy to find, and does the
> **unused** stuff fade cleanly — or does recall slowly drift?

If you run Engram in earnest, this is the thing we'd most like your data on.

## Why "aged brain" matters

A **fresh** brain has no edges. Nothing has been recalled together yet, so the
only signal is semantic similarity — the literal closeness of meanings. A
**used** brain is different: it has *paths*. Memories that were recalled together
laid down edges; edges that proved useful got stronger; neglected ones decayed.
At that point the brain knows things similarity alone can't tell you — which
memories *go together in practice*.

The features below all depend on that. They have little to measure on a cold
brain, which is exactly why they're roadmap items, not shipped ones.

## Update (0.5.1): a warm graph can now be manufactured — with one caveat that matters

The framing above — *these experiments can only be tested against an aged brain,
and we don't have one* — is now half wrong. `tests/bench/warm_graph.py` and
`pm demo-theatre --warm` build an association graph on demand by replaying
task-shaped work: sequences of queries authored as real jobs (preparing the
funding submission, chasing the insurance claim), so memories co-recalled inside
a task become linked. On the 213-memory theatre brain, 114 such queries lay down
242 edges and 88 memories gain weight. The experiments below no longer have to
*wait* — they can be built and run today.

**What the harness proves, and what it does not.** Spreading activation over the
manufactured graph works and is visibly different from similarity: a
funding-deadline query reaches a newly-appointed chartered-accountant trustee it
shares no words with — a memory cosine never returns. That is the mechanism, and
it is real.

But on the same brain, the harness did **not** reproduce the ranking win the
association graph shows on the live mindspace corpus. Measured on the wikilink
bench after warming:

| | cold | warm |
|---|---|---|
| hit@1 | 0.276 | **0.310** |
| hard-pair MRR | 0.149 | **0.130** |

hit@1 improved; hard-pair MRR — the metric use-history helps most on mindspace
(+45%) — got slightly *worse*. So a **simulated** warm graph is not
interchangeable with a **real aged** one. The likely reasons are scale and
authenticity: ~200 hand-simulated queries over 213 memories is not months of
genuine work over thousands, and simulated co-recall may be systematically
different from the real thing. That is itself a roadmap finding: **the open
question is not just "does a warm graph help" but "how much of the benefit
survives simulation" — because if none of it does, every experiment below still
needs real user data, and the harness only tests the plumbing.**

So the harness changes the status of the experiments from *blocked* to
*runnable-but-not-conclusive*: it can prove a mechanism exists and can catch a
regression in it, but it cannot yet stand in for the aged-brain evidence the
open question really wants. Both are still needed.

## Planned experiments

### 1. Resolve-then-ridge recall

Today, [`collapse`](README.md) finds the **doorway** — it resolves the blurry
relevance field into the set of genuinely-relevant memories. The next step is to
*walk through it*: once the doorway is found, return the **highest-strength
path** through that set using the use-built association graph, instead of points
ranked only by similarity.

Picture a memory as a room and the relevant cluster as a house. `collapse` picks
which doorway you leave by. The **ridge** is the route the brain has actually
worn smooth through that house — the strongest chain of associations, not the
single nearest point.

- **Hypothesis:** path-first recall beats nearest-neighbour — but **only once
  the graph is warm.**
- **Now buildable.** The warm-graph harness can produce the graph this needs, so
  resolve-then-ridge can be *implemented and smoke-tested* today rather than
  waiting for an aged brain. The `--warm` demo already shows spreading
  activation surfacing use-linked memories similarity misses — the raw material
  a ridge would walk.
- **Measure:** same query, nearest-neighbour vs resolve-then-ridge, on **both** a
  simulated-warm brain and, when available, a real aged one. The gap between the
  two is itself the result — see the 0.5.1 caveat above. The synthetic run tells
  you whether the mechanism is sound; only the real one tells you whether it
  holds up over time.

### 2. Recall-distribution self-diagnostic

Every recall produces a distribution of relevance scores. A healthy brain should
have a characteristic *shape* to that distribution. Watching that shape **drift**
over time — as the graph grows — could be an early-warning signal that recall is
degrading, before a human notices. The shape of the boundary becomes a
correction signal.

- **Needs:** a long enough history to know what "healthy" looks like for a given
  brain. The warm-graph harness can now establish a synthetic baseline to
  degrade *against*, which the drift test needs — though "healthy" on a
  manufactured graph and "healthy" on a real one may differ, per the 0.5.1
  caveat.
- **Measure:** does a deliberately-degraded brain (e.g. flooded with
  near-duplicate noise) show distribution drift the diagnostic catches?

### 3. Retention-over-time validation

Instrument the decay-and-strengthening loop over weeks: track whether
frequently-needed memories stay easy to find and neglected ones fade cleanly.
This is the direct test of the open question above — and the data that tells us
whether anything in (1) or (2) is actually worth keeping.

## How you can help

Run a brain for real, for a while, and tell us what it remembered and what it
forgot. That single signal is worth more than any feature we could guess at.
Open an issue with what your brain got right and what drifted.

## Scheduled removals

- **`dream_state` → `dream_watermarks` migration shim** (`path_memory/dream.py::_ensure_state`):
  the one-time carry-over of the old global reading watermark into per-project
  rows. Every known brain (mindspace, the AMI line from 0.4.0) has migrated.
  Remove in 0.6.0 — after one release of soak, so any brain upgraded straight
  from ≤0.3.x still crosses the bridge once. The `dream_state` table itself
  goes at the same time.
