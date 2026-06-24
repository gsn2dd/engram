-- WTG Path Memory — database schema
-- Requires PostgreSQL 14+ with pgvector extension

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS memories (
    id            serial PRIMARY KEY,
    -- Entity / ownership
    person        text,                          -- primary entity: geonameid, slug, or name
    -- Content
    subject       text NOT NULL,                 -- short human label
    body          text NOT NULL,                 -- full claim / fact text (claim_text)
    source_links  jsonb DEFAULT '[]'::jsonb,     -- [{url, title, accessed_at}]
    -- Classification
    noun_type     text DEFAULT 'thing'           -- legacy: person|place|project|thing
                  CHECK (noun_type IN ('person','place','project','thing')),
    node_type     text,                          -- production: anchor|section|fact|source|sentiment|faq|image_alt
    node_key      text,                           -- stable id e.g. "2643743|night_transport|fact_a1b2"
    origin        text DEFAULT 'contribution'    -- contribution|discovery|recycle
                  CHECK (origin IN ('contribution','discovery','recycle')),
    -- Vector
    embedding     vector(768),                   -- semantic position (text-embedding-3-small)
    -- Observer weight
    access_count  integer DEFAULT 0,             -- total retrievals
    success_count integer DEFAULT 0,             -- retrievals that led to a published page
    fail_count    integer DEFAULT 0,             -- retrievals where page failed QC
    weight        float   DEFAULT 0.0,           -- accumulated observer weight
    last_accessed timestamptz,                   -- for aging / decay
    -- Lifecycle
    archived      boolean DEFAULT false,
    expires_at    timestamptz,                   -- hard expiry (NULL = never)
    created_at    timestamptz DEFAULT now(),
    -- Temporal anchor — for claims whose correct tense depends on the calendar,
    -- not on how long ago the row was written. e.g. "next year's Olympics" is
    -- upcoming, current, or past depending on today's date vs the Games' own
    -- dates, regardless of when this row was saved or last accessed.
    -- NULL on both = not a calendar-anchored claim (most rows).
    temporal_anchor_start date,                   -- e.g. event/validity start date
    temporal_anchor_end   date                    -- defaults to anchor_start if unset
);

ALTER TABLE memories ADD CONSTRAINT memories_node_key_uniq UNIQUE (node_key);
CREATE INDEX IF NOT EXISTS memories_node_type_idx ON memories(node_type) WHERE node_type IS NOT NULL;
CREATE INDEX IF NOT EXISTS memories_origin_idx    ON memories(origin);

-- Semantic search index (cosine similarity)
CREATE INDEX IF NOT EXISTS memories_embedding_idx
    ON memories USING hnsw (embedding vector_cosine_ops);

-- Fuzzy text search on entity and subject
CREATE INDEX IF NOT EXISTS memories_person_trgm_idx
    ON memories USING gin (person gin_trgm_ops);
CREATE INDEX IF NOT EXISTS memories_subject_trgm_idx
    ON memories USING gin (subject gin_trgm_ops);

-- Partial index for active memories only
CREATE INDEX IF NOT EXISTS memories_active_idx
    ON memories (noun_type, last_accessed)
    WHERE archived = false;

-- Partial index for the temporal-retensing sweep — only rows that actually
-- carry a calendar anchor need to be scanned for stale tense.
CREATE INDEX IF NOT EXISTS memories_temporal_anchor_idx
    ON memories (temporal_anchor_start, temporal_anchor_end)
    WHERE archived = false AND temporal_anchor_start IS NOT NULL;

-- Multi-entity attachment — a memory can belong to several places
-- e.g. "The Landes forest" belongs to both Morcenx (2992380) and Onesse-Laharie (2990041)
-- person column stays as the primary entity; memory_entities holds all of them.
CREATE TABLE IF NOT EXISTS memory_entities (
    memory_id  integer NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    entity     text NOT NULL,
    PRIMARY KEY (memory_id, entity)
);
CREATE INDEX IF NOT EXISTS memory_entities_entity_idx ON memory_entities(entity);

