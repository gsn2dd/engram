"""
Canonical project identity.

`project` used to be free text, which meant the same project accumulated
several spellings — in the private brain this produced `wtg` (2009 memories)
and `worldtownguide` (118) as separate projects, plus `pirate_games` alongside
`pirate-games`. Every unscoped recall then treated them as different projects,
and every scoped recall silently returned half the corpus.

The registry fixes that, but only if all three halves are wired up:

  * normalise on WRITE  — new spellings can never accumulate again
  * normalise on READ   — asking by any known alias returns everything
  * backfill ONCE       — existing rows rewritten, old spellings kept as aliases

Any one alone leaks.

An unknown project on write is REGISTERED, not rejected: a memory must never be
lost to a typo. It is reported to the caller so a near-duplicate of an existing
slug gets noticed while it is one row rather than two thousand.
"""

import difflib
import re
from typing import List, Optional, Tuple

ROLES = ("primary", "origin", "applies-to", "mentions")

# How close a new slug has to be to an existing one before we call it suspicious.
_SIMILARITY_WARN = 0.82


def slugify(name: str) -> str:
    """Fold a project name to the canonical shape: lowercase, hyphens, no junk."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(name or "").strip().lower())
    return slug.strip("-")


def resolve(cur, name: Optional[str]) -> Optional[str]:
    """Alias -> canonical slug. Returns None for an unknown or empty name."""
    if not name:
        return None
    cur.execute("SELECT canonical FROM project_aliases WHERE alias = %s", (str(name),))
    row = cur.fetchone()
    if row:
        return row[0]
    # Try the slugified form before giving up: "WTG " and "wtg" are the same ask.
    slug = slugify(name)
    if slug and slug != name:
        cur.execute("SELECT canonical FROM project_aliases WHERE alias = %s", (slug,))
        row = cur.fetchone()
        if row:
            return row[0]
    cur.execute("SELECT slug FROM projects WHERE slug = %s", (slug,))
    return cur.fetchone()[0] if cur.rowcount else None


def near_matches(cur, slug: str) -> List[str]:
    """Existing slugs suspiciously close to this one — the typo alarm."""
    cur.execute("SELECT slug FROM projects")
    existing = [r[0] for r in cur.fetchall()]
    return [s for s in existing
            if s != slug and difflib.SequenceMatcher(None, s, slug).ratio() >= _SIMILARITY_WARN]


def ensure(cur, name: str, display_name: Optional[str] = None) -> Tuple[str, bool, List[str]]:
    """
    Resolve `name`, registering it if genuinely new.

    Returns (canonical_slug, was_created, near_matches). Never raises on an
    unknown project — losing a memory to a typo is far worse than gaining a
    project — but `near_matches` lets the caller shout about a likely duplicate
    at the moment it is created.
    """
    canonical = resolve(cur, name)
    if canonical:
        return canonical, False, []

    slug = slugify(name)
    if not slug:
        return None, False, []

    warn = near_matches(cur, slug)
    cur.execute(
        "INSERT INTO projects (slug, display_name) VALUES (%s, %s) ON CONFLICT (slug) DO NOTHING",
        (slug, display_name or name),
    )
    cur.execute(
        "INSERT INTO project_aliases (alias, canonical) VALUES (%s, %s) ON CONFLICT (alias) DO NOTHING",
        (slug, slug),
    )
    if str(name) != slug:
        cur.execute(
            "INSERT INTO project_aliases (alias, canonical) VALUES (%s, %s) ON CONFLICT (alias) DO NOTHING",
            (str(name), slug),
        )
    return slug, True, warn


def add_alias(cur, alias: str, canonical: str) -> None:
    cur.execute(
        "INSERT INTO project_aliases (alias, canonical) VALUES (%s, %s) "
        "ON CONFLICT (alias) DO UPDATE SET canonical = EXCLUDED.canonical",
        (str(alias), str(canonical)),
    )


def set_links(cur, memory_id: int, links) -> None:
    """
    Attach project links to a memory.

    `links` is an iterable of (project, role, confidence). A memory is NEVER
    duplicated per project: three copies would carry three separate
    access_counts, weights and edge sets, so retrieval evidence splits three
    ways and none of them ever gets strong — which attacks the exact mechanism
    the brain runs on. One row, many links.

    If a claim genuinely differs per project ("this is a bug in engram" vs
    "this is correct behaviour in WTG"), those were never one memory. Write two,
    and cross-link them.
    """
    for project, role, confidence in links:
        canonical = resolve(cur, project)
        if not canonical:
            canonical, _, _ = ensure(cur, project)
        if not canonical:
            continue
        if role not in ROLES:
            role = "mentions"
        cur.execute(
            """INSERT INTO memory_projects (memory_id, project, role, confidence)
               VALUES (%s,%s,%s,%s)
               ON CONFLICT (memory_id, project) DO UPDATE
                 SET role = EXCLUDED.role, confidence = EXCLUDED.confidence""",
            (memory_id, canonical, role, confidence),
        )


def projects_for(cur, memory_id: int):
    cur.execute(
        "SELECT project, role, confidence FROM memory_projects WHERE memory_id = %s "
        "ORDER BY CASE role WHEN 'primary' THEN 0 WHEN 'origin' THEN 1 ELSE 2 END",
        (memory_id,),
    )
    return [{"project": p, "role": r, "confidence": c} for p, r, c in cur.fetchall()]
