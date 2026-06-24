# Engram
### An open-source memory brain your AI agent attaches to

*100% coded by AI (Claude) · from human inspiration (David Dand)*

---

## What this is

**Engram** is an open-source memory *brain* for AI agents — not another vector store. You run it as a container, and your agent attaches to it as its persistent memory. It's built on a few ideas most "memory" libraries don't have:

1. A memory is stored from **multiple perspectives at once** (a fan-out of lenses — its themes, the questions it answers, the different names it goes by), so it's findable from angles its literal text would never match.
2. The act of retrieving knowledge **changes** the knowledge — connection weights between memories emerge from retrieval history, not from training data, and spreading activation surfaces what's linked *by use*, not just by meaning.
3. Structured knowledge can be folded into a seed — a compact, weighted, semantically-indexed object an agent can consume directly.

It ships as two components:

| Component | What it does |
|-----------|-------------|
| **Model Seed** | Folds structured knowledge about any entity into a grounded, source-cited object an agent can consume |
| **Path Memory** | A self-organising memory layer where connection weights emerge from use, not design |

Together they form a knowledge system that learns what matters by watching what gets used.

---

## Using Engram as an agent brain

**The objective:** give an AI agent a *persistent, self-organising memory* that lives outside the model — so it remembers across sessions, gets *better at recall the more it's used*, and can surface the right memory from many angles, not just the exact words it was stored under.

**How an agent uses it** — three verbs:

- **Remember** — hand Engram something learned (a fact, an event, a decision). It files the memory from several perspectives at once (its theme, the questions it answers, the different names it goes by) and classifies it automatically — so it's findable later from angles its literal wording would miss.
- **Recall** — ask in natural language. Engram returns the best matches *and* what's associated with them *by use* (spreading activation), not just by keyword. Every recall quietly strengthens the paths it travels.
- **Forget** — nothing is curated by hand. Memories that stop being recalled decay and eventually archive themselves. The brain keeps what earns its keep.

> **A note on cost:** generating the fan-out perspectives means each `Memory.save()` makes a few small LLM calls (the lenses + classification). That's on by default because it's what makes recall feel uncanny — but for bulk imports or cost-sensitive use, pass `perspectives=False` to save the literal memory only.

The attach point is an **MCP endpoint** (SSE transport, for the widest client compatibility): spin up the container and point any MCP-capable agent (OpenClaw, Claude Desktop, your own) at `http://<host>:8080/sse` — it has a brain, no glue code. The server exposes six tools — `remember`, `recall`, `recall_with_associations`, `supersede`, `remember_json` (fold a whole JSON blob into recallable memories, one per leaf), and `recall_json` (reassemble a folded blob back into one object) — backed by everything above. Run one brain per agent, or share one across a fleet. *(You can also drive it directly via the Python API / CLI, shown below.)*

### Making your agent actually *use* it

Attaching the endpoint makes the tools *available* — but a model won't reflexively reach for memory unless you tell it to. **This is the single most important integration step:** add a short directive to your agent's **system prompt / persona**, so recall-and-remember becomes a habit rather than something it only does when asked:

> *You have a persistent memory (engram). Before you answer, `recall` relevant context. When you learn something worth keeping — a fact, a decision, a preference — `remember` it. Scope memories to the current project where that helps.*

