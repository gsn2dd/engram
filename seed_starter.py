#!/usr/bin/env python3
"""
Seed the starter brain: a handful of memories ABOUT engram itself.

An empty brain is a bad first impression and a slightly broken one. Recall
returns nothing, collapse has no field to resolve, the dreaming pass has
nothing to read, and every threshold in the engine was fitted to a corpus that
does not exist yet. More practically: the first thing anyone does with a memory
system is ask it something, and "no results" teaches them nothing about whether
it works.

So a fresh instance starts with the engine's own documentation stored AS
MEMORIES. Asking "how do I connect my agent" is then both the first useful
answer and a live demonstration that semantic recall works — the queries below
share almost no words with the memories they find.

Two deliberate choices:

  * PROJECT-SCOPED to `engram-guide`, never mixed into the user's own projects,
    so it can be removed completely with one command (printed at the end) once
    it has served its purpose. A starter brain that cannot be cleanly deleted
    is contamination, not a welcome.
  * HONEST. These are shipped to customers and become the engine's own account
    of itself. The status note says the same thing the README says, including
    what is still a bet. A memory system whose own memories oversell it is
    teaching the wrong lesson on day one.

Idempotent, and safe to call when no API keys are configured — it needs to
embed, so with no provider it exits quietly rather than failing a boot.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PROJECT = "engram-guide"

STARTER = [
    ("what engram is",
     "Engram is a memory brain an AI agent attaches to, not a document store. Anything you put in "
     "is indexed from several angles at once, gains connections from how it is actually used, grows "
     "stronger with retrieval and fades when neglected. The point is that the brain outlives any one "
     "agent, model or vendor: agents get replaced every few months, your memory should not."),

    ("connecting an agent to this brain",
     "The MCP endpoint is http://localhost:8080/sse. Any MCP-capable agent attaches to it — Claude "
     "Code with `claude mcp add --transport sse engram http://localhost:8080/sse`, or an OpenClaw or "
     "Hermes agent pointed at the same URL. On the AWS image the port is deliberately not exposed to "
     "the network; reach it through an SSM port-forward or an SSH tunnel."),

    ("why the port is closed by default",
     "The MCP server has no authentication of its own, so anything that can reach it can read and "
     "write the entire brain. That is why it binds to loopback and access goes through a tunnel. Do "
     "not expose port 8080 to a network you do not control. The ingest endpoint on 8081 is different: "
     "it requires a bearer token, and that token is generated uniquely for your instance on first boot."),

    ("the tools an attached agent gets",
     "Six: remember (store a subject plus a body), recall (find by meaning, not keywords), "
     "recall_with_associations (pull in what is linked by past use as well as by meaning), "
     "remember_json and recall_json (fold a structured record in and get it back out whole), and "
     "supersede (mark an old memory as replaced by a newer one, so recall prefers the current version "
     "without destroying the history)."),

    ("telling an agent to actually use its memory",
     "A model will not use a brain unless its persona tells it to. Paste the block from AGENT_PROMPT.md "
     "into your agent's system prompt — this is the single most important setup step, and skipping it "
     "means the tools are present but only get reached for when you ask explicitly. Better still, wire "
     "recall into a startup hook so memory arrives without the agent having to choose to ask for it."),

    ("getting a clean answer instead of a padded list",
     "Call recall with collapse=true. A normal search returns a fixed number of results and pads the "
     "tail with weak matches; collapse finds where relevance actually falls off a cliff and stops "
     "there, so you get the answer set rather than the top few. Use it when you want what is genuinely "
     "relevant and nothing else."),

    ("getting unstuck on purpose",
     "Recall takes a creativity dial between 0 and 1. Leave it at 0 for factual lookups. Raise it to "
     "0.5-0.8 when brainstorming or stuck, and recall will mix in related-but-unexpected memories, "
     "flagged as serendipity. They are drawn from near-misses, so they are adjacent rather than random."),

    ("keeping one brain for several workstreams",
     "Pass a project when you store and when you recall, and one brain serves many workstreams without "
     "them bleeding into each other. Projects are canonicalised, so alternative spellings of the same "
     "name resolve to one project instead of quietly splitting your corpus in half. Subjects within a "
     "project become topics, so you can narrow further — one town inside a whole site, say."),

    ("what happens while you are not using it",
     "A consolidation pass runs on a timer. It compacts the traces of what was recalled together into "
     "the association graph, decays what has gone unused, reads new memories to work out what subjects "
     "they concern, and writes summaries. It is closer to sleep than to housekeeping: the connections "
     "that make recall good are formed offline, not at the moment you store something."),

    ("capturing conversations automatically",
     "The Engram Capture browser extension records your claude.ai and ChatGPT conversations into this "
     "brain. Point it at the ingest endpoint on port 8081 with the bearer token from "
     "/etc/engram/engram.env. Secrets are stripped both in the browser and again at the server before "
     "anything is stored — but treat that as a safety net, not a licence to paste keys into a chat."),

    ("setting the API key this brain needs",
     "Engram needs an embedding key to store anything, and the image ships without one on purpose. "
     "On the AWS image: edit /etc/engram/engram.env as root, set GEMINI_API_KEY or OPENAI_API_KEY, "
     "then `systemctl restart engram`. Running under docker compose: put the key in your .env or pass "
     "it with -e. Pin the provider with ENGRAM_EMBED_PROVIDER=gemini or openai if you have both. "
     "Nothing can be remembered until this is done — a save without a key fails outright."),

    ("first five minutes with a new brain",
     "1. Set an embedding key (see the memory on that). 2. Open a tunnel to port 8080 if you are on "
     "the AWS image. 3. Attach your agent to the MCP endpoint. 4. Paste AGENT_PROMPT.md into your "
     "agent's system prompt so it actually reaches for memory. 5. Ask it to recall something from "
     "these starter memories to prove the loop works end to end. 6. Delete these with "
     "`pm forget-project engram-guide --yes` once you no longer need them."),

    ("what to do if recall returns nothing",
     "Check in this order. Is an embedding key set — a brain with no key stores nothing, so it is "
     "genuinely empty. Are you scoping to a project that has no memories in it? Is the provider the "
     "same one that wrote the existing memories — vectors from two different embedding models are the "
     "same length and not comparable, so a mismatched provider makes an existing brain look empty. "
     "The engine refuses to mix them rather than degrading quietly."),

    ("where the code and the issues live",
     "Engram is open source at github.com/gsn2dd/engram — MIT licensed. The engine is written entirely "
     "by AI from a human author's direction. Raise problems, questions and what-broke reports there; "
     "real usage data is the thing the project most needs."),

    ("what is proven and what is still a bet",
     "Honest status: engram works and is tested, but it has not been proven in long real-world use. "
     "The parts that make it useful — persistent, semantic, structured, attachable — are solid. The "
     "parts that make it distinctive — memory that improves with use and forgets cleanly over time — "
     "depend on an aged brain with a real association graph, and that is still being tested. Run it, "
     "and say what it remembered and what it lost."),
]


def already_seeded(conn) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM memories WHERE project = %s LIMIT 1", (PROJECT,))
    seeded = cur.fetchone() is not None
    cur.close()
    return seeded


def main() -> int:
    from path_memory.db import get_conn
    from path_memory.embed import provider_ready

    # provider_ready(), not resolve_provider(): with ENGRAM_EMBED_PROVIDER pinned,
    # resolve_provider() happily names a provider whose key is absent, so the
    # guard passed and every single memory then failed individually. The image
    # ships without keys on purpose — the customer supplies them — so no keys is
    # the normal first-boot state, not a failure worth aborting startup for.
    if not provider_ready():
        # Exit 2, NOT 0. The boot loop retries on non-zero, and returning 0 here
        # told it the job was finished — so the starter brain would never appear
        # after the customer added a key, which is the whole case this exists
        # for. 0 means "the brain has its starter memories"; 2 means "not yet".
        print("[starter] no embedding provider configured; will retry when one is set",
              file=sys.stderr)
        return 2

    conn = get_conn()
    try:
        if already_seeded(conn):
            print("[starter] starter memories already present; nothing to do", file=sys.stderr)
            return 0
    finally:
        conn.close()

    from path_memory.memory import Memory
    stored = 0
    for subject, body in STARTER:
        try:
            Memory.save(subject=subject, body=body, person=None, project=PROJECT,
                        origin="contribution", tier="curated", source_system="starter")
            stored += 1
        except Exception as exc:
            print(f"[starter] could not store {subject!r}: {exc}", file=sys.stderr)

    if not stored:
        # Do not print a welcome for a brain that received nothing.
        print("[starter] stored nothing; leaving the brain empty", file=sys.stderr)
        return 2

    print(f"[starter] stored {stored} starter memories in project '{PROJECT}'.")
    print("[starter] try:  pm recall \"how do I plug my agent into this\"")
    print("[starter]       pm recall \"is it safe to open the port\"")
    print("[starter]       pm recall \"what does it do while I am asleep\"")
    print(f"[starter] remove them all with:  pm forget-project {PROJECT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
