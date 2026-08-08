# Changelog

All notable changes to Engram are recorded here. Engram uses
[semantic versioning](https://semver.org/); each version maps to a git tag and a
published container image.

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

[0.3.0]: https://github.com/gsn2dd/engram/releases/tag/v0.3.0
[0.2.0]: https://github.com/gsn2dd/engram/releases/tag/v0.2.0
[0.1.0]: https://github.com/gsn2dd/engram/releases/tag/v0.1.0