That one instruction is the difference between *"the brain is plugged in"* and *"the agent thinks with it."* The tool descriptions steer **how** to call each tool; this steers **when**. (In OpenClaw, add it to the agent's persona; in Claude Desktop, to the system prompt; in your own agent, to its system message.)

**A complete, ready-to-paste version lives in [`AGENT_PROMPT.md`](AGENT_PROMPT.md)** — copy it straight into your agent's persona and adjust the voice to taste. It covers all five tools (recall-first, remember-what-matters, project scoping, JSON folding, supersede).

### Handing engram JSON — and getting it back

You can give engram JSON and read it back, two ways depending on what you want:

- **Query its *contents*.** `remember_json` folds a JSON blob into one memory per
  leaf, keyed by its path (`business.hours.sat`). Then `recall` finds the right
  pieces by meaning — *"what are the weekend hours?"* surfaces the `sat` leaf
  even with no shared keywords. Use this when you want to *ask questions* about
  the data.

  ```bash
  # agent side (MCP): remember_json('{"business":{"hours":{"sat":"10am-4pm"}}}', project="acme")
  # query a piece:    recall("weekend opening time", project="acme")  ->  business.hours.sat: 10am-4pm
  # get it all back:  recall_json(project="acme")  ->  {"business": {"hours": {"sat": "10am-4pm"}}}
  ```

  `recall_json` is the inverse of `remember_json` — it gathers the folded leaves
  for a scope and **reassembles the whole object, with types intact** (strings,
  numbers, bools, null, nested lists). So folding is symmetric: blob in, blob out.

- **Round-trip the *whole blob* without folding.** If you don't need the contents
  searchable piece-by-piece, just store the JSON as a memory body and `recall`
  hands it back intact:

  ```bash
  # remember(subject="customer 4821 record", body="<the JSON string>", project="acme")
  # recall("customer 4821")  ->  body is the JSON, returned whole
  ```

The first makes the data **searchable by meaning** *and* reassemblable as a
whole; the second is the quick path when you only ever want the object back as a
unit. Use whichever the task needs.

### Creativity — structured serendipity

`recall` takes an optional **`creativity`** (0–1). At `0` you get the precise
best matches. Turn it up and engram swaps a growing share of the *tail* of the
results for **near-miss memories** — semantically adjacent, but not the obvious
answer — to nudge the agent toward a connection the literal query would never
surface. It always keeps the real top hit; it just mixes in sparks.

```python
recall("how do we keep users logged in", creativity=0)     # -> the auth decision
recall("how do we keep users logged in", creativity=0.8)   # -> auth decision + the founder, the office, the caching debate
```

The point is the painter's happy accident, or a useful mutation: a small,
*aimed* detour is where inspiration comes from. So the noise isn't random —
random is just irrelevant — it's the **adjacent possible**, drawn from the
second ring of the embedding space. Sparks are flagged `serendipity=true`, so
the agent treats them as prompts rather than facts, and they never strengthen
the use-built graph. Almost every memory system chases precision; this is the
dial for the opposite — and it's grounded in how minds actually generate ideas
(divergent thinking, incubation, the way dreams recombine distant memories).

---

## Where it comes from

Engram is **100% coded by AI** (Claude) — every line of it — from **human inspiration and direction** (David Dand). The human brought the vision and the ideas; the AI wrote the code. Two sources shaped that vision:

- **Tony Buzan's work on the mind** — mind maps and *radiant thinking*: the idea that memory and understanding are associative and branching, not linear lists. Engram's association graph and fan-out perspectives are that idea turned into software — knowledge that radiates outward by connection, and strengthens along the routes you actually travel.
- **The lived human experience of having memories** — that we recall by association and by theme; that the same thing has different names depending on who's remembering it; and that memories grow stronger with use and fade when neglected. Engram tries to behave the way memory actually *feels*, not the way a database works.

---

## Quickstart

Engram is **one self-contained container** — Postgres+pgvector, the app, and the
schema baked into a single image. You bring your own `OPENAI_API_KEY` and
`ANTHROPIC_API_KEY` (used for embeddings, classification, and lens generation);
the container never ships with keys.

**Run the pre-built image** (available once a release is published to GHCR):

```bash
cp .env.example .env    # add your OPENAI_API_KEY and ANTHROPIC_API_KEY
docker run -p 8080:8080 -v engram_pgdata:/var/lib/postgresql/data --env-file .env ghcr.io/gsn2dd/engram
```

`-p 8080:8080` publishes the MCP endpoint (attach agents at `http://localhost:8080/sse`); `-v engram_pgdata:…` keeps the brain across restarts.

**Or build from source** (for development / contributing):

```bash
git clone https://github.com/gsn2dd/engram
cd engram
cp .env.example .env    # fill in your OPENAI_API_KEY and ANTHROPIC_API_KEY
docker compose up
```

That's it — Postgres initialises with the schema on first boot, and the brain is
live inside the container. On first boot it also seeds a small **demo brain** (a
fictional startup's notes) so recall works immediately — try:

```bash
docker compose exec engram python3 cli/pm.py recall "how do we keep users logged in"
# -> surfaces the JWT auth decision, with no words in common
```

Set `ENGRAM_SEED_DEMO=0` for a clean, empty brain in a real deployment.

Talk to it with the CLI / Python library against the running container:

```bash
docker compose exec engram python3 cli/pm.py save "Auth decision" "We use short-lived JWTs." --person my-project
docker compose exec engram python3 cli/pm.py recall "how do we keep users logged in"
```

---

## The core insight

Most AI memory systems are retrieval-only. You put things in, you get things out. The weights are fixed.

Engram is different: **the observer changes the memory**.

```
JSON Layer 1:  [A] ----w=0.8---- [B]
                |                  |
              w=0.1             w=0.6
                |                  |
JSON Layer 2:  [C] ----w=0.0---- [D]
                         |
                       w=0.9
                         |
JSON Layer 3:           [E]
```

Every retrieval that passes through a path strengthens it. Every path never taken fades. The system trains itself through use — there is no separate training phase.

The JSON structure defines the possible paths. Retrieval history decides which ones survive.

---

## How it works

### The seed

A **model seed** is a structured knowledge object — not a document, not a scraped summary. It contains:

- Verified facts with source citations and confidence scores
- Semantic context (cultural, geographic, linguistic signals)
- Fame anchors and narrative scaffolds
- Public contribution slots and update/repair metadata
- Vector slots for retrieval (768-dimensional embeddings)

The seed is the 2D projection of a multi-dimensional knowledge object. The JSON is the shadow. The real structure lives in the embedding space.

### The layers

Nested JSON is not flat. Each layer of nesting is a layer of the knowledge structure:

```
Layer 1 (top-level keys)  →  embed each element  →  768D vector
Layer 2 (nested objects)  →  embed each element  →  768D vector
Layer N (leaf values)     →  embed each element  →  768D vector
```

Connection weight between any two elements across layers:

```
weight(A → B) = accumulated retrieval signal through A and B
```

This is Hebbian learning at the data-structure level: **connections that fire together wire together**. But the training signal is not gradient descent — it is the observer.

### The observer

When a memory is retrieved:

```python
UPDATE memories SET
  access_count = access_count + 1,
  weight = weight + (1.0 / (access_count + 2)),  # diminishing returns
  last_accessed = now()
WHERE id = %s
```

- Default weight: `0`
- First retrieval: `+0.50`
- Second: `+0.33`
- Third: `+0.25`
- Weight accumulates. Importance emerges from use, not assignment.

### Noun routing

Every memory is auto-classified on save:

| Type | What it covers |
|------|---------------|
| `person` | A human being |
| `place` | A geographic location |
| `project` | An initiative, product, codebase, or ongoing work |
| `thing` | An idea, concept, or anything else |

Classification is automatic — the system inspects the entity and content and decides. No manual tagging.

### Temporal decay and erasure

Memories never retrieved age out:

```python
# Decay weight over time for unaccessed memories
UPDATE memories SET weight = weight * 0.95
WHERE last_accessed < now() - interval '7 days'

# Archive if weight falls below threshold
UPDATE memories SET archived = true
WHERE weight < 0.01
```

The system forgets what is not needed. The most-travelled paths become highways. The rest become dirt tracks, and eventually disappear.

**This runs on its own.** The container executes a **consolidation pass on a loop** (default hourly — set `ENGRAM_CONSOLIDATE_INTERVAL` in seconds): it compacts raw co-recall edges into the path graph that spreading-activation reads, decays unused node and edge weights, and archives what's faded. Trigger it by hand any time with `pm consolidate`. Weights strengthen on every recall regardless, but *this* pass is what lets the graph reorganise itself over time — so it ships on by default.

### Temporal anchoring — a different axis from decay

Decay answers "how much should we still trust this, given how long it's gone
unused." It does not answer "what tense should this be read in, right now."
A claim like *"next year's Olympics"* doesn't go stale because nobody asked
about it for a while — it goes stale because the calendar moved past the
Games' actual dates, regardless of how often the memory was recalled.

Memories can carry an optional calendar anchor:

```python
Memory.save(
    subject="olympics-2028", body="Los Angeles will host the 2028 Summer Olympics...",
    person="los-angeles",
    temporal_anchor_start="2028-07-14", temporal_anchor_end="2028-07-30",
)
```

`recall()` re-derives a live `temporal_status` (`upcoming` / `current` /
`past`) against today's date on every call — never frozen at write time —
and `format_for_prompt()` surfaces it as a tense hint so the writer doesn't
copy stale wording verbatim once an anchor's status has moved on. Run
`pm temporal-sweep` to list every calendar-anchored memory and its current
status — useful before a recycle pass, to catch claims whose frozen prose no
longer matches reality.

---

## The remembered path

A path through the JSON layers — activated repeatedly by retrieval — becomes a piece of knowledge in itself. Not the nodes. The route between them.

This is what makes Engram different from a vector database:

| Vector DB | Engram |
|-----------|----------------|
| Retrieval finds nearest neighbours | Retrieval strengthens connections |
| Weights are static | Weights emerge from use |
| No forgetting | Temporal decay removes unused paths |
| Flat similarity search | Layered structure with directional paths |
| Training phase separate from operation | Every retrieval is a training step |

---

## Storage

```sql
CREATE TABLE memories (
  id          serial PRIMARY KEY,
  person      text,                    -- entity: person, place, project name, or NULL
  subject     text,                    -- short subject label
  body        text,                    -- full content
  noun_type   text DEFAULT 'thing',    -- person | place | project | thing
  embedding   vector(768),             -- semantic position in 768D space
  access_count integer DEFAULT 0,      -- singleton retrieval counter
  weight      float DEFAULT 0.0,       -- accumulated observer weight
  last_accessed timestamptz,           -- for aging/decay
  archived    boolean DEFAULT false,   -- soft-deleted memories
  created_at  timestamptz DEFAULT now()
);

CREATE INDEX ON memories USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON memories USING gin (person gin_trgm_ops);
CREATE INDEX ON memories USING gin (subject gin_trgm_ops);
```

Requires: PostgreSQL + pgvector extension.

---

## Semantic recall

```bash
# Find memories by meaning, not keyword
python3 cli/pm.py recall "how do we keep users logged in"

# Filter by entity
python3 cli/pm.py recall "the caching decision" --person my-project

# Filter by noun type
python3 cli/pm.py recall "who knows the deploy process" --noun person

# Limit results
python3 cli/pm.py recall "auth approach" --limit 3
```

Every recall updates the observer weights automatically.

---

## The Model Seed component

The seed generator turns any structured data source into a grounded intelligence packet deployable to AI systems:

```
Raw data + local contributions
  → fold (research debt + public contribution engines)
    → weighted knowledge object (the seed)
      → embed → store in the brain
        → self-host, or build your own publishing layer on top
```

**Seed consumers** (what you can build with a seed):
- Agents that need grounded, persistent memory about specific entities
- Recommendation and ranking engines
- Domain-specific assistants and copilots
- RAG pipelines that want weighted, self-organising recall
- QA and repair pipelines

The seed generator is free and open source. [WorldTownGuide](https://worldtownguide.com) is one production deployment built on this engine — a useful reference, not a requirement.

---

## Open source

The seed generator and Path Memory layer are free and open source.

Fork it. Run it. Generate seeds for any entity — cities, projects, people, ideas. Build your own knowledge layer. The weights that emerge from your usage are yours.

```bash
git clone https://github.com/gsn2dd/engram
```

The weights that emerge from your usage are yours.

---

## What this is not

- Not a pretrained LLM
- Not a vector database with static weights
- Not a scraper or summary generator
- Not a black box — every connection weight is inspectable, every path is traceable

---

## Status — and an honest ask

Active development, and **genuinely experimental.** The core works, but Engram has **not yet been tested in long trials.** The open question we most want help with:

> **How does memory retention and retrieval hold up over time?**

As the graph grows to thousands of memories and the decay-and-strengthening loop runs for weeks and months, does the *right* memory stay easy to find — and does the *unused* stuff fade cleanly — or does recall slowly drift? We don't yet know, and that's exactly the thing a real brain has to get right.

**If you run it, we'd genuinely like to hear back:** what got harder to find, what surfaced that shouldn't have, how recall *felt* after a month of real use. That long-horizon feedback is the most valuable thing you can give the project — open an issue and tell us what your brain remembered and what it forgot.

Path Memory layer: operational. Model Seed generator: operational. Open-source packaging: in progress.

**100% coded by AI, with human inspiration.** Conceived and directed by [David Dand](https://worldtownguide.com/about) (gsn2dd); every line of code written by Claude.
