# Convergence plan: one engine, two names

**Status:** plan, not started. Written 2026-08-08.

## The situation

There are two memory systems on this machine that were supposed to be one:

| | mindspace | engram |
|---|---|---|
| What it is | the private brain, in daily use | the open-source product |
| Where | host PostgreSQL 16.12, pgvector 0.8.0 | container, PostgreSQL 16.14, pgvector 0.8.3 |
| Contents | 3,267 memories | 1 memory |
| Embeddings | `gemini-embedding-001`, 768d | pluggable since 2026-08-07, 768d |

They share a lineage: engram is the merge of mindspace (free-form agent memory)
and wtg-path-memory (structured knowledge), renamed on 2026-06-24, with the
best-of-both port landing the same day.

## How far apart they actually are

Diffed 2026-08-08:

- **23 columns shared** on `memories`
- **engram has 0 columns mindspace lacks**
- **mindspace has 9 engram lacks:** `tier`, `contributor`, `source_system`,
  `session_id`, `exchange_id`, `source_uri`, `content_hash`,
  `redaction_version`, `metadata_json`

Engram's schema is a strict **subset** of mindspace's. The association
machinery — `memory_entities`, `memory_links`, `memory_perspectives`,
`path_edge_summary`, `seeds` — is already identical on both sides.

So they did not diverge on architecture. They diverged on **provenance**.
mindspace grew an ingestion layer because it is used; engram never did because
it holds one memory.

## Why this is cheap now, and was not a week ago

All 3,267 mindspace vectors are `gemini-embedding-001` at 768 dimensions.
Since the embedding provider became pluggable, engram produces exactly that —
same model, same dimensions, same request shape.

**The vectors are directly transferable. No re-embedding, no cost, no loss of
the association weights.** Before that change this migration meant re-embedding
the whole corpus through OpenAI and rebuilding the graph from scratch.

## Direction of travel

**engram is the engine.** It is packaged, tested, containerised, has an MCP
interface, and is published. mindspace becomes an engram *instance*, not a
parallel codebase.

**Converge the schema and the code. Leave the data where it is.**

This is the part worth being deliberate about. The instinct is "move mindspace
into the engram container", but that is a risky data move solving nothing: a
large number of cron jobs, ingestion scripts and tools point at the host
database. Converging means both sides run *the same schema and the same engine
code* — not that the bytes relocate. Containerise later, if there is ever a
reason.

## Phase 1 — engram becomes the superset (no data moves)

1. Add the 9 provenance columns to `schema.sql`, with the idempotent
   `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` pattern already used for
   `embedding_model`.
2. Reconcile the duplicate dedup designs: engram's `captures` table and
   mindspace's `exchange_id` column solve the same problem twice. Keep the
   column plus a unique index; drop the table. It is younger and has no data.
3. Port the redaction layer (`mindspace/redaction.py`) into the engine. Engram
   currently scrubs secrets only at the ingest endpoint; it belongs at the
   `Memory.save` boundary so every write path gets it.
4. Add `tier` handling to recall. mindspace defaults to `curated` and keeps
   transcripts out of the path graph — engram has no equivalent, so a captured
   transcript would pollute association weights.

## Phase 2 — project identity (do this first, see below)

See "Multiple names for one project".

## Phase 3 — mindspace runs the engine

1. Upgrade the mindspace database in place to the converged schema.
2. Repoint `recall.py` / `embed_memory.py` at `path_memory` instead of their
   own implementations. They become thin CLIs over the engine.
3. Move the ingestion scripts (`ingest_transcripts.py`, `session_ingest.py`,
   `log_transcript.py`, `temporal.py`) into engram as an optional
   `ingestion/` module. **This is the half of mindspace the open-source
   product most needs** — it is what makes a brain fill up by itself, and
   neither OpenClaw nor Hermes Agent has it.
4. Delete the duplicated logic from `~/mindspace`, leaving config and CLIs.

## What to leave behind deliberately

- **`case_documents`** (mindspace) — the legal-case RAG application's table.
  Application data, not a memory-engine concern. It stays out of the engine.
- **`recall_self_test_log`** (mindspace) — arguably belongs in the engine as
  the recall-health diagnostic on the roadmap, but only once that feature is
  real. Do not port a table for a feature that does not exist.
- **`captures`** (engram) — superseded by `exchange_id`, per Phase 1.

## Multiple names for one project

`project` is free text, so the same project exists under several spellings:

```
wtg             2009      pirate-games    20
worldtownguide   118      pirate_games     1
```

Every unscoped recall treats these as different projects, and every scoped
recall silently misses the other spelling. This gets worse with every memory
written, so it is the one part of this plan worth doing **now** rather than
at migration time.

**Fix: a canonical project registry with aliases.**

```sql
CREATE TABLE IF NOT EXISTS projects (
    slug         text PRIMARY KEY,      -- canonical
    display_name text,
    created_at   timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS project_aliases (
    alias     text PRIMARY KEY,         -- any spelling ever seen
    canonical text NOT NULL REFERENCES projects(slug)
);
```

Three parts, and all three are needed — the table alone will not hold:

1. **Normalise on write.** `Memory.save` resolves the incoming project through
   `project_aliases` before storing. New spellings can never accumulate again.
2. **Normalise on read.** `recall(project=...)` resolves the same way, so
   asking for either spelling returns everything.
3. **Backfill once.** Rewrite existing rows to the canonical slug, keeping the
   old spelling as an alias so nothing is orphaned.

Unknown project on write: register it rather than reject it — a memory must
never be lost to a typo — but log it, so a near-duplicate of an existing slug
gets noticed while it is still one row rather than two thousand.

**Open decision — which spelling is canonical for WorldTownGuide?** `wtg` has
the volume (2009 rows); `worldtownguide` matches the repository and the domain.
This is a naming call, and picking wrong is what created the problem, so it
needs an explicit answer rather than a guess.

## Harness integration — shipping the "don't forget me" half

Two things were built on 2026-08-08 against mindspace, after an engram session
drifted into unrelated work because recall was unlabelled:

- a `UserPromptSubmit` hook that injects recall tagged with each memory's
  project, states the active project, and flags off-project hits
- a `/project-checkin` skill: active project, its most recent memories, any
  corrections or supersessions, and repo branch/commit/dirty state

**These should ship with engram**, as `integrations/claude-code/`, rewritten to
talk to engram's MCP endpoint instead of mindspace's psql and `recall.py`.

The reasoning is a product argument, not a tidiness one. Engram's own
`AGENT_PROMPT.md` states the problem correctly — "a model won't use a brain
unless its persona tells it to" — but a persona instruction is the weakest
possible fix, because it is a request a model can drop under context pressure.
That is not hypothetical: we published a memory brain and then did not use it
for six weeks.

Harness-level injection cannot be forgotten, because the model is not the one
doing the remembering. **"Engram installs itself into your agent"** is a
differentiator neither OpenClaw nor Hermes Agent has — both also fall back on
persona instructions for memory usage.

## Sequencing, honestly

Phase 2 (project identity) is worth doing now: it is small, and the cost of
delay compounds with every memory written.

Phases 1 and 3 are a day or two of careful work on something that does not yet
earn. The standing constraint is that WorldTownGuide must become self-funding
first. Do the migration when engram has a reason to be the live brain — in
practice, when the Marketplace listing clears, since that is weeks away anyway.

Write the plan down now, while the schema diff is fresh. Execute it when it pays.
