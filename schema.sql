-- Engram — database schema
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
    embedding     vector(768),                   -- semantic position
    -- Which model produced `embedding`. Vectors from different models are the
    -- same length and NOT comparable, so a brain must know its own provenance;
    -- see path_memory/embed.py assert_brain_compatible().
    embedding_model text,
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

-- Everything below is idempotent, so re-running this file upgrades a brain
-- created before these existed. Fresh installs get the columns from the
-- CREATE TABLE above where they are declared there.
ALTER TABLE memories ADD COLUMN IF NOT EXISTS embedding_model text;

-- PROVENANCE. Where a memory came from, and whether it has been cleaned. An
-- engine that only records what a memory says cannot answer "who told us
-- this, in which session, and has it been redacted?" — which is the difference
-- between a brain that fills up by itself and one a human has to hand-feed.
ALTER TABLE memories ADD COLUMN IF NOT EXISTS tier text DEFAULT 'curated';
ALTER TABLE memories ADD COLUMN IF NOT EXISTS contributor       text;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS source_system     text;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS session_id        text;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS source_uri        text;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS content_hash      text;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS redaction_version text;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS metadata_json     jsonb;

-- Ingest idempotency. The extension re-posts on retry and rescans pages, so
-- the same exchange genuinely arrives twice. A unique index makes the DATABASE
-- refuse the duplicate: a pre-flight SELECT loses that race every time,
-- because the retry arrives while the first request is still embedding and
-- sees nothing committed. Measured, not theorised — the first version of the
-- ingest endpoint stored a duplicate on exactly that path.
ALTER TABLE memories ADD COLUMN IF NOT EXISTS exchange_id text;
CREATE UNIQUE INDEX IF NOT EXISTS memories_exchange_uniq
    ON memories(exchange_id) WHERE exchange_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS memories_tier_idx ON memories(tier);

-- PROJECT IDENTITY. `project` was free text, so the same project accumulated
-- several spellings and every scoped recall silently returned half the corpus.
-- The registry is only sound if all three halves exist: normalise on write,
-- normalise on read, and backfill once. Any one alone leaks.
CREATE TABLE IF NOT EXISTS projects (
    slug         text PRIMARY KEY,
    display_name text,
    notes        text,
    created_at   timestamptz DEFAULT now()
);

-- Aliases are kept forever rather than deleted: old notes, scripts and human
-- habit keep using them, and a resolvable alias beats a miss.
CREATE TABLE IF NOT EXISTS project_aliases (
    alias      text PRIMARY KEY,
    canonical  text NOT NULL REFERENCES projects(slug) ON UPDATE CASCADE,
    created_at timestamptz DEFAULT now()
);

-- A memory may concern several projects. It is NEVER duplicated to achieve
-- that: three copies would carry three separate access_counts, weights and
-- edge sets, so retrieval evidence splits three ways and none of them ever
-- gets strong — attacking the exact mechanism this engine runs on. One row,
-- many links. If a CLAIM differs per project, those were always two memories.
CREATE TABLE IF NOT EXISTS memory_projects (
    memory_id  integer NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    project    text    NOT NULL REFERENCES projects(slug) ON UPDATE CASCADE,
    -- primary    : what it is ABOUT (mirrors memories.project, the fast path)
    -- origin     : what we were working on when it was found
    -- applies-to : another project the finding governs
    -- mentions   : named, but not governed by it
    role       text NOT NULL DEFAULT 'primary'
               CHECK (role IN ('primary','origin','applies-to','mentions')),
    confidence real,
    created_at timestamptz DEFAULT now(),
    PRIMARY KEY (memory_id, project)
);

CREATE INDEX IF NOT EXISTS memory_projects_project_role_idx
    ON memory_projects(project, role);

-- RESOLVED BOUNDARIES. `collapse` does the expensive work of separating the
-- relevance field into keep and drop, and used to discard the result. Each row
-- here is one resolution kept: a named doorway with the set it resolved to.
--
-- The point is the reversal. A query embeds, matches a centroid HERE (a scan of
-- doorways, not of the corpus), and the doorway yields its members by exact id.
-- Fuzzy on the way in, exact on the way out — and the name is a handle a human
-- or agent can use directly, without a vector at all.
--
-- `key` is derived from the member set, not assigned, so the same cluster
-- re-resolving lands on its own key and increments query_count instead of
-- creating a rival. A doorway that keeps re-forming is thereby visibly
-- load-bearing, the same way a well-used edge is.
CREATE TABLE IF NOT EXISTS collapse_keys (
    key           text PRIMARY KEY,      -- sha256 of the sorted member ids
    name          text,                  -- generated handle; a label, not an authority
    gist          text,
    centroid      vector(768),           -- mean of member embeddings
    member_ids    integer[] NOT NULL,
    cut_gap       real,                  -- how cleanly the field separated
    example_query text,
    query_count   integer     DEFAULT 1, -- times this doorway has been resolved or used
    formed_at     timestamptz DEFAULT now(),
    last_used     timestamptz DEFAULT now(),
    -- Set by consolidation when memories arrive after formed_at. Stale is not
    -- wrong, it is INCOMPLETE: the members still cohere, something newer may
    -- also belong. Re-resolving is the offline pass's job.
    stale         boolean     DEFAULT false
);

CREATE INDEX IF NOT EXISTS collapse_keys_name_idx ON collapse_keys(name);
CREATE INDEX IF NOT EXISTS collapse_keys_centroid_idx
    ON collapse_keys USING hnsw (centroid vector_cosine_ops);

