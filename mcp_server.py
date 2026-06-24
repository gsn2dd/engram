#!/usr/bin/env python3
"""
Engram MCP server — exposes the brain as MCP tools so any MCP-capable agent
(OpenClaw, Claude Desktop, your own) can attach to it as persistent memory.

It talks to a running engram database via the usual DB_* env vars, and serves
over the network (SSE transport, for the widest client compatibility) so an
agent on another machine can attach by pointing at:

    http://<host>:<port>/sse        (default port 8080)

Tools exposed: remember, remember_json, recall_json, recall,
recall_with_associations, supersede.
"""
import os

from mcp.server.fastmcp import FastMCP

from path_memory.memory import Memory
from path_memory.recall import recall as _recall, recall_with_activation as _recall_assoc

mcp = FastMCP(
    "engram",
    host=os.environ.get("ENGRAM_MCP_HOST", "0.0.0.0"),
    port=int(os.environ.get("ENGRAM_MCP_PORT", "8080")),
)


@mcp.tool()
def remember(subject: str, body: str, person: str = "", project: str = "") -> dict:
    """Store a memory in the brain.

    subject: a short label. body: the full content/fact/decision.
    person:  optional entity this belongs to (a person, place, project, topic).
    project: optional project scope, so one brain can serve many projects.
    Returns the new memory id. The memory is auto-classified and indexed under
    several perspective lenses so it's findable from many angles later.
    """
    mid = Memory.save(subject=subject, body=body,
                      person=person or None, project=project or None)
    return {"id": mid}


@mcp.tool()
def remember_json(json_text: str, person: str = "", project: str = "") -> dict:
    """Attach a whole JSON string to the brain. Each leaf value is folded into a
    recallable memory keyed by its dotted path (e.g. "business.hours.mon"), so
    you can later ask the brain about the JSON's contents in natural language.
    Returns the ids created and the count."""
    from path_memory.fold import fold_json
    ids = fold_json(json_text, person=person or None, project=project or None)
    return {"ids": ids, "count": len(ids)}


@mcp.tool()
def recall_json(person: str = "", project: str = "") -> dict:
    """Reassemble JSON previously stored via remember_json back into one whole
    object, scoped by project and/or person. The inverse of remember_json — fold
    a blob in, get the whole structure back out with types intact."""
    from path_memory.fold import recall_json as _recall_json
    return {"json": _recall_json(person=person or None, project=project or None)}


@mcp.tool()
def recall(query: str, person: str = "", project: str = "", limit: int = 5,
           creativity: float = 0.0) -> list:
    """Recall memories by meaning, not keywords. Returns the best matches,
    strongest first. Optional person/project narrow the search. Every recall
    quietly strengthens the paths it travels.

    creativity (0..1): raise it to blend in 'near-miss' memories — related but
    not the obvious answer — to spark connections the literal query would miss.
    Those picks are flagged serendipity=true; treat them as prompts, not facts."""
    rows = _recall(query, person=person or None, project=project or None,
                   limit=limit, creativity=creativity)
    return [{"id": r["id"], "subject": r["subject"], "body": r["body"],
             "person": r["person"], "score": r["score"],
             "serendipity": r.get("serendipity", False)} for r in rows]


@mcp.tool()
def recall_with_associations(query: str, limit: int = 5) -> dict:
    """Like recall, but also surfaces memories linked *by use* (spreading
    activation) — connections that meaning-search alone can never find."""
    out = _recall_assoc(query, limit=limit)
    return {
        "results": [{"id": r["id"], "subject": r["subject"], "score": r.get("score")}
                    for r in out["results"]],
        "associated": [{"id": a["id"], "subject": a["subject"]}
                       for a in out["activated"]],
    }


@mcp.tool()
def supersede(old_id: int, new_id: int) -> dict:
    """Distillation: mark an old memory as replaced by a newer one. The old one
    stays recallable but ranks below its replacement."""
    Memory.supersede(old_id, new_id)
    return {"ok": True, "superseded": old_id, "by": new_id}


if __name__ == "__main__":
    # SSE transport — widest client compatibility (works with OpenClaw's gateway
    # and embedded modes, and older MCP clients). Serves /sse + /messages.
    mcp.run(transport="sse")