-- Memory links — directed edges between memories, created by sequential recall
-- Each time memory B is surfaced after memory A, a link A→B is created or strengthened.
-- This records the chain of moments: coming from one memory to the next.
CREATE TABLE IF NOT EXISTS memory_links (
    id          serial PRIMARY KEY,
    from_id     integer REFERENCES memories(id),
    to_id       integer REFERENCES memories(id),
    link_type   text DEFAULT 'temporal_sequence',  -- temporal_sequence | semantic | manual
    strength    float DEFAULT 1.0,                 -- increases each time this transition recurs
    created_at  timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS memory_links_from_idx ON memory_links(from_id);
CREATE INDEX IF NOT EXISTS memory_links_to_idx   ON memory_links(to_id);

-- Compacted edge weights — the fast-read layer over memory_links' raw,
-- ever-growing footprint log (LSM-tree style). path_memory.links.compact_links()
-- folds raw footprints in here on a schedule and deletes what it folds, so
-- reads never have to count a growing pile of rows. One row per
-- (from_id, to_id, link_type); strength accumulates with the same
-- diminishing-returns shape as node weight, so a path used a lot keeps
-- gaining without running away unboundedly. decay_links() ages and prunes
-- this table the way aging.py ages and archives memories.
CREATE TABLE IF NOT EXISTS path_edge_summary (
    from_id     integer NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    to_id       integer NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    link_type   text NOT NULL DEFAULT 'temporal_sequence',
    strength    double precision NOT NULL DEFAULT 0,
    hop_count   integer NOT NULL DEFAULT 0,
    last_walked timestamptz,
    updated_at  timestamptz DEFAULT now(),
    PRIMARY KEY (from_id, to_id, link_type)
);
CREATE INDEX IF NOT EXISTS path_edge_summary_from_idx ON path_edge_summary(from_id);
CREATE INDEX IF NOT EXISTS path_edge_summary_to_idx   ON path_edge_summary(to_id);

-- Compiled seed artifacts — versioned, checksummed product objects
-- Each compile() run produces a new version; the latest is the canonical seed.
CREATE TABLE IF NOT EXISTS seeds (
    id          serial PRIMARY KEY,
    entity      text NOT NULL,           -- settlement slug or entity name
    version     integer NOT NULL DEFAULT 1,
    checksum    text,                    -- sha256 of payload for change detection
    payload     jsonb NOT NULL,          -- the full compiled seed object
    memory_ids  integer[],               -- which memories were compiled in
    compiled_at timestamptz DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS seeds_entity_version_idx ON seeds (entity, version);
CREATE INDEX IF NOT EXISTS seeds_entity_recent_idx ON seeds (entity, compiled_at DESC);

-- ─────────────────────────────────────────────────────────────────────────
-- Best-of-both additions — features that grew in the mindspace lineage:
--   project scoping · distillation (superseded) · fan-out perspectives
-- Written as idempotent migrations so they apply to fresh and existing installs.
-- ─────────────────────────────────────────────────────────────────────────

-- Distillation: when a memory is corrected/distilled, the old row stays fully
-- recallable but points to its replacement and ranks lower (recall multiplies
-- its score by SUPERSEDED_FACTOR). NULL = not superseded.
ALTER TABLE memories ADD COLUMN IF NOT EXISTS superseded_by integer;

-- Project scope: one brain can serve many projects without blurring recall.
-- NULL = unscoped. recall(project=...) filters to a single project.
ALTER TABLE memories ADD COLUMN IF NOT EXISTS project text;
CREATE INDEX IF NOT EXISTS memories_project_idx ON memories(project) WHERE project IS NOT NULL;

-- Fan-out perspective handles: each memory is also indexed under several
-- orthogonal lenses (its themes, the questions it answers, the names it goes
-- by), so it's findable from angles its literal wording would miss. One row
-- per (memory, lens); recall searches these alongside the literal embedding.
CREATE TABLE IF NOT EXISTS memory_perspectives (
    id          serial PRIMARY KEY,
    memory_id   integer NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    perspective text NOT NULL DEFAULT 'thematic',   -- thematic | questions | vantages | ...
    content     text,                               -- the generated lens text (inspectable)
    embedding   vector(768),
    created_at  timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS memory_perspectives_embedding_idx
    ON memory_perspectives USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS memory_perspectives_memid_idx
    ON memory_perspectives(memory_id);
