import hashlib
import re
from typing import Optional, List, Dict, Any
from .db import get_conn
from .embed import embed_one
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
    ) -> int:
        """
        temporal_anchor_start/end: set these when the claim's correct tense
        depends on the calendar (e.g. "next year's Olympics") rather than on
        how long ago this row was written. See path_memory.temporal.
        """
        import json
        text    = f"{person or ''} — {subject}\n\n{body}"
        vec     = embed_one(text)
        noun    = classify_noun(person, subject, body)
        vec_str = "[" + ",".join(str(x) for x in vec) + "]"
        nkey    = _make_node_key(person or '', subject, body) if person else None
        links   = json.dumps(source_links or [])

        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(
            """INSERT INTO memories
                   (person, subject, body, noun_type, node_type, node_key,
                    source_links, origin, embedding, project, expires_at,
                    temporal_anchor_start, temporal_anchor_end)
               VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::vector,%s,%s,%s,%s)
               ON CONFLICT (node_key) DO UPDATE SET
                   body                   = EXCLUDED.body,
                   source_links           = EXCLUDED.source_links,
                   embedding              = EXCLUDED.embedding,
                   project                = COALESCE(memories.project, EXCLUDED.project),
                   archived               = false,
                   temporal_anchor_start  = EXCLUDED.temporal_anchor_start,
                   temporal_anchor_end    = EXCLUDED.temporal_anchor_end
               RETURNING id""",
            (person, subject, body, noun,
             node_type if node_type in NODE_TYPES else None,
             nkey, links, origin, vec_str, project, expires_at,
             temporal_anchor_start, temporal_anchor_end),
        )
        memory_id = cur.fetchone()[0]

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
