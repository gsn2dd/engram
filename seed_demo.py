#!/usr/bin/env python3
"""
Seed a small demo brain, so a fresh Engram boots with something to recall instead
of an empty box. It holds one coherent little story — the design of a children's
bedtime-story app — so semantic recall and use-built associations have something
to show. (The memories are the *why* behind the product, the way a real team's
brain would remember its own decisions.)

Runs only when ENGRAM_SEED_DEMO is truthy, and is idempotent (skips if the demo
project already exists). It uses *your* keys to embed + generate perspectives —
exactly like any real memory — so nothing is baked into the image.

Try, once it's up (the query shares almost no words with the memory it finds):
  pm recall "what stops a child staring at a phone at night"   # -> audio, screen dark
  pm recall "will it ever run out of things to hear"           # -> the seasonal batches
  pm recall "is it safe for a young child"                     # -> the two-storyteller check
  pm recall "why would a parent pick this over a rival"        # -> the familiar voice
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from path_memory.memory import Memory
from path_memory.db import get_conn

DEMO = [
    ("the guiding promise", "Everything we make for children has to be genuinely good for them — it earns its place by helping, never by grabbing attention. No adverts, no tracking, ever.", "storytime"),
    ("screens at bedtime", "At night the phone plays only sound and dims to black, resting face-down, so a child listens in the dark and drifts off instead of staring at a lit screen.", "storytime"),
    ("how a story should end", "Every tale winds gently down and finishes — no cliffhangers, nothing that plays on by itself afterwards — because the whole point is that the little one falls asleep.", "storytime"),
    ("the shape of every tale", "Beneath the pirates and the animals, each story quietly builds a hopeful outlook: trying again after a stumble, naming a big feeling, being kind. The lesson lives in what the characters do, never in a lecture.", "storytime"),
    ("the send-off before sleep", "After the tale comes a short, calm look ahead — on a school night, picture tomorrow going smoothly and feeling capable; at the weekend, look forward to time to play and rest.", "storytime"),
    ("a line we will not cross", "The bedtime encouragement is always reassurance, that you can handle whatever comes, and never pressure to perform — because pressure is the very worry we are trying to soothe away.", "storytime"),
    ("keeping the shelf full", "There is always something new and it never runs dry: fresh tales are added in small seasonal batches for each age, a little faster than a child can listen, so the collection only deepens as the years pass.", "storytime"),
    ("two storytellers", "Before any tale is ever heard, a careful reader checks it is gentle, kind, and suitable for a young child of that age; a quicker helper drafts the many tales it starts from.", "storytime"),
    ("what cannot be copied", "Families come back, and rivals struggle to compete, not for the words — anyone can generate those now — but for one warm, familiar voice reading in their own language, night after night.", "storytime"),
    ("a small app, a deep library", "Tales arrive only when they are asked for, and the device remembers which have already been heard, so there is always something new without carrying a mountain of files.", "storytime"),
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
    print(f"seeded {len(DEMO)} demo memories (project=demo). Try: pm recall \"what stops a child staring at a phone at night\"")


if __name__ == "__main__":
    main()
