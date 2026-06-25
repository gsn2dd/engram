# Changelog

All notable changes to Engram are recorded here. Engram uses
[semantic versioning](https://semver.org/); each version maps to a git tag and a
published container image.

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
