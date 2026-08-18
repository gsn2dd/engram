#!/usr/bin/env python3
"""
Build an INDEPENDENT second brain for the recall bench.

WHY THIS EXISTS. Every threshold in this engine — USE_BONUS, rank normalisation,
questions-only lenses, the collapse floor, the canary floor — was fitted to one
corpus: mindspace. Fitted-to-n=1 is the largest unknown in the system and the
thing that separates "works for us" from "works".

Two earlier attempts at a second brain each failed in an instructive way:

  * The demo company (36 memories, 14 hand-written questions) SATURATED — every
    policy scored 1.000 hit@1. No headroom, so it cannot discriminate.
  * engram_test (3,841 memories) is a snapshot of mindspace itself, so it tests
    robustness to use-history state but shares the author, domain and vocabulary.

This builds the missing one: a few hundred memories in a domain deliberately
unlike ours, with ground truth the ranker had no vote in.

THE DESIGN DECISION THAT MAKES THE GROUND TRUTH HARD, and therefore useful.

A generated corpus whose cross-references connect obviously-similar memories
produces an easy bench — cosine finds those unaided and every policy scores the
same, which is exactly how the demo brain saturated. So the generator is asked
for links that span a VOCABULARY GAP: a decision recorded in one memory and its
consequence recorded later in different words, by a different role, about a
different-sounding thing. Those are the pairs where an association graph can
prove something similarity cannot.

Circularity check, because it is the whole point of the exercise: the RANKER has
no involvement in producing these labels. A model writes a fictional history and
says which events relate to which; recall never votes. That is the same standing
as the mindspace wikilinks (written by agents while working, not by the ranker),
and it is what makes the labels admissible.

Usage:
    DB_NAME=engram_eph_secondbrain ... python3 tests/bench/build_second_brain.py [--count 250]
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from path_memory.db import get_conn
from path_memory.memory import Memory
from path_memory.llm import complete_text

PROJECT = "harrowgate"

# Deliberately far from this codebase's world. Not software, not startups, not
# infrastructure — a domain with its own vocabulary, roles and failure modes, so
# a policy that only works on our corpus has nowhere to hide.
DOMAIN = """the Harrowgate Repertory Theatre, a 340-seat producing theatre in a
northern English market town: productions and casting, the resident company,
touring, the grade-II listed building and its endless maintenance, Arts Council
funding rounds, box office and audience development, the youth programme, the
bar and catering operation, front-of-house staffing, and the board."""

BATCH_PROMPT = """You are writing the working memory of a theatre's operations
team — the notes people actually keep about {domain}

Write {n} SEPARATE memory entries as a JSON array. Each entry:
  {{"subject": "...", "body": "...", "relates_to": <index or null>}}

RULES:
- "subject" is a short distinctive label, 8-16 words, saying what makes THIS
  entry different from its neighbours. Never a generic category.
- "body" is 80-200 words of specific operational detail: names, dates, sums of
  money, seat counts, supplier names, decisions and their reasons.
- Entries must be about DIFFERENT things. Vary across productions, building,
  funding, staff, audience, bar, board, touring, youth programme.
- Roughly {links} of them must set "relates_to" to the index (0-based) of an
  EARLIER entry in this array — the earlier decision, incident or person that
  this one is a consequence of.

THE RULE ABOUT relates_to — CALIBRATION MATTERS MORE THAN DISTANCE. The pair
must be connected through a SHARED CONCRETE THREAD that both entries name: the
same production, the same person, the same room, the same supplier, the same
funding round. Describe them from different angles and different roles, so the
wording differs — but the shared thread must be present in BOTH, or the link is
unfindable by anyone and proves nothing.

Good: a boiler deferral that names the Ellis Wing, and a costume complaint that
also names the Ellis Wing. Different vocabulary, one anchor in common.
Bad: a boiler deferral and a costume complaint with nothing shared at all — that
is not a hard case, it is an impossible one.

DO NOT REPEAT what is already in the memory. These subjects already exist, so
write about DIFFERENT events, people and problems:
{existing}

Start numbering from index {start}. Reply with ONLY the JSON array."""


def generate_batch(n, start, links, existing=()):
    from anthropic import Anthropic
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=16000,
        messages=[{"role": "user", "content": BATCH_PROMPT.format(
            domain=DOMAIN, n=n, start=start, links=links,
            existing="\n".join(f"  - {e}" for e in existing) or "  (none yet)")}],
    )
    text = complete_text(msg, what="second-brain batch")
    if not text:
        # A cut-off batch is discarded whole rather than salvaged: half a JSON
        # array parses into nothing useful, and a partial entry would enter the
        # corpus as a truncated memory. Batches are small precisely so losing
        # one costs little.
        return []
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except Exception as exc:
        print(f"  batch parse failed: {exc}", file=sys.stderr)
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=250)
    ap.add_argument("--batch", type=int, default=8)
    args = ap.parse_args()

    # A single bad batch must not end the run. Generated JSON fails to parse
    # occasionally — an unescaped quote inside a body is enough — and the first
    # version treated that as "stop", which silently produced 112 memories when
    # 240 were asked for. Retry a few times, then give up on THAT batch only.
    entries, misses = [], 0
    while len(entries) < args.count and misses < 6:
        want = min(args.batch, args.count - len(entries))
        # A third of each batch carries a link. Enough labelled pairs to score
        # on, not so many that the corpus reads as nothing but cross-references.
        # Feed back what already exists. Without this, independent batches
        # reinvent the same story beats — the first run produced three separate
        # "wardrobe mould" memories and three "unexplained ticket surge" ones,
        # which then filled every result set with siblings and made the corpus
        # unusable as ground truth.
        got = generate_batch(want, len(entries), max(1, want // 3),
                             existing=[e.get("subject", "") for e in entries[-60:]])
        if not got:
            misses += 1
            print(f"  batch failed ({misses}/6), continuing", file=sys.stderr, flush=True)
            continue
        entries.extend(got[:want])
        print(f"  generated {len(entries)}/{args.count}", flush=True)

    # PASS 1 — save every entry WITHOUT its link, so ids exist to point at.
    ids = []
    for i, e in enumerate(entries):
        mid = Memory.save(subject=(e.get("subject") or "")[:300],
                          body=e.get("body") or "",
                          project=PROJECT, tier="curated")
        ids.append(mid)
        if (i + 1) % 25 == 0:
            print(f"  saved {i + 1}/{len(entries)}", flush=True)

    # PASS 2 — write the cross-references in, then RE-EMBED, because the body
    # changed after the vector was computed. Skipping that would leave every
    # linked memory indexed under text it no longer contains.
    from path_memory.embed import embed_one
    conn = get_conn()
    cur = conn.cursor()
    linked = 0
    for i, e in enumerate(entries):
        tgt = e.get("relates_to")
        if tgt is None or not isinstance(tgt, int) or not (0 <= tgt < len(ids)) or tgt == i:
            continue
        cur.execute("SELECT subject, body FROM memories WHERE id = %s", (ids[i],))
        subject, body = cur.fetchone()
        body = f"{body}\n\nFollows from [[{ids[tgt]}]]."
        vec = embed_one(f" — {subject}\n\n{body}")
        cur.execute("UPDATE memories SET body = %s, embedding = %s::vector WHERE id = %s",
                    (body, "[" + ",".join(str(x) for x in vec) + "]", ids[i]))
        linked += 1
    conn.commit()
    cur.close()
    conn.close()
    print(f"\nsaved {len(ids)} memories, {linked} cross-references written")


if __name__ == "__main__":
    main()
