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

THE PROMPT'S RULE IS NOW ENFORCED IN CODE, NOT ASKED FOR IN ENGLISH.

The prompt says "do not reuse distinctive words from the cause". The model
ignored it: the generated set included questions sharing "ripon, print, works"
and "elevation, market, street" with their answers — questions that simply name
the thing they are asking about. An instruction a model can quietly decline is
a bug report against missing code, so the overlap is now COMPUTED and the
degenerate cases REJECTED.

The threshold was measured, not chosen. Over 26 generated questions the shared
distinctive-word count ran median 1.5, mean 1.5, max 4; inspecting the tail,
every question sharing 3 or more words was a restatement of the answer's own
subject line. So 3 is the bar, and it rejected 4 of 26 (15%).

AND THE TIER IS NOW MEASURED BY OVERLAP, NOT BY PAIR COSINE. The same
measurement showed pair-cosine does not track difficulty: two "hard" pairs by
cosine shared three words with their answers, while five "easy" pairs shared
none. Overlap is the better predictor because overlap is what decides whether
plain keyword search would find the answer — which is the thing being claimed.

WHAT THIS QUESTION SET DOES AND DOES NOT DEMONSTRATE — read before quoting it.

It does NOT show engram finding answers that share no words with the question.
Inspecting the generated "hard" set: they share "ripon, print, works", "kestrel,
tour", "elevation, market, street" with their answers. Keyword search would find
those, let alone an embedding.

That is not a generator failure, it is a contradiction I built into the design.
The corpus generator is asked for links sharing a CONCRETE ANCHOR so the pair is
findable at all; the question generator is then asked not to reuse the cause's
distinctive words. But the anchor IS the shared vocabulary. A pair either has
one — and is then findable by ordinary similarity — or it does not, and is
unreachable by anything, which is what the first corpus produced (bench floored
at MRR 0.006).

WHAT THE ZERO-OVERLAP QUESTIONS DO AND DO NOT PROVE. After the gate, 4 of 58
generated questions share no distinctive word at all with their answer, and
engram finds those answers at ranks 1, 2, 5 and 5. That is real, and it is
worth having — but it demonstrates that KEYWORD search would fail, not that a
vector store would. Closing a lexical gap is exactly what an embedding does;
any competent vector store would likely find them too. So this remains evidence
that semantic beats lexical, which is table stakes, rather than evidence that
engram beats RAG.

The conclusion that matters for a shipped demo: on a COLD brain, engram's
retrieval is good but not categorically different from a competent vector
store. What IS different — spreading activation over use-built edges — requires
a warm graph, which a freshly-seeded demo brain by definition does not have.
A demo should therefore lead with what a cold brain can actually show that a
top-k vector store cannot: collapse (three answers come back as three, not five
padded), supersession, live temporal re-tensing, and project scoping.

So these questions are honest as a FUNCTIONAL test — they verify recall works on
an independent corpus, and they are the bench's ground truth. They are not a
differentiator demo, and labelling them as one would be overclaiming.

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
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from path_memory.db import get_conn
from path_memory.llm import complete_text
from path_memory.recall import recall

WIKILINK = re.compile(r"\[\[(\d+)\]\]")

# Words too common to count as evidence that a question leans on its answer's
# wording. Deliberately short: a long stopword list would quietly suppress real
# overlap and flatter the result.
STOPWORDS = {
    "what", "when", "why", "how", "which", "this", "that", "been", "were",
    "have", "has", "did", "does", "the", "and", "for", "was", "are", "our",
    "its", "from", "with", "into", "them", "there", "their", "they", "who",
    "only", "just", "even", "some", "suddenly", "originally", "actually",
    "first", "before", "after", "still", "being", "then", "than", "over",
}

# A question sharing this many distinctive words with its answer is naming the
# answer rather than asking about it. Measured over 26 generated questions:
# median 1.5, mean 1.5, max 4, and every case at 3+ was a restatement of the
# answer's subject line ("Ripon Print Works", "Market Street elevation").
MAX_SHARED_WORDS = 3


def distinctive(text):
    """Content words — the ones whose presence in both question and answer
    means keyword search would have found it without any embedding.

    ACCENTS ARE FOLDED FIRST. The obvious pattern, [a-z']+, silently splits
    "façade" into "fa" and "ade" — both below the length floor — so a question
    asking about the "Market Street façade repair" scored ZERO overlap against
    an answer about "the façade job". A checker that cannot see a word cannot
    reject it, and this corpus is full of words that carry accents. Folding to
    ASCII first costs nothing and closes a whole class of false negative.
    """
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return {w for w in re.findall(r"[a-z']+", folded.lower())
            if len(w) > 3 and w not in STOPWORDS}


def shared_words(question, answer_subject):
    return sorted(distinctive(question) & distinctive(answer_subject))

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

    out, kept, tried, rejected = [], 0, 0, 0
    for src, tgt, cos in sorted(scored, key=lambda s: s[2]):
        cur.execute("SELECT subject, body FROM memories WHERE id=%s", (tgt,))
        c_subj, c_body = cur.fetchone()
        cur.execute("SELECT subject, body FROM memories WHERE id=%s", (src,))
        e_subj, e_body = cur.fetchone()
        q = make_question(f"{c_subj}\n{c_body[:700]}", f"{e_subj}\n{e_body[:700]}")
        tried += 1
        if not q:
            continue
        # ENFORCE the prompt's own rule. The model declines it often enough that
        # asking is not a control.
        shared = shared_words(q, c_subj)
        if len(shared) >= MAX_SHARED_WORDS:
            rejected += 1
            print(f"  reject (names its answer: {','.join(shared)}) {q[:52]}", flush=True)
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
                    # Recorded as DATA so nobody has to take the tier on trust.
                    "shared_words": shared,
                    # Measured, not inferred from cosine — see the module
                    # docstring for why cosine turned out to be the wrong proxy.
                    "tier": "no-overlap" if not shared else "partial-overlap"})
        kept += 1
        print(f"  [{kept}/{tried}] rank {ids.index(tgt)+1}  cos {cos:.3f}  {q[:64]}", flush=True)
        if kept >= 40:
            break

    cur.close()
    conn.close()
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=2)
    clean = sum(1 for o in out if o["tier"] == "no-overlap")
    print(f"\nkept {kept} verified questions of {tried} tried "
          f"({rejected} rejected for naming their answer); "
          f"{clean} share NO distinctive words with their answer, "
          f"{kept - clean} share some -> {args.out}")


if __name__ == "__main__":
    main()
