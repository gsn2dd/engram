#!/usr/bin/env python3
"""
Warm a cold brain by simulating REAL WORK, so the use-built graph can be tested.

THE QUESTION THIS ANSWERS. Engram's distinctive claim is that recall improves
because of use: memories recalled together lay down edges, and spreading
activation later surfaces what is linked BY USE rather than by meaning. On a
freshly-seeded brain that machinery is inert — the theatre demo brain has 0
links, 0 edges and 0 weight — so the claim cannot be demonstrated or tested. It
needs months of real use, which a demo cannot fake and a bench cannot wait for.

WHY SIMULATING IT IS LEGITIMATE, AND WHERE IT WOULD NOT BE.

An edge is laid between memories RETURNED TOGETHER FOR THE SAME QUERY. That is
not cosine(A, B). Two memories can be far apart in embedding space and still be
co-relevant to one question — the boiler deferral and the damp costumes are not
similar to each other, but "why is the wardrobe damp?" wants both. The edge
encodes query-mediated co-relevance, which is precisely the thing similarity
cannot express, and it is why a warm graph can beat a cold one.

That only holds IF THE QUERIES ARE REAL WORK. Generate queries from the corpus's
own subject lines and every edge will connect near-duplicates — the graph then
says exactly what cosine already said, and warming demonstrates a tautology. So
the sessions below are hand-written as TASKS someone at this theatre would
actually be doing, each a sequence of questions asked while doing one job.

Written by hand, not generated, for two reasons: a model asked for "queries
about this corpus" drifts back toward restating subject lines, and the tasks
must be authored INDEPENDENTLY OF THE WIKILINKS so the bench's ground truth
stays separate from the signal being warmed. If the tasks were derived from the
labelled pairs, any improvement would be the harness marking its own homework.

increment_weight=True here is deliberate and is the one place it belongs: this
IS the simulated use. Everywhere else in the bench it is False, because a
benchmark that warms the graph it is measuring cannot be trusted.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from path_memory.db import get_conn
from path_memory.links import compact_links
from path_memory.recall import recall

# Each entry is one work session: a person doing ONE job, asking the questions
# that job actually raises, in the order it raises them. The value is in the
# SEQUENCE — memories co-recalled inside a task become linked, and tasks cut
# across the categories the corpus is organised by.
SESSIONS = [
    ("preparing the Arts Council submission", [
        "what funding have we been awarded recently",
        "what audience figures do we have for the last season",
        "what did we promise in the last funding application",
        "what is our position on the youth programme",
        "when is the submission deadline",
        "who signs off the accounts",
    ]),
    ("handling the storm damage insurance claim", [
        "what damage did the storm do",
        "what did the insurer say about the claim",
        "what did the roof repairs cost",
        "which contractor did the building work",
        "what is still not fixed in the building",
    ]),
    ("casting and staffing the winter show", [
        "what is the winter production",
        "who has been cast so far",
        "what problems have we had with availability",
        "who covers sound and lighting",
        "what does the resident company cost us",
    ]),
    ("sorting out the bar and front of house", [
        "how is the bar performing",
        "what licensing constraints do we have",
        "what did we change about last orders",
        "what complaints have we had from customers",
        "who supplies our drinks",
    ]),
    ("planning the tour", [
        "which venues are on the tour",
        "what went wrong with a touring venue",
        "what does a get-in involve at each venue",
        "how many performances per venue",
    ]),
    ("the building is falling apart again", [
        "what maintenance is outstanding",
        "what problems have we had with damp",
        "what happened with the boiler",
        "which rooms are out of use",
        "what have we deferred for budget reasons",
    ]),
    ("board and governance", [
        "who resigned from the board",
        "what did the board decide about ticket prices",
        "what is the board worried about",
        "when is the next away day",
    ]),
    ("the youth programme and outreach", [
        "how is the youth programme funded",
        "what outreach have we done in deprived areas",
        "how many young people take part",
        "what did the teen showcase achieve",
    ]),
]


def warm(rounds=1, limit=5, verbose=True):
    """Run every session `rounds` times, then compact the footprints into edges.

    Repeating sessions matters: one pass creates a footprint, repetition is what
    turns a footprint into a STRENGTH. That is the whole point of the compaction
    step — a pair recalled together five times should outweigh a pair recalled
    together once, and a single pass cannot express that.
    """
    queries = 0
    for _ in range(rounds):
        for task, qs in SESSIONS:
            for q in qs:
                recall(q, limit=limit, increment_weight=True)
                queries += 1
            if verbose:
                print(f"  {task}: {len(qs)} queries", flush=True)

    conn = get_conn()
    compacted = compact_links(conn)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM path_edge_summary")
    edges = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM memories WHERE weight > 0")
    warm_memories = cur.fetchone()[0]
    cur.execute("SELECT round(avg(strength)::numeric,2), round(max(strength)::numeric,2) "
                "FROM path_edge_summary")
    avg_s, max_s = cur.fetchone()
    cur.close()
    conn.close()
    return {"queries": queries, "compacted": compacted, "edges": edges,
            "warm_memories": warm_memories, "avg_strength": avg_s, "max_strength": max_s}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3,
                    help="how many times to run the whole set of work sessions")
    ap.add_argument("--limit", type=int, default=5)
    args = ap.parse_args()
    print(f"Simulating {args.rounds} rounds of work across {len(SESSIONS)} sessions...")
    r = warm(rounds=args.rounds, limit=args.limit)
    print(f"\n{r['queries']} queries -> {r['edges']} edges, "
          f"{r['warm_memories']} memories carry weight "
          f"(strength avg {r['avg_strength']}, max {r['max_strength']})")


if __name__ == "__main__":
    main()
