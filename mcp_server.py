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

    subject: a SHORT, DISTINCTIVE label — this is the main handle the memory is
             found by later, so say what makes this one different from its
             neighbours, not just which category it belongs to.
    body:    the full content/fact/decision. Put the conclusion first; recall
             injects a preview, so a long tail may never be read.
    person:  optional entity this belongs to (a person, place, project, topic).
    project: optional project scope, so one brain can serve many projects.

    Always succeeds and returns the new memory id. May also return `warnings`
    — advisory only, nothing was rejected. They flag the failure modes that are
    invisible one memory at a time and unfixable in bulk later, chiefly a
    subject template that would make this memory and its siblings impossible to
    tell apart. Acting on one means writing a better memory next time, or
    calling `supersede` if you have just replaced something.
    """
    mid = Memory.save(subject=subject, body=body,
                      person=person or None, project=project or None)
    out = {"id": mid}
    # Advisory only, and never allowed to affect the write that already
    # succeeded — hence the guard around it as well as inside it.
    try:
        from path_memory import quality
        from path_memory.db import get_conn
        conn = get_conn()
        try:
            warnings = quality.messages(conn, mid)
        finally:
            conn.close()
        if warnings:
            out["warnings"] = warnings
    except Exception:
        pass
    return out


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
           creativity: float = 0.0, collapse: bool = False) -> list:
    """Recall memories by meaning, not keywords. Returns the best matches,
    strongest first. Optional person/project narrow the search. Every recall
    quietly strengthens the paths it travels.

    creativity (0..1): raise it to blend in 'near-miss' memories — related but
    not the obvious answer — to spark connections the literal query would miss.
    Those picks are flagged serendipity=true; treat them as prompts, not facts.

    collapse: set true to get only the genuinely-relevant answers instead of a
    fixed `limit`. It finds the natural cliff in relevance and returns just the
    memories above it — three real answers come back as three, not five padded
    with weak matches. Use it when you want a clean answer set, not a top-N list."""
    rows = _recall(query, person=person or None, project=project or None,
                   limit=limit, creativity=creativity, collapse=collapse)
    # Log what was SHOWN so that what was USED can be attributed later. Never
    # raises — an analytics write must not be able to break a recall.
    from path_memory import events as _events
    event_id = _events.record(query, rows, project=project or None, source="mcp")
    out = [{"id": r["id"], "subject": r["subject"], "body": r["body"],
            "person": r["person"], "score": r["score"],
            "serendipity": r.get("serendipity", False)} for r in rows]
    if event_id and out:
        # Carried on the first row rather than wrapping the whole response in an
        # envelope, which would change the tool's shape for every existing
        # caller in order to serve an optional follow-up call.
        out[0]["event_id"] = event_id
    return out


@mcp.tool()
def mark_used(event_id: int, used_ids: list) -> dict:
    """Report which recalled memories ACTUALLY helped you answer.

    Call this after you have used a recall's results. Pass the `event_id` from
    that recall and the ids that genuinely informed your answer — not everything
    you were shown.

    Why it matters: recall strengthens whatever it returns, so without this the
    brain learns what its own ranker likes rather than what turned out to be
    worth having. Reporting an EMPTY list is useful and honest — it records that
    the recall did not help, which is the one outcome nothing else can detect."""
    from path_memory import events as _events
    ok = _events.mark_used(int(event_id), [int(i) for i in (used_ids or [])])
    return {"ok": ok, "event_id": int(event_id),
            "used": sorted({int(i) for i in (used_ids or [])})}


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
    import sys

    # SSE transport — widest client compatibility (works with OpenClaw's gateway
    # and embedded modes, and older MCP clients). Serves /sse + /messages.
    #
    # ENGRAM_MCP_TOKEN turns on bearer-token auth for the whole endpoint. This
    # is the long-recorded blocking feature: without it the server trusts
    # anything that can reach the port, which confines every deployment to
    # loopback + tunnel forever. With a token set, clients attach with
    #     headers: { "Authorization": "Bearer <token>" }
    # (Claude Code, OpenClaw and the MCP SDKs all support SSE headers.)
    #
    # No token keeps the historical behaviour so existing local setups do not
    # break — but that mode is only safe on loopback, and says so.
    token = os.environ.get("ENGRAM_MCP_TOKEN", "").strip()
    if token:
        # Same floor as the ingest server: a short token invites brute force,
        # and refusing to start is louder than quietly accepting a weak secret.
        if len(token) < 24:
            print("[engram] refusing to start: ENGRAM_MCP_TOKEN is shorter than 24 chars",
                  file=sys.stderr, flush=True)
            sys.exit(1)
        import uvicorn

        from authgate import BearerGate

        print("[engram] MCP endpoint requires a bearer token", file=sys.stderr, flush=True)
        uvicorn.run(BearerGate(mcp.sse_app(), token),
                    host=mcp.settings.host, port=mcp.settings.port)
    else:
        print("[engram] ENGRAM_MCP_TOKEN not set — MCP endpoint is UNAUTHENTICATED; "
              "keep it on loopback (see deploy docs)", file=sys.stderr, flush=True)
        mcp.run(transport="sse")
