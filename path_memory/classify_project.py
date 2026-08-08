"""
Decide which project(s) a memory belongs to, before it is stored.

Three layers, cheapest first. The ordering is the whole design:

  1. KNOWN CONTEXT — the active project plus which known projects the text
     actually names. Deterministic, free, and right most of the time.
  2. LLM — only for the ambiguous remainder. Deciding what a memory is *about*
     is a meaning judgment, and meaning judgments go to a model, not a regex.
  3. EMBEDDINGS — deliberately NOT here. They audit, they do not assign; see
     below.

WHY EMBEDDINGS DO NOT DECIDE THIS
Measured on the private brain (3,826 memories): for each memory, the share of
its five nearest neighbours sharing its project was 98% for the largest project
but only 64% for the smallest. The small project scored worst precisely because
it is semantically near-identical to its neighbour — which is exactly the
boundary a classifier has to hold. Similarity also tracks corpus share, so a
vector-first classifier quietly absorbs small projects into large ones.

A project label is a fact about PROVENANCE, not a judgment about meaning. We
know what we were working on. Embeddings answer "what is this like?"; the
question here is "where did this come from, and what does it govern?" Use them
afterwards to flag a memory whose neighbours disagree with its label — that is
a drift alarm, not an assignment.
"""

import json
import os
import re
from typing import Dict, List, Optional

from . import projects
from .llm import complete_text

MODEL = os.environ.get("ENGRAM_CLASSIFY_MODEL", "claude-opus-5")
ENABLED = os.environ.get("ENGRAM_CLASSIFY", "auto").strip().lower()

# Roles a secondary link may take. `primary` is excluded deliberately — there is
# exactly one primary and it is returned separately.
SECONDARY_ROLES = ("origin", "applies-to", "mentions")

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "primary": {
            "type": "string",
            "description": "Slug of the project this memory is ABOUT. Exactly one.",
        },
        "links": {
            "type": "array",
            "description": "Other projects this memory touches. Empty is normal and correct.",
            "items": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "role": {"type": "string", "enum": list(SECONDARY_ROLES)},
                    "confidence": {"type": "number"},
                },
                "required": ["project", "role", "confidence"],
                "additionalProperties": False,
            },
        },
        "reasoning": {"type": "string"},
    },
    "required": ["primary", "links", "reasoning"],
    "additionalProperties": False,
}

SYSTEM = """You file engineering memories against the project they belong to.

Roles:
- primary    : what the memory is ABOUT. Exactly one, always.
- origin     : what was being worked on when this was found, if different.
- applies-to : another project the finding genuinely governs.
- mentions   : named in passing, not governed by it.

Rules that matter:
- Choose `primary` only from the candidate slugs given. Never invent one.
- Prefer the subject of the finding over the session it happened in. A bug in
  project A found while working on project B is primary A, origin B.
- Do not add links for projects merely named in passing unless the memory says
  something that actually applies to them. Empty `links` is a good answer.
- If the memory states one claim about several systems, that is one memory with
  several links. If it states DIFFERENT claims about different systems, say so
  in `reasoning` — it should have been written as separate memories.
- Keep `reasoning` to one sentence."""


def _known(cur) -> Dict[str, str]:
    """alias -> canonical, for every registered spelling."""
    cur.execute("SELECT alias, canonical FROM project_aliases")
    aliases = {a.lower(): c for a, c in cur.fetchall()}
    cur.execute("SELECT slug, coalesce(display_name, slug) FROM projects")
    for slug, display in cur.fetchall():
        aliases.setdefault(slug.lower(), slug)
        aliases.setdefault(display.lower(), slug)
    return aliases


def mentioned(text: str, known: Dict[str, str]) -> List[str]:
    """
    Which known projects the text actually names.

    Word-boundary matching on a fixed vocabulary of registered names — hard
    structural work, which is what regex is for. It decides nothing about
    meaning; it only narrows the candidate set handed to the model.
    """
    lowered = (text or "").lower()
    found = []
    for alias, canonical in known.items():
        if len(alias) < 3:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", lowered):
            if canonical not in found:
                found.append(canonical)
    return found


