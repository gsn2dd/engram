# Changelog

All notable changes to Engram are recorded here. Engram uses
[semantic versioning](https://semver.org/); each version maps to a git tag and a
published container image.

## [0.5.1] — 2026-08-18

A small follow-up folding four commits made after the 0.5.0 tag into a published
image — no behaviour change to the served engine, but the container was running
0.5.0 code while `main` had moved on.

### Added
- **Graph-warming harness and the `--warm` demo** (`tests/bench/warm_graph.py`,
  `pm demo-theatre --warm`). Engram's use-built association graph is inert on a
  freshly-seeded brain, so the differentiator — memories linked by USE rather
  than meaning — cannot be shown on a cold demo. `--warm` simulates a few weeks
  of task-shaped work (queries authored as real jobs, independently of the
  bench's ground truth) and shows the same query before and after: on the
  theatre brain, 114 queries lay down 242 edges, and spreading activation then
  surfaces memories cosine never returns (a funding-deadline query reaches the
  newly-appointed chartered-accountant trustee). The warming is visible in the
  harness; nothing is pre-baked.
- **Question-generator overlap gate** (`tests/bench/build_questions.py`) — the
  prompt's "do not reuse the answer's distinctive words" rule is now enforced in
  code, with an ASCII-folding fix so accented words like "façade" are not
  invisible to the checker.
- **chrome-agent capture-testing tooling** (`browser-capture/tools/`).

### Fixed
- **Embedding selection and failures now name the provider** (`path_memory/embed.py`).
  `auto` picking a vendor silently meant a stale key produced a bare 401 from a
  provider the operator did not know was in play. Selection now announces itself
  once per process, and a failure carries the provider, model and how it was
  chosen. Diagnosability only — `assert_brain_compatible()` already prevented
  any corruption.

## [0.5.0] — 2026-08-18

The "measure the claim" release. Engram's distinctive bet — that recall improves
because of use — was scored for the first time, against ground truth the ranker
did not generate. It was failing.

Everything below was measured before it was changed, and the measurements are
mapped to their decisions in [`docs/WHAT_WE_MEASURED.md`](docs/WHAT_WE_MEASURED.md).
Three things were deliberately NOT changed despite sounding like improvements —
`success_bonus` stays at 0, and two of the three fan-out lenses are kept in the
code though retired from use — because the evidence said so. What is honest
about this release is as much what it declined to ship as what it shipped.

### Added
- **Recall form — lossless at rest, lossy on the way out** (`recall_form`
  column, `path_memory/recall_form.py`). Recall never injected whole memories;
  it injected `body[:220]`. Curated bodies average 767 characters and p90 is
  2,256, so a typical memory arrived 90% missing with the cut made by POSITION
  rather than importance — one real finding injected its date and a preamble
  while the measured numbers it existed to record sat at character 2,100 and
  never reached the context. A memory now carries a short form used ONLY for
  injection. **The embedding stays on the full body**, so findability is
  provably untouched — a memory is found exactly as often and ranked exactly as
  high; only what gets shown changes. Supplied at write time via
  `remember(recall_form=...)` when the writer knows what mattered, or written
  offline by the dreaming pass, most-recalled-first. The length cap is enforced
  in code, not requested in a prompt: asked for 400 characters the model
  averaged 768 across the first 89 real memories, which would have made the
  feature cost context rather than save it.
- **Open loops — what was concluded and never done** (`open_loops`,
  `path_memory/open_loops.py`, `pm open` / `pm close`, MCP `open_loops` /
  `close_loop`). A brain that records diagnoses but cannot say which were acted
  on is a filing cabinet. A cheap regex narrows candidates, a model judges
  whether the memory states something explicitly *not done*, and a budget bounds
  the pass — the same shape as the dreaming pass, which now runs it hourly.
  Loops close on evidence only: supersession, or an explicit close. **Silence is
  never completion** — a loop ages, it never expires. Surfaced in the
  session-start context rather than behind a command, because a list you must
  opt into is a list that rots.
- **Recall events — shown is not used** (`recall_events`, `path_memory/events.py`).
  Recall strengthened everything it returned, so the association graph was
  learning what the ranker likes rather than what turned out to be worth having
  — and with an always-on recall hook, that is a closed loop. Every recall now
  logs what it showed (with ranks and scores); what was *used* is attributed
  afterwards, by an agent reporting it (`mark_used` MCP tool) or by an offline
  rule reading what followed. `NULL` used means "not yet judged" and is
  deliberately distinct from `[]`, "judged, and nothing shown helped" — the one
  outcome nothing else can detect, a recall that fails while looking like it
  worked. `Memory.used()` is the reinforcement path; `Memory.success()` remains
  as its WorldTownGuide-lineage alias.
- **`success_bonus` ranking term — built, wired, and OFF (0.0).** It stays off
  until the bench says it earns its place. That restraint is the direct lesson
  of `USE_BONUS`, which was shipped at 0.5 on reasoning alone and spent months
  making recall worse than no ranking at all. Capture runs from day one so data
  accrues; `pm bench --use-signal` reports when there is enough to answer, and
  the `+use-signal` rung answers it. The term saturates rather than scaling
  linearly — the signal is "has this ever helped", not "how many times".
- **A demo that shows what a vector store cannot do** (`pm demo-theatre
  --verify`). 213 memories from a fictional theatre — a domain engram was never
  tuned on — demonstrating collapse ("how many answers are there?" rather than
  "give me five"), supersession ("is this still true?"), and temporal re-tensing
  judged against today. It ships as DATA, not a generator, so every question in
  it stays verified. It also prints what it does NOT show: on a cold brain
  engram's retrieval is good but not categorically better than a competent
  vector store, and the use-built association graph only appears after weeks of
  real use.
- **The recall bench** (`path_memory/bench.py`) — a policy ladder that fixes the
  corpus, query and embedding and varies exactly one thing: the ranking policy.
  Ground truth comes from `[[id]]` wikilinks between memories, the only
  relevance labels in a brain that the ranker had no vote in; cases split
  easy/hard by pair cosine, because the hard pairs are the only place
  association can prove anything similarity has not already done. See
  [`docs/RECALL_MEASUREMENT.md`](docs/RECALL_MEASUREMENT.md).
- **Health probe** (`pm bench --health`) — the cheap canary: can a memory still
  be found by its own subject line? Runs inside the engine, so it embeds through
  the same provider as the corpus by construction, and returns a verdict rather
  than a number. Its threshold is measured against a simulated fault (healthy
  hit@10 0.88; query vectors in a foreign space 0.00), not chosen.
- **`recall(policy=...)`** — override individual ranking terms without forking
  the function. For the bench; not a general tuning surface.

### Changed
- **Two of the three fan-out lenses are retired.** Generation and retrieval now
  default to the `questions` lens alone. Measured across three experiments and
  two ground truths with a paired bootstrap: on direct lookup — the lens's own
  design brief — `questions` is worth +0.055 MRR (p=0.015) and takes hit@1 from
  0.627 to 0.707, while `thematic` (+0.005, p=0.184) and `vantages` (+0.002,
  p=0.399) changed 4–10 results out of 150. Questions-only (0.7993) even edged
  all-three-merged (0.7968), because perspective merging is `max()` — an inert
  lens cannot help the right memory it fails to match, but can still promote a
  wrong one it happens to match. This is a **3× cut in the cost of a write**
  with no measured retrieval loss. Both retired lenses stay defined and their
  stored rows are never deleted; `ENGRAM_LENSES=all` restores the historical
  three. Honest caveat: `vantages` targets alias-shaped queries and no
  experiment probed those, so it was retired for being inert on what was
  tested, which is not the same as disproven.

### Fixed
- **Use-history was making recall WORSE.** Held out (n=73): shipped scored MRR
  0.241 against plain cosine's 0.308. Probed with a memory's exact subject line
  (n=120), the shipped ranking returned it first 13.3% of the time versus
  cosine's 85.8%. Root cause was the *shape* of the transform, not its
  coefficient: weight was normalised against the pool maximum, and on a
  heavy-tailed distribution (mean 0.19, max 5.83, 15% non-zero) that gave a
  handful of memories nearly the whole bonus on every query — the same
  popularity-beats-relevance defect fixed in 0.4.0, surviving at lower
  amplitude because only the coefficient had ever been revisited. Now rank-
  normalised (outlier-immune, and the order of use is all the design ever
  claimed) with `USE_BONUS` 0.5 → 0.1. New: MRR 0.344, and **+55% MRR on the
  hard pairs** the association graph exists for.
- **`increment_weight=False` now gates edge writes, not just node weights.** A
  read-only recall was still laying down permanent association edges, so
  mindspace's transcript search had been building the graph it is documented
  never to touch — and no benchmark can score a graph that every scoring run
  alters.

## [0.4.0] — 2026-08-08

The "brain that maintains itself" release: engram now compresses its own
corpus offline, ships as a bootable AWS image, and — at last — authenticates
its MCP endpoint.

### Added
- **MCP bearer-token auth** — set `ENGRAM_MCP_TOKEN` (24+ chars) and every
  request to the MCP endpoint must carry `Authorization: Bearer <token>`.
  Constant-time comparison, gates `/sse` and `/messages/` alike. Unset keeps
  the historical open behaviour (loopback-only!) with a loud warning. This was
  the blocking feature for any deployment beyond one machine.
- **The dreaming pass** (`pm dream` / `path_memory.dream`) — an hourly,
  budget-capped consolidation pass that READS new memories with a model,
  discovers the subjects they are about (topics), backfills those topics across
  the whole corpus by literal match, writes topic summaries and per-hour period
  digests back as first-class memories (`origin='recycle'`, chained by
  supersession), and promotes repeatedly re-formed collapse doorways into
  topics. Per-project watermarks mean an hour with nothing new costs zero model
  calls.
- **Collapse doorways** (`path_memory.boundary`) — a clean collapse resolution
  is persisted as a keyed doorway (members, centroid, example query); repeated
  resolution is the evidence the dreaming pass uses for promotion. Naming
  happens offline in the pass, never on the read path.
- **Project registry** — `projects` / `project_aliases` / `memory_projects`
  with slug canonicalisation (transliteration + hash fallback for non-Latin
  names), many-to-many memory↔project links with roles, and alias resolution in
  BOTH `Memory.save` and `recall`, so a memory is recallable under the same
  name it was written with.
- **Browser-capture ingest endpoint** (`ingest_server.py`, port 8081) — the
  authenticated surface the Engram Capture extension posts conversations to;
  bearer token required, server-side secret scrub, idempotent by exchange id.
- **Pluggable embedding providers** — Gemini (`gemini-embedding-001`) or
  OpenAI (`text-embedding-3-small`), both 768d, selected by
  `ENGRAM_EMBED_PROVIDER`/available key; vectors from different models are
  never mixed.
- **Provenance and tiers** — memories carry `tier` (curated / transcript /
  insight / decision / project), `origin`, `source_system`, `source_uri`,
  `exchange_id`, `derived_from` / `derived_depth` for summaries, and a
  versioned credential redaction pass at the save boundary.
- **AWS Marketplace deployment** (`deploy/aws/`) — AMI build pipeline,
  CloudFormation template (no inbound ports; SSM port-forward access),
  first-boot instance-unique credentials (DB password, ingest token, MCP
  token), SSM Parameter Store key loading, login guide (`get_started`,
  `engram-help`).
- **Demo brain + starter brain** — `demo_company.py` seeds a fictional
  company whose 14 test questions double as an end-to-end install self-test
  (`--verify`); `seed_starter.py` seeds engram's own documentation as
  memories so a fresh brain answers its first question.

### Fixed
- **Use-history can no longer outrank relevance.** Ranking was additive with
  weight at 0.7 vs cosine at 0.1; warming one cluster hijacked every later
  query. Relevance is now the base and use-history a bounded (≤1.5×)
  multiplier.
- **Collapse no longer invents cliffs in flat fields** — a drop must clear an
  absolute floor (5% of the top score, measured) as well as the relative gap,
  and normalisation spans the whole candidate pool.
- **Transaction poisoning in `Memory.save`** — perspective-lens failures roll
  back to a savepoint instead of poisoning the transaction after commit-less
  returns of phantom ids.
- **Schema is applied on every container start** — upgrades no longer run new
  code against an old schema; `schema.sql` is fully idempotent.
- **Folded-JSON redaction is reported, not silent** — `recall_json` names
  redacted or unparsable leaves instead of returning placeholders dressed as
  data; `fold_json(redact=False)` opts out deliberately.
- Dreaming-pass correctness: per-project watermarks (no project starved by the
  largest), read-but-empty batches advance, unregistered projects register
  instead of rolling back the pass, deterministic member selection stops
  identical re-summaries, round-robin reading spends the whole budget.

### Changed
- `mcp>=1.2.0,<2.0.0` and all majors capped after an unpinned `mcp` 2.0 broke
  the published image.

## [0.3.0] — 2026-06-25

### Added
- **Collapse** — `recall(collapse=True)`: adaptive result sizing. Instead of
  returning a fixed top-`limit` padded with weak matches, recall resolves the
  relevance field into keep/drop by finding the natural *cliff* in the scores
  and returning only what sits above it — so a question with three real answers
  comes back as three, not five. When nothing falls off a cliff (everything is
  relevant) it simply returns the top `limit`, so it's safe to leave on. Opt-in,
  default off; exposed through the MCP `recall` tool. See the README's
  *Collapse* section for the intuition.

## [0.2.0] — 2026-06-24

### Added
- **Creativity** — `recall(creativity=0..1)`: a structured-serendipity dial. At
  `0` you get the precise best matches; turn it up and recall swaps a growing
  share of the result *tail* for **near-miss memories** — semantically adjacent
  but not the obvious answer — to spark connections the literal query would
  miss. Sparks are flagged `serendipity=true`, treated as prompts rather than
  facts, and deliberately never strengthen the use-built graph.

## [0.1.0] — 2026-06-24

Initial public release — an open-source, self-organising memory *brain* an AI
agent attaches to. 100% AI-coded (Claude), human-inspired (David Dand).

### Added
- **The brain.** Memories indexed from **multiple perspectives at once** (their
  themes, the questions they answer, the names they go by); an **association
  graph** grown from how memories are actually used, with **spreading
  activation** to surface what's linked by use rather than only by meaning;
  **retrieval-strengthening and temporal decay** so importance emerges from use,
  not assignment; **project scoping**; **supersede / distillation** (a corrected
  memory ranks below its replacement without erasing it); and **temporal
  anchoring** (calendar-aware tense, re-derived live, not frozen at write time).
- **MCP server** (SSE transport, widest client compatibility) exposing six
  tools: `remember`, `recall`, `recall_with_associations`, `supersede`,
  `remember_json`, `recall_json`. Point any MCP-capable agent at
  `http://<host>:8080/sse` — no glue code.
- **JSON fold / unfold** — `remember_json` folds a whole JSON blob into
  individually recallable memories (one per leaf, keyed by dotted path);
  `recall_json` reassembles the original object with types intact.
- **Self-organising consolidation loop** — edge compaction and decay run on
  their own inside the container, so the graph keeps tidying itself.
- **Agent persona prompt** ([`AGENT_PROMPT.md`](AGENT_PROMPT.md)) — the
  integration step that turns *"the brain is plugged in"* into *"the agent
  thinks with it."*
- **Pre-loaded demo brain** (`ENGRAM_SEED_DEMO=1`) for an instant try-out, plus
  a container image and `docker-compose` quickstart.

[0.5.1]: https://github.com/gsn2dd/engram/releases/tag/v0.5.1
[0.5.0]: https://github.com/gsn2dd/engram/releases/tag/v0.5.0
[0.3.0]: https://github.com/gsn2dd/engram/releases/tag/v0.3.0
[0.2.0]: https://github.com/gsn2dd/engram/releases/tag/v0.2.0
[0.1.0]: https://github.com/gsn2dd/engram/releases/tag/v0.1.0
