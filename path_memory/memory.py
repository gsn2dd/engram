import hashlib
import re
import sys as _sys
from typing import Optional, List, Dict, Any
from .db import get_conn
from .embed import embed_one, active_model, assert_brain_compatible
from .classify import classify_noun
from .temporal import temporal_status

NODE_TYPES = ('anchor', 'section', 'fact', 'source', 'sentiment', 'faq', 'image_alt')
ORIGINS    = ('contribution', 'discovery', 'recycle')


def _make_node_key(entity: str, subject: str, body: str) -> str:
    """Stable deterministic node key: entity|subject_slug|hash6"""
    slug = re.sub(r'[^a-z0-9]+', '_', subject.lower())[:40].strip('_')
    h    = hashlib.sha256(f"{entity}|{subject}|{body}".encode()).hexdigest()[:6]
    return f"{entity}|{slug}|{h}"


class Memory:
    """
    Observation node — the core unit of Engram.

    Maps to Claudine's observation_node schema:
        person        → geonameid / entity
        body          → claim_text
        node_type     → anchor|section|fact|source|sentiment|faq|image_alt
        node_key      → stable deterministic id
        source_links  → [{url, title}]
        origin        → contribution|discovery|recycle
        weight        → usage/reliability signal
        success_count → incremented on successful page publish
        fail_count    → incremented on QC failure

    Every retrieval increments access_count + weight.
    Call Memory.success(ids) after publish. Memory.fail(ids) on QC failure.
    """

    @staticmethod
    def save(
        subject: str,
        body: str,
        person: Optional[str] = None,
        entities: Optional[List[str]] = None,
        node_type: Optional[str] = None,
        source_links: Optional[List[Dict]] = None,
        origin: str = 'contribution',
        project: Optional[str] = None,
        expires_at: Optional[str] = None,
        temporal_anchor_start: Optional[str] = None,
        temporal_anchor_end: Optional[str] = None,
        perspectives: bool = True,
        tier: str = 'curated',
        contributor: Optional[str] = None,
        source_system: Optional[str] = None,
        session_id: Optional[str] = None,
        exchange_id: Optional[str] = None,
        source_uri: Optional[str] = None,
        redact: bool = True,
        classify: bool = False,
        active_project: Optional[str] = None,
    ) -> int:
        """
        temporal_anchor_start/end: set these when the claim's correct tense
        depends on the calendar (e.g. "next year's Olympics") rather than on
        how long ago this row was written. See path_memory.temporal.

        redact: scrub credential-shaped strings before storing. On by default
        and at the SAVE boundary rather than at one entry point, so every write
        path is covered — a secret only has to slip through once to be
        replayed into every future context that recalls the memory.

        classify: resolve which project(s) this memory belongs to (see
        path_memory.classify_project). Off by default because it can cost a
        model call; callers that already know the project just pass it.
        """
        import json
        if redact:
            from .redaction import scrub
            subject, redaction_version = scrub(subject)
            body, _ = scrub(body)
        else:
            redaction_version = None
        text    = f"{person or ''} — {subject}\n\n{body}"
        vec     = embed_one(text)
        model   = active_model()
        noun    = classify_noun(person, subject, body)
        vec_str = "[" + ",".join(str(x) for x in vec) + "]"
        nkey    = _make_node_key(person or '', subject, body) if person else None
        links   = json.dumps(source_links or [])

        conn = get_conn()
        cur  = conn.cursor()
        # Guard before the write, not after: a brain that already holds vectors
        # from a different model must not silently acquire incomparable ones.
        assert_brain_compatible(cur)

        # Resolve project identity before storing, so a new spelling can never
        # accumulate. Classification runs only when asked, and only decides
        # what the caller did not already know.
        from . import projects as _projects
        project_links = []
        if classify:
            from .classify_project import classify as _classify
            verdict = _classify(cur, subject, body,
                                active_project=project or active_project)
            project = verdict.get("primary") or project
            project_links = verdict.get("links") or []
        if project:
            resolved, _created, near = _projects.ensure(cur, project)
            if near:
                print(f"[engram] new project {resolved!r} looks close to existing "
                      f"{near} — check for a typo before it becomes two projects",
                      file=_sys.stderr)
            project = resolved

        cur.execute(
            """INSERT INTO memories
                   (person, subject, body, noun_type, node_type, node_key,
                    source_links, origin, embedding, embedding_model, project,
                    expires_at, temporal_anchor_start, temporal_anchor_end,
                    tier, contributor, source_system, session_id, exchange_id,
                    source_uri, redaction_version)
               VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::vector,%s,%s,%s,%s,%s,
                       %s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (node_key) DO UPDATE SET
                   body                   = EXCLUDED.body,
                   source_links           = EXCLUDED.source_links,
                   embedding              = EXCLUDED.embedding,
                   embedding_model        = EXCLUDED.embedding_model,
                   project                = COALESCE(memories.project, EXCLUDED.project),
                   archived               = false,
                   temporal_anchor_start  = EXCLUDED.temporal_anchor_start,
                   temporal_anchor_end    = EXCLUDED.temporal_anchor_end
               RETURNING id""",
            (person, subject, body, noun,
             node_type if node_type in NODE_TYPES else None,
             nkey, links, origin, vec_str, model, project, expires_at,
             temporal_anchor_start, temporal_anchor_end,
             tier, contributor, source_system, session_id, exchange_id,
             source_uri, redaction_version),
        )
        memory_id = cur.fetchone()[0]

        # One row, many links — never one row per project.
        if project:
            _projects.set_links(cur, memory_id, [(project, "primary", 1.0)])
        for link in project_links:
            _projects.set_links(cur, memory_id,
                                [(link["project"], link["role"], link.get("confidence"))])

        all_entities = []
        if person:
            all_entities.append(person)
        if entities:
            all_entities.extend(e for e in entities if e and e != person)
        for entity in all_entities:
            cur.execute(
                "INSERT INTO memory_entities (memory_id, entity) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                (memory_id, entity),
            )

        # Fan-out perspective lenses: index this memory under several orthogonal
        # angles so it's findable from more than its literal wording. Shares this
        # transaction; a lens failure is swallowed and never blocks the save.
        if perspectives:
            from .perspectives import store_perspectives
            try:
                store_perspectives(cur, memory_id, person, subject, body)
            except Exception:
                pass

        conn.commit()
        cur.close()
        conn.close()
        return memory_id

    @staticmethod
    def get(memory_id: int) -> Optional[Dict[str, Any]]:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(
            """SELECT id, person, subject, body, noun_type, node_type, node_key,
                      source_links, origin, weight, access_count,
                      success_count, fail_count, created_at,
                      temporal_anchor_start, temporal_anchor_end
               FROM memories WHERE id = %s AND archived = false""",
            (memory_id,),
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                """UPDATE memories SET
                     access_count = access_count + 1,
                     weight = weight + (1.0 / (access_count + 2)),
                     last_accessed = now()
                   WHERE id = %s""",
                (memory_id,),
            )
            conn.commit()
        cur.close()
        conn.close()
        if not row:
            return None
        return {
            "id": row[0], "person": row[1], "subject": row[2], "body": row[3],
            "noun_type": row[4], "node_type": row[5], "node_key": row[6],
            "source_links": row[7], "origin": row[8],
            "weight": row[9], "access_count": row[10],
            "success_count": row[11], "fail_count": row[12], "created_at": row[13],
            "temporal_anchor_start": row[14], "temporal_anchor_end": row[15],
            "temporal_status": temporal_status(row[14], row[15]),
        }

    @staticmethod
    def success(memory_ids: List[int]) -> None:
        """Call after successful page publish for every node included in the output."""
        if not memory_ids:
            return
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(
            """UPDATE memories SET
                 success_count = success_count + 1,
                 weight = weight + (1.0 / (access_count + 2))
               WHERE id = ANY(%s)""",
            (memory_ids,),
        )
        conn.commit()
        cur.close()
        conn.close()

    @staticmethod
    def fail(memory_ids: List[int]) -> None:
        """Call when a page fails QC — increments fail_count, decays weight slightly."""
        if not memory_ids:
            return
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(
            """UPDATE memories SET
                 fail_count = fail_count + 1,
                 weight = GREATEST(0, weight - 0.05)
               WHERE id = ANY(%s)""",
            (memory_ids,),
        )
        conn.commit()
        cur.close()
        conn.close()

    @staticmethod
    def supersede(old_id: int, new_id: int) -> None:
        """Distillation: mark old_id as replaced by new_id. The old memory stays
        fully recallable but ranks below its replacement (recall multiplies its
        score by SUPERSEDED_FACTOR) — so the correction wins close calls without
        erasing the original, in case the replacement dropped a needed detail."""
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("UPDATE memories SET superseded_by = %s WHERE id = %s", (new_id, old_id))
        conn.commit()
        cur.close()
        conn.close()

    @staticmethod
    def attach(memory_id: int, entity: str) -> None:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(
            "INSERT INTO memory_entities (memory_id, entity) VALUES (%s,%s) ON CONFLICT DO NOTHING",
            (memory_id, entity),
        )
        conn.commit()
        cur.close()
        conn.close()

    @staticmethod
    def list_by_entity(entity: str, limit: int = 20) -> List[Dict[str, Any]]:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(
            """SELECT DISTINCT ON (m.id) m.id, m.subject, m.noun_type, m.node_type,
                      m.weight, m.access_count, m.success_count, m.fail_count,
                      m.last_accessed, m.person
               FROM memories m
               LEFT JOIN memory_entities me ON me.memory_id = m.id
               WHERE (m.person = %s OR me.entity = %s) AND m.archived = false
               ORDER BY m.id, m.weight DESC, m.created_at DESC
               LIMIT %s""",
            (entity, entity, limit),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {
                "id": r[0], "subject": r[1], "noun_type": r[2], "node_type": r[3],
                "weight": r[4], "access_count": r[5],
                "success_count": r[6], "fail_count": r[7],
                "last_accessed": r[8], "primary_entity": r[9],
            }
            for r in rows
        ]
