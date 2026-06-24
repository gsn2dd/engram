"""
Engram — Seed Compiler
Turns accumulated memories for an entity into a versioned, checksummed
seed artifact: the product object that closes the loop.

Entity key for places: GeoNames ID as a string (e.g. "2643743" for London).
GeoNames IDs are globally unique, stable, and interoperable with OSM/Wikipedia.
For non-place entities (projects, people) any stable slug works.

Usage:
    from seed.compile import compile_seed, get_seed, geonames_meta
    seed = compile_seed("2643743")          # London by GeoNames ID
    seed = get_seed("2643743")              # latest stored version
    meta = geonames_meta("2643743")        # name, country, population, coords
"""
import hashlib
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from path_memory.db import get_conn
from path_memory.links import spreading_activate

GEONAMES_USER = os.environ.get("GEONAMES_USER", "")   # free account at geonames.org

# Standard topic categories — used for gap/debt detection
TOPIC_CATEGORIES = [
    "transport",
    "accommodation",
    "food and drink",
    "best time to visit",
    "hidden gems",
    "history and culture",
    "safety",
    "costs and money",
    "language and communication",
    "weather and climate",
    "local customs",
    "nature and outdoors",
]

CATEGORY_KEYWORDS = {
    "transport":              ["bus", "train", "metro", "tube", "tram", "taxi", "walk", "bike", "airport", "transport", "travel"],
    "accommodation":          ["hotel", "hostel", "airbnb", "stay", "accommodation", "room", "apartment", "rent"],
    "food and drink":         ["food", "eat", "restaurant", "cafe", "coffee", "bar", "drink", "market", "cuisine"],
    "best time to visit":     ["time", "season", "summer", "winter", "spring", "autumn", "month", "weather", "peak", "crowd"],
    "hidden gems":            ["hidden", "gem", "secret", "local", "quiet", "off the beaten", "underrated", "unknown"],
    "history and culture":    ["history", "museum", "monument", "culture", "art", "church", "cathedral", "heritage", "ancient"],
    "safety":                 ["safe", "safety", "crime", "scam", "avoid", "danger", "risk", "police", "emergency"],
    "costs and money":        ["cost", "price", "cheap", "expensive", "budget", "money", "euro", "currency", "free", "tip"],
    "language and communication": ["language", "speak", "english", "local", "phrase", "translate", "communicate"],
    "weather and climate":    ["weather", "rain", "sun", "hot", "cold", "temperature", "climate", "humidity", "wind"],
    "local customs":          ["custom", "culture", "tradition", "etiquette", "dress", "respect", "local", "norm"],
    "nature and outdoors":    ["park", "nature", "walk", "hike", "river", "mountain", "beach", "garden", "outdoor"],
}


def geonames_meta(geonameid):
    """
    Fetch place metadata from GeoNames API.
    Returns dict with name, country, population, lat, lng, timezone — or None.
    Requires GEONAMES_USER env var (free account at geonames.org).
    """
    if not GEONAMES_USER or not str(geonameid).isdigit():
        return None
    try:
        url = (
            f"http://api.geonames.org/getJSON"
            f"?geonameId={geonameid}&username={GEONAMES_USER}"
        )
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read())
        if "status" in data:
            return None
        return {
            "geonameid":  str(data.get("geonameId", geonameid)),
            "name":       data.get("name"),
            "ascii_name": data.get("asciiName"),
            "country":    data.get("countryName"),
            "country_code": data.get("countryCode"),
            "population": data.get("population"),
            "lat":        data.get("lat"),
            "lng":        data.get("lng"),
            "timezone":   data.get("timezone", {}).get("timeZoneId"),
            "admin1":     data.get("adminName1"),
        }
    except Exception:
        return None


def _detect_gaps(memories):
    """Return topic categories with no memory coverage — the research debt."""
    covered = set()
    for m in memories:
        text = f"{m['subject']} {m['body']}".lower()
        for category, keywords in CATEGORY_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                covered.add(category)
    return [c for c in TOPIC_CATEGORIES if c not in covered]


