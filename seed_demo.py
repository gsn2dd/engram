#!/usr/bin/env python3
"""
Seed a small demo brain, so a fresh Engram boots with something to recall instead
of an empty box. It tells one coherent little story (a fictional startup, "Helix")
so semantic recall and use-built associations have something to show.

Runs only when ENGRAM_SEED_DEMO is truthy, and is idempotent (skips if the demo
project already exists). It uses *your* keys to embed + generate perspectives —
exactly like any real memory — so nothing is baked into the image.

Try, once it's up:
  pm recall "how do we keep users logged in"   # -> the JWT auth decision (no shared words)
  pm recall "where is the team based"           # -> Lisbon
  pm recall "how does the company make money"    # -> the pricing model
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from path_memory.memory import Memory
from path_memory.db import get_conn

DEMO = [
    ("auth decision", "We chose short-lived JWTs over server sessions so the API stays stateless and easy to scale horizontally.", "helix"),
    ("database choice", "Postgres with the pgvector extension holds both our relational data and our embeddings — one datastore, far less to operate.", "helix"),
    ("Maria, the founder", "Maria started Helix after years building search infrastructure; she cares most about low latency and developer experience.", "Maria"),
    ("where the team works", "The team is based in a co-working space in Lisbon, down by the river in Cais do Sodré.", "helix"),
    ("pricing model", "Free for solo developers; usage-based pricing begins once an account passes ten thousand requests a month.", "helix"),
    ("the caching question", "We talked about caching embeddings to cut API spend, and agreed to revisit it once we can see real traffic patterns.", "helix"),
    ("next hire", "The next hire is developer relations, not another backend engineer — distribution is the bottleneck now, not the code.", "helix"),
    ("the Friday outage", "Friday's downtime was connection-pool exhaustion; the fix was bounding the pool size and adding a health check.", "helix"),
]


def already_seeded():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT 1 FROM memories WHERE project = 'demo' LIMIT 1")
    seeded = cur.fetchone() is not None
    cur.close(); conn.close()
    return seeded


def main():
    if already_seeded():
        print("demo brain already present — skipping")
        return
    for subject, body, person in DEMO:
        Memory.save(subject=subject, body=body, person=person, project="demo")
        print(f"  + {subject}")
    print(f"seeded {len(DEMO)} demo memories (project=demo). Try: pm recall \"how do we keep users logged in\"")


if __name__ == "__main__":
    main()
