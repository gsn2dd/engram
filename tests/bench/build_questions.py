#!/usr/bin/env python3
"""
Turn the second brain's cross-references into a DEMONSTRABLE question set.

THE POINT OF THE QUESTIONS, which is different from the point of the corpus.
A test brain that only proves "the search works" demonstrates nothing a vector
store could not do. What engram claims is that it finds the right memory when
the question and the answer share almost no words — so the questions have to be
built to show precisely that, or the demo is indistinguishable from RAG.

So each question is generated FROM A LINKED PAIR: it is phrased in the language
of the CONSEQUENCE and its true answer is the CAUSE. "Why are the costumes going
mouldy?" should return the memory about deferring the boiler replacement — a
memory containing neither "costume" nor "mouldy".

TIERED, because a demo needs to establish competence before it shows off:
  easy — the pair is semantically close; any decent vector search finds it.
         These prove the thing is working at all.
  hard — the pair sits below the median pair-cosine. These are the ones a
         plain embedding search misses, and they are the actual argument.

ONLY VERIFIED QUESTIONS SHIP. Every candidate is run against the brain and kept
only if the intended answer actually comes back. Shipping a question that does
not work would be worse than shipping none: the first thing a buyer does is try
it, and the first thing they would learn is that it fails.
"""
import argparse
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from path_memory.db import get_conn
from path_memory.llm import complete_text
from path_memory.recall import recall

WIKILINK = re.compile(r"\[\[(\d+)\]\]")

PROMPT = """Two entries from a theatre's operational memory are connected: the
second happened BECAUSE of the first.

CAUSE (the answer we want someone to find):
{cause}

CONSEQUENCE (what someone would notice first):
{effect}

Write ONE natural question, 8-18 words, that a person at this theatre would
actually type when facing the CONSEQUENCE and wanting to understand why.

Hard rules:
- Use the vocabulary of the CONSEQUENCE, not the cause.
- Do NOT reuse distinctive words from the cause — no names, no equipment, no
  sums of money that appear in it. The whole point is that the question and its
  answer share almost no words.
- It must be answerable by the cause. Someone reading the cause should think
  "yes, that explains it".

Reply with only the question."""


def make_question(cause, effect):
    from anthropic import Anthropic
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model="claude-sonnet-5", max_tokens=100,
        messages=[{"role": "user", "content": PROMPT.format(cause=cause, effect=effect)}])
    text = complete_text(msg, what="demo question", quiet=True)
    return text.strip().strip('"') if text else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tests/bench/second_brain_questions.json")
    ap.add_argument("--limit", type=int, default=5)
    args = ap.parse_args()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""SELECT id, subject, body FROM memories
                    WHERE body ~ '\\[\\[[0-9]+\\]\\]' AND archived = false""")
    pairs = []
    for mid, subject, body in cur.fetchall():
        for t in WIKILINK.findall(body):
            pairs.append((mid, int(t)))

    # Pair distance decides the tier. Doing this from the vectors rather than by
    # eye keeps "hard" an measured property rather than an opinion.
    scored = []
    for src, tgt in pairs:
        cur.execute("""SELECT 1 - (a.embedding <=> b.embedding)
                         FROM memories a, memories b WHERE a.id=%s AND b.id=%s""", (src, tgt))
        row = cur.fetchone()
        if row and row[0] is not None:
            scored.append((src, tgt, float(row[0])))
    if not scored:
        print("no linked pairs found", file=sys.stderr)
        return
    median = statistics.median(s[2] for s in scored)
    print(f"{len(scored)} linked pairs, median pair-cosine {median:.4f}")

    out, kept, tried = [], 0, 0
    for src, tgt, cos in sorted(scored, key=lambda s: s[2]):
        cur.execute("SELECT subject, body FROM memories WHERE id=%s", (tgt,))
        c_subj, c_body = cur.fetchone()
        cur.execute("SELECT subject, body FROM memories WHERE id=%s", (src,))
        e_subj, e_body = cur.fetchone()
        q = make_question(f"{c_subj}\n{c_body[:700]}", f"{e_subj}\n{e_body[:700]}")
        tried += 1
        if not q:
            continue
        # VERIFY on the real engine before keeping it.
        hits = recall(q, limit=args.limit, increment_weight=False)
        ids = [h["id"] for h in hits]
        if tgt not in ids:
            continue
        out.append({"question": q, "answer_id": tgt,
                    "answer_subject": c_subj,
                    "rank": ids.index(tgt) + 1,
                    "pair_cosine": round(cos, 4),
                    "tier": "hard" if cos < median else "easy"})
        kept += 1
        print(f"  [{kept}/{tried}] rank {ids.index(tgt)+1}  cos {cos:.3f}  {q[:64]}", flush=True)
        if kept >= 40:
            break

    cur.close()
    conn.close()
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=2)
    hard = sum(1 for o in out if o["tier"] == "hard")
    print(f"\nkept {kept} verified questions of {tried} tried "
          f"({hard} hard, {kept - hard} easy) -> {args.out}")


if __name__ == "__main__":
    main()