def _checksum(payload):
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def compile_seed(entity, min_weight=0.0, limit=50, activation_hops=2, activation_limit=10):
    """
    Compile the current top memories for entity into a seed artifact.
    Stores it in the seeds table (new version each call).

    Beyond the weight-ranked cutoff, walks the path graph outward from
    those nodes via spreading_activate() so memories linked by use --
    not by weight or cosine similarity on their own -- are folded in
    too, each tagged with how it was discovered. This is what makes the
    seed a product of the graph rather than just a top-N weight dump.

    Returns the seed dict.
    """
    conn = get_conn()
    cur  = conn.cursor()

    # Include memories where this entity is primary OR secondary attachment
    cur.execute(
        """SELECT DISTINCT ON (m.id) m.id, m.subject, m.body, m.noun_type,
                  m.weight, m.access_count, m.last_accessed, m.created_at, m.person
           FROM memories m
           LEFT JOIN memory_entities me ON me.memory_id = m.id
           WHERE (m.person = %s OR me.entity = %s)
             AND m.archived = false AND m.weight >= %s
           ORDER BY m.id, m.weight DESC, m.access_count DESC
           LIMIT %s""",
        (entity, entity, min_weight, limit),
    )
    rows = cur.fetchall()
    seed_ids = [r[0] for r in rows]

    memories = [
        {
            "id":             r[0],
            "subject":        r[1],
            "body":           r[2],
            "noun_type":      r[3],
            "weight":         float(r[4]),
            "access_count":   r[5],
            "last_accessed":  r[6].isoformat() if r[6] else None,
            "created_at":     r[7].isoformat() if r[7] else None,
            "primary_entity": r[8],    # may differ from entity if attached secondarily
        }
        for r in rows
    ]

    activated = spreading_activate(conn, seed_ids, hops=activation_hops, decay=0.5, limit=activation_limit)
    if activated:
        activation_by_id = {a["id"]: a["activation"] for a in activated}
        cur.execute(
            """SELECT id, subject, body, noun_type, weight, access_count,
                      last_accessed, created_at, person
               FROM memories WHERE id = ANY(%s) AND archived = false""",
            (list(activation_by_id.keys()),),
        )
        for r in cur.fetchall():
            memories.append({
                "id":               r[0],
                "subject":          r[1],
                "body":             r[2],
                "noun_type":        r[3],
                "weight":           float(r[4]),
                "access_count":     r[5],
                "last_accessed":    r[6].isoformat() if r[6] else None,
                "created_at":       r[7].isoformat() if r[7] else None,
                "primary_entity":   r[8],
                "discovered_via":   "spreading_activation",
                "activation_score": round(activation_by_id[r[0]], 4),
            })

    gaps     = _detect_gaps(memories)
    mem_ids  = [m["id"] for m in memories]
    total_w  = sum(m["weight"] for m in memories)
    mean_w   = total_w / len(memories) if memories else 0.0
    max_w    = max((m["weight"] for m in memories), default=0.0)

    # Determine next version number
    cur.execute(
        "SELECT COALESCE(MAX(version), 0) FROM seeds WHERE entity = %s",
        (entity,),
    )
    next_version = cur.fetchone()[0] + 1

    # Enrich with GeoNames metadata if entity looks like a geonameid
    place_meta = geonames_meta(entity) if str(entity).isdigit() else None

    payload = {
        "entity":       entity,
        "place":        place_meta,          # None for non-place entities
        "version":      next_version,
        "memory_count": len(memories),
        "weight_summary": {
            "total": round(total_w, 4),
            "mean":  round(mean_w, 4),
            "max":   round(max_w, 4),
        },
        "top_paths":      memories,
        "activated_count": sum(1 for m in memories if m.get("discovered_via") == "spreading_activation"),
        "gaps":           gaps,
        "compiled_at":  None,   # filled after insert
    }
    checksum = _checksum(payload)

    cur.execute(
        """INSERT INTO seeds (entity, version, checksum, payload, memory_ids)
           VALUES (%s, %s, %s, %s::jsonb, %s)
           RETURNING id, compiled_at""",
        (entity, next_version, checksum, json.dumps(payload, default=str), mem_ids),
    )
    seed_id, compiled_at = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()

    payload["compiled_at"] = compiled_at.isoformat()
    payload["checksum"]    = checksum
    payload["seed_id"]     = seed_id
    return payload


def get_seed(entity):
    """Return the latest compiled seed for entity, or None."""
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """SELECT payload, checksum, compiled_at
           FROM seeds WHERE entity = %s
           ORDER BY version DESC LIMIT 1""",
        (entity,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    seed = row[0]
    seed["checksum"]    = row[1]
    seed["compiled_at"] = row[2].isoformat() if row[2] else None
    return seed
