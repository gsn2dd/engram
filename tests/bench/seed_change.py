#!/usr/bin/env python3
"""
Seed the theatre brain with FACTS THAT CHANGED, and facts pinned to the calendar.

WHY THIS IS SEPARATE FROM THE CORPUS. The generated corpus is 200 memories about
a theatre, and it demonstrates that recall works. It cannot demonstrate the two
behaviours a vector store structurally does not have, because nothing in it ever
changed and nothing in it is pinned to a date:

    superseded pairs:            0
    calendar-anchored memories:  0

These are written BY HAND rather than generated. A demo turns on the exact
wording of a before-and-after pair, and eight pairs is not worth a model call —
nor worth the risk of a generator producing two facts that do not actually
contradict each other, which would make the demo a lie.

WHAT EACH PAIR IS FOR:
  * supersession — RAG has no concept of currency. Store "the bar closes at 11",
    later store "the bar closes at midnight", and a vector store returns both,
    quite possibly the stale one first if it matches the query better. Nothing
    in the index knows one replaced the other. Engram ranks the replacement
    above the original, keeps the original recallable for audit, and says which
    is which.
  * temporal anchors — a memory about a date should read as upcoming, current or
    past depending on TODAY, re-derived at recall time rather than frozen in the
    prose. A vector store returns "next month's deadline" forever.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from path_memory.memory import Memory
from path_memory.db import get_conn

PROJECT = "harrowgate"

# (old_subject, old_body, new_subject, new_body)
# The pair must genuinely CONTRADICT — same question, different answer — or the
# demo shows nothing. "More detail added later" is not supersession.
CHANGED = [
    ("Bar last orders set at 11pm for the autumn season",
     "Front of house confirmed last orders at 11pm across the autumn season, "
     "matching the licence in force since 2024. Duty managers were briefed and "
     "the printed table cards were reordered to show 11pm.",
     "Bar last orders moved to midnight after the licence variation",
     "The licence variation was granted, so last orders move from 11pm to "
     "midnight from October. This replaces the 11pm figure briefed earlier in "
     "the season — table cards and the duty manager briefing both need redoing."),

    ("Arts Council uplift provisionally indicated at £180,000",
     "The relationship manager indicated a provisional uplift of £180,000 for "
     "the next funding period, subject to the full assessment panel. Budget "
     "planning for the studio programme was drafted against that figure.",
     "Arts Council award confirmed at £142,000, not the indicated £180,000",
     "The panel confirmed £142,000 — £38,000 below the provisional figure the "
     "budget was drafted against. The studio programme scale has to be revisited; "
     "the earlier £180,000 number should not be used for planning."),

    ("Winter Kestrel tour fourth venue confirmed as Skipton",
     "Skipton's Century Theatre confirmed as the fourth venue on the winter "
     "Kestrel tour, with get-in on the Monday and three performances.",
     "Skipton withdrew from the Kestrel tour; Ilkley takes the fourth slot",
     "Skipton's Century Theatre withdrew over a stage floor loading limit. "
     "Ilkley King's Hall takes the fourth slot instead, same week, two "
     "performances rather than three. Skipton is no longer on the tour."),

    ("Standard evening ticket held at £18 for the season",
     "The board agreed to hold the standard evening ticket at £18 for the "
     "season, absorbing the increase rather than passing it to audiences.",
     "Standard evening ticket rises to £21 from January",
     "After the funding shortfall the board reversed the hold: the standard "
     "evening ticket goes to £21 from January. The £18 figure agreed earlier "
     "no longer applies."),

    ("Company rehearsals to run in Studio 2 through the autumn",
     "Studio 2 allocated as the main rehearsal room for the autumn company, "
     "with the Green Room kept free for fittings and notes.",
     "Rehearsals moved out of Studio 2 to the Green Room after the leak",
     "Water ingress through the Studio 2 ceiling forced rehearsals into the "
     "Green Room for the rest of the autumn. Studio 2 is out of use, so the "
     "earlier allocation no longer stands."),
]

# (subject, body, anchor_start, anchor_end) — one comfortably past, one running
# right now, one clearly ahead, so a single run shows all three tenses.
ANCHORED = [
    ("Press night for The Seagull",
     "Press night for The Seagull, with regional critics and the Arts Council "
     "relationship manager attending. Reception desk to hold twelve comps.",
     "2026-05-14", "2026-05-14"),
    ("Summer run of Brassed Off in the Main House",
     "Brassed Off runs in the Main House across three weeks, including two "
     "relaxed performances and one captioned matinee.",
     "2026-08-10", "2026-08-30"),
    ("Arts Council National Portfolio submission deadline",
     "The National Portfolio submission closes at noon. Finance need the "
     "audited accounts and the audience data pack in the week before.",
     "2026-11-03", "2026-11-03"),
]


def main():
    conn = get_conn()
    cur = conn.cursor()
    made = 0
    for old_s, old_b, new_s, new_b in CHANGED:
        old_id = Memory.save(subject=old_s, body=old_b, project=PROJECT, tier="curated")
        new_id = Memory.save(subject=new_s, body=new_b, project=PROJECT, tier="curated")
        # The link is what a vector store cannot express: not "these are
        # similar" but "this one replaced that one".
        Memory.supersede(old_id, new_id)
        made += 2
        print(f"  superseded [{old_id}] -> [{new_id}]  {new_s[:52]}")

    for subj, body, start, end in ANCHORED:
        mid = Memory.save(subject=subj, body=body, project=PROJECT, tier="curated",
                          temporal_anchor_start=start, temporal_anchor_end=end)
        made += 1
        print(f"  anchored   [{mid}] {start}..{end}  {subj[:48]}")

    cur.close()
    conn.close()
    print(f"\n{made} memories added: {len(CHANGED)} supersession pairs, "
          f"{len(ANCHORED)} calendar-anchored")


if __name__ == "__main__":
    main()