def _deterministic(active: Optional[str], candidates: List[str]) -> Optional[dict]:
    """The cheap answer, when there is an unambiguous one."""
    if active and not [c for c in candidates if c != active]:
        # Nothing but the active project is named: no judgment to make.
        return {"primary": active, "links": [], "reasoning": "only the active project is named",
                "method": "context"}
    if not active and len(candidates) == 1:
        return {"primary": candidates[0], "links": [], "reasoning": "exactly one project named",
                "method": "context"}
    return None


def _ask_model(subject: str, body: str, active: Optional[str], candidates: List[str]) -> Optional[dict]:
    try:
        from anthropic import Anthropic
    except Exception:
        return None
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return None

    prompt = (
        f"Candidate projects: {', '.join(candidates)}\n"
        f"Active project when this was written: {active or '(unknown)'}\n\n"
        f"SUBJECT: {subject}\n\nBODY:\n{(body or '')[:6000]}"
    )
    try:
        response = Anthropic().messages.create(
            model=MODEL,
            # Thinking is on by default on this model and counts against
            # max_tokens, so leave headroom or the JSON truncates mid-object.
            max_tokens=2000,
            system=SYSTEM,
            output_config={
                "effort": "low",          # a constrained pick from a known list
                "format": {"type": "json_schema", "schema": RESULT_SCHEMA},
            },
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        return None

    # A refusal or a truncation both return HTTP 200. Truncation matters here
    # even though the JSON parse below would fail anyway: without the check the
    # cause is invisible, and "classifier returned nothing" reads as a model
    # limitation rather than a max_tokens ceiling somebody can raise.
    text = complete_text(response, what="project classification")
    if not text:
        return None
    try:
        result = json.loads(text)
    except Exception:
        return None
    result["method"] = "llm"
    return result


def classify(cur, subject: str, body: str, active_project: Optional[str] = None,
             touched_projects: Optional[List[str]] = None) -> dict:
    """
    Returns {primary, links: [{project, role, confidence}], reasoning, method}.

    Never raises and never returns None: a memory must be storable even when
    classification fails. The worst case is a memory filed against the active
    project, which is what would have happened without a classifier at all.
    """
    known = _known(cur)
    text = f"{subject}\n\n{body}"
    candidates = mentioned(text, known)

    for extra in (touched_projects or []):
        canonical = projects.resolve(cur, extra)
        if canonical and canonical not in candidates:
            candidates.append(canonical)
    if active_project and active_project not in candidates:
        candidates.append(active_project)

    if not candidates:
        return {"primary": active_project, "links": [], "method": "fallback",
                "reasoning": "no known project named; filed against the active project"}

    quick = _deterministic(active_project, candidates)
    if quick:
        return quick
    if ENABLED in ("0", "off", "false", "never"):
        return {"primary": active_project or candidates[0], "links": [], "method": "context",
                "reasoning": "classifier disabled; filed against the active project"}

    result = _ask_model(subject, body, active_project, candidates)
    if not result:
        return {"primary": active_project or candidates[0], "links": [], "method": "fallback",
                "reasoning": "classifier unavailable; filed against the active project"}

    # Trust the model's judgment, not its spelling: everything it names is
    # resolved through the registry, and anything unregistered is dropped
    # rather than quietly creating a project.
    primary = projects.resolve(cur, result.get("primary")) or active_project or candidates[0]
    links = []
    for link in result.get("links") or []:
        canonical = projects.resolve(cur, link.get("project"))
        if not canonical or canonical == primary:
            continue
        role = link.get("role")
        links.append({
            "project": canonical,
            "role": role if role in SECONDARY_ROLES else "mentions",
            "confidence": link.get("confidence"),
        })
    return {"primary": primary, "links": links, "method": "llm",
            "reasoning": (result.get("reasoning") or "")[:500]}