-- RECALL EVENTS — the difference between what was SHOWN and what was USED.
--
-- Until 2026-08-16 this engine could not tell those apart, and it strengthened
-- on the wrong one. Every recall bumped weight and laid down edges for every
-- result returned, so the use-built graph was learning WHAT GOT SHOWN. Paired
-- with an always-on prompt-time recall hook that is a self-confirming loop:
-- whatever the ranker surfaces gets strengthened, which makes the ranker
-- surface it again.
--
-- The distinction is not academic. Hand a model the provably correct memory and
-- it still may ignore it, misread it, or be confused by it — so "this was
-- returned" is evidence about the RANKER, while "this was used" is evidence
-- about the MEMORY. Only the second is worth learning from.
--
-- One row per recall. `shown` is written at recall time; `used` is filled in
-- afterwards, by whatever can actually tell — an agent reporting explicitly, or
-- an offline pass reading the conversation that followed. Attribution is
-- therefore allowed to be LATE and allowed to be ABSENT: a NULL `used` means
-- nobody has judged this event yet, which is different from an empty array
-- meaning nothing shown was used.
CREATE TABLE IF NOT EXISTS recall_events (
    id            bigserial PRIMARY KEY,
    created_at    timestamptz DEFAULT now(),
    query         text,
    project       text,
    session_id    text,                    -- groups events within one conversation
    source        text,                    -- hook | mcp | cli | bench | ...
    -- [{"id":123,"rank":1,"score":0.71}, ...] — rank and score are kept because
    -- "the answer was there but ranked 9th" is a different failure from "it was
    -- never returned", and the two need different fixes.
    shown         jsonb NOT NULL,
    used          jsonb,                   -- [123, ...]; NULL = not yet judged
    attributed_at timestamptz,
    attribution   text                     -- explicit | citation | model | ...
);
CREATE INDEX IF NOT EXISTS recall_events_created_idx ON recall_events(created_at);
CREATE INDEX IF NOT EXISTS recall_events_session_idx ON recall_events(session_id);
-- The attributor's work queue: events nobody has judged yet.
CREATE INDEX IF NOT EXISTS recall_events_unattributed_idx
    ON recall_events(created_at) WHERE used IS NULL;


-- TOPICS — sub-classification inside a project.
--
-- `project` answers "which body of work"; a topic answers "which THING inside
-- it". A conversation about building the Banbury hub is project=worldtownguide,
-- topic=banbury — so recall can be narrowed to Banbury without inventing a
-- separate project for every town.
--
-- Topics are DISCOVERED, not enumerated. Two sources, both the same underlying
-- move (cluster, then name):
--   promoted  — a collapse doorway that keeps re-forming. Repeated resolution
--               IS the evidence that a set is a durable thing rather than one
--               query's accident, so usage promotes it.
--   discovered— the dreaming pass clustering a project's memories offline,
--               including transcripts, where a subject appears in conversation
--               long before anyone writes a curated memory about it.
CREATE TABLE IF NOT EXISTS topics (
    project      text NOT NULL REFERENCES projects(slug) ON UPDATE CASCADE,
    slug         text NOT NULL,
    label        text,
    gist         text,
    centroid     vector(768),
    source       text DEFAULT 'discovered'
                 CHECK (source IN ('promoted','discovered','manual')),
    member_count integer     DEFAULT 0,
    created_at   timestamptz DEFAULT now(),
    last_seen    timestamptz DEFAULT now(),
    PRIMARY KEY (project, slug)
);

CREATE INDEX IF NOT EXISTS topics_centroid_idx
    ON topics USING hnsw (centroid vector_cosine_ops);

-- Many-to-many on purpose: one memory can be about Banbury AND about
-- sponsorship. Forcing a single topic would make the tag a worse version of
-- the project column rather than a finer one.
CREATE TABLE IF NOT EXISTS memory_topics (
    memory_id   integer NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    project     text    NOT NULL,
    slug        text    NOT NULL,
    confidence  real,
    assigned_by text    DEFAULT 'dream',
    created_at  timestamptz DEFAULT now(),
    PRIMARY KEY (memory_id, project, slug),
    FOREIGN KEY (project, slug) REFERENCES topics(project, slug) ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS memory_topics_topic_idx ON memory_topics(project, slug);

-- Derived memories are marked so recall can tell a summary from a thing that
-- actually happened. `origin='recycle'` already existed and means exactly this;
-- these columns record WHAT it was derived from, so a summary is auditable back
-- to its sources rather than being an unattributable assertion.
ALTER TABLE memories ADD COLUMN IF NOT EXISTS derived_from integer[];
ALTER TABLE memories ADD COLUMN IF NOT EXISTS derived_depth integer DEFAULT 0;
CREATE INDEX IF NOT EXISTS memories_origin_recycle_idx
    ON memories(origin) WHERE origin = 'recycle';

-- Postgres has no ADD CONSTRAINT IF NOT EXISTS, so a bare ALTER here made the
-- whole file fail on its second run — while the comments above promise that
-- re-running it upgrades an existing brain. That is the documented upgrade
-- path, and it aborted at this line before reaching anything after it.
DO $$ BEGIN
    ALTER TABLE memories ADD CONSTRAINT memories_node_key_uniq UNIQUE (node_key);
EXCEPTION
    WHEN duplicate_table THEN NULL;
    WHEN duplicate_object THEN NULL;
END $$;
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
-- Additional features:
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
