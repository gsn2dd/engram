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
- **Measure:** same query, nearest-neighbour vs resolve-then-ridge, on an aged
  brain. Does the ridge return the answer a human would call *most on-point*?

### 2. Recall-distribution self-diagnostic

Every recall produces a distribution of relevance scores. A healthy brain should
have a characteristic *shape* to that distribution. Watching that shape **drift**
over time — as the graph grows — could be an early-warning signal that recall is
degrading, before a human notices. The shape of the boundary becomes a
correction signal.

- **Needs:** a long enough history to know what "healthy" looks like for a given
  brain.
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
