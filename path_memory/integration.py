"""
Engram — Lambda Integration Helper
Drop-in join point for get_record_from_intelligence.

Usage in the Lambda, right after fetch_approved_contribution_summary():

    from path_memory.integration import fetch_ranked_nodes, format_for_prompt, mark_success, mark_fail

    pm_nodes = fetch_ranked_nodes(geonameid, query=place_name, top_k=12)
    user_context_extra = format_for_prompt(pm_nodes)

    # After successful publish:
    mark_success([n['id'] for n in pm_nodes])

    # After QC failure:
    mark_fail([n['id'] for n in pm_nodes])
"""
from typing import List, Dict, Any, Optional
from .recall import recall
from .memory import Memory


# Node types that are most useful in the writer's user_context window
WRITER_NODE_TYPES = ('fact', 'anchor', 'sentiment', 'faq')
SECTION_NODE_TYPES = ('section',)
SOURCE_NODE_TYPES  = ('source',)


def fetch_ranked_nodes(
    geonameid: str,
    query: Optional[str] = None,
    node_types: Optional[List[str]] = None,
    top_k: int = 12,
    origin: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieve and rank observation nodes for a geonameid.
    Uses composite score: 0.7*weight + 0.2*recency + 0.1*semantic_match.

    If query is None, uses the geonameid itself as the query string
    (pulls topically relevant nodes without a specific writer question).

    Returns top_k nodes ready for format_for_prompt().
    """
    q = query or geonameid

    if node_types:
        # Separate call per node_type, merge and re-sort
        all_nodes: List[Dict] = []
        seen: set = set()
        for nt in node_types:
            batch = recall(q, person=geonameid, node_type=nt,
                           origin=origin, limit=top_k,
                           increment_weight=True)
            for n in batch:
                if n["id"] not in seen:
                    seen.add(n["id"])
                    all_nodes.append(n)
        all_nodes.sort(key=lambda r: r["score"], reverse=True)
        return all_nodes[:top_k]
    else:
        return recall(q, person=geonameid, origin=origin,
                      limit=top_k, increment_weight=True)


_TEMPORAL_HINT = {
    "upcoming": " [UPCOMING — keep future tense]",
    "current": " [HAPPENING NOW — present tense]",
    "past": " [NOW PAST — rephrase in past tense, do not repeat frozen wording as-is]",
}


def _temporal_hint(node: Dict[str, Any]) -> str:
    """
    Surface a live tense hint so the writer doesn't copy a calendar-anchored
    claim's wording verbatim once its status has moved on (e.g. "next year's
    Olympics" written months ago, now past). Empty string for nodes with no
    temporal anchor — the common case.
    """
    return _TEMPORAL_HINT.get(node.get("temporal_status"), "")


def format_for_prompt(nodes: List[Dict[str, Any]]) -> str:
    """
    Format ranked observation nodes into clearly labelled blocks
    for injection into the writer prompt user_context.

    Produces named sections matching what get_record_from_intelligence
    already expects: top_local_insights, top_famous_anchors.
    """
    if not nodes:
        return ""

    facts     = [n for n in nodes if n.get("node_type") in ("fact", "section", None)]
    anchors   = [n for n in nodes if n.get("node_type") == "anchor"]
    sentiments = [n for n in nodes if n.get("node_type") == "sentiment"]
    faqs       = [n for n in nodes if n.get("node_type") == "faq"]

    parts = []

    if facts:
        lines = [f"- [{n.get('node_key') or n['id']}]{_temporal_hint(n)} {n['body']}" for n in facts[:8]]
        parts.append("TOP LOCAL INSIGHTS (ranked by retrieval weight):\n" + "\n".join(lines))

    if anchors:
        lines = [f"- {n['subject']}:{_temporal_hint(n)} {n['body']}" for n in anchors[:5]]
        parts.append("TOP FAMOUS ANCHORS:\n" + "\n".join(lines))

    if sentiments:
        lines = [f"- {n['body']}" for n in sentiments[:4]]
        parts.append("VISITOR SENTIMENTS:\n" + "\n".join(lines))

    if faqs:
        lines = [f"Q: {n['subject']}\nA: {n['body']}" for n in faqs[:3]]
        parts.append("FREQUENTLY ASKED:\n" + "\n".join(lines))

    return "\n\n".join(parts)


def mark_success(memory_ids: List[int]) -> None:
    """Call after successful page publish. Reinforces weight for included nodes."""
    Memory.success(memory_ids)


def mark_fail(memory_ids: List[int]) -> None:
    """Call after QC failure. Decays weight for nodes in the failed output."""
    Memory.fail(memory_ids)
