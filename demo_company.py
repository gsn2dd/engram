#!/usr/bin/env python3
"""
A demo brain: the working memory of a small fictional company.

Two jobs in one file.

  1. A DEMO you can talk to. The starter memories explain how engram works;
     these show what it is FOR. They are the sort of thing a real team's brain
     accumulates — decisions and the reasons behind them, a root cause, a
     customer complaint, a pricing argument that changed its mind — with the
     reasoning attached rather than just the outcome.

  2. A SELF-TEST. Every question below is answered by exactly one memory, and
     `--verify` checks that recall actually finds it. That exercises the whole
     chain on the customer's own instance with the customer's own key:
     embedding, storage, semantic search, the relevance cliff, and project
     scoping. If this passes, the install works. If it fails, the failure names
     which part broke.

The questions deliberately share almost no vocabulary with the memories that
answer them ("why do they go quiet when it gets cold" finds a memory about
lithium cells and a firmware watchdog). Keyword search cannot do that, which is
the point being demonstrated.

Tidewell Instruments is invented. Any resemblance to a real company is
accidental — this is sample data, not a case study.

    python3 demo_company.py            seed it
    python3 demo_company.py --verify   seed it, then prove recall works
    pm forget-project tidewell --yes   remove every trace of it
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PROJECT = "tidewell"

# (subject, body) — a small company's brain, roughly a year of decisions.
MEMORIES = [
    ("what Tidewell actually sells",
     "We make river water-quality sensors that councils and angling trusts bolt to bridges. "
     "The sensor is not the product — the product is a defensible record that a discharge "
     "happened at a time and place, good enough to put in front of a regulator."),

    ("why we stopped selling the hardware outright",
     "Selling units for 900 pounds each meant every customer became a support burden we were not "
     "paid for, and a broken unit in year three was our reputation and their problem. Moved to "
     "40 pounds per sensor per month including replacement. Revenue halved for two quarters and "
     "then passed the old peak, because renewals stopped depending on someone finding budget."),

    ("the winter dropout, root cause",
     "Units went silent below about minus four degrees and came back on their own in spring, so "
     "for a year we blamed the lithium cells and the cold. The cells were fine. The modem draws "
     "hard for a moment when it wakes, the pack sags under that draw when cold, the brownout "
     "detector trips, and the watchdog reboots mid-transmission — forever. Fix was a 200 "
     "millisecond delay after wake before the modem powers up. Nine lines of firmware."),

    ("what the winter dropout cost us",
     "Fourteen months of intermittent silence across the northern deployments, two councils "
     "declining to renew, and a field engineer sent out eleven times to swap batteries that were "
     "never the problem. The cost was not the bug, it was believing the first plausible "
     "explanation for a year without testing it."),

    ("the mounting bracket complaint",
     "Ashcombe Council's river warden reported that the original bracket needed two people and a "
     "boat to fit, because the bolts faced the water. She was right and had said so twice before "
     "anyone wrote it down. The redesign put the bolts on the bank side; fitting time went from "
     "ninety minutes to twelve, and it is now the thing customers mention first."),

    ("why we do not chase the drinking-water market",
     "Drinking water needs certification we would spend three years and most of our money "
     "obtaining, against incumbents with regulatory relationships older than the company. River "
     "monitoring has no such moat and the buyers are underserved. Staying out is a decision, "
     "not an oversight — revisit only if someone offers to fund the certification."),

    ("the false-positive problem that nearly sank the pilot",
     "The first Ashcombe pilot reported eleven discharge events in a fortnight. Two were real. "
     "The rest were a dairy upstream washing down at the same hour each evening. We had built an "
     "alarm on a threshold when what mattered was the shape of the curve — a discharge rises "
     "sharply and decays slowly, a wash-down is symmetrical."),

    ("what we learned from the dairy",
     "An alert nobody trusts is worse than no alert, because it trains the recipient to ignore "
     "the real one. After the dairy episode we held alerts for a confirming second reading. "
     "Detection got slower by nine minutes and complaints stopped entirely."),

    ("why the data goes to the customer, not to us",
     "Councils asked who owned the readings and we said they did, in writing, before anyone "
     "asked us to. It cost a data-licensing revenue line we had modelled. It also won two "
     "contracts outright, because the alternative vendors would not answer the question."),

    ("the deployment that taught us about tides",
     "The Netherhaven estuary site read wildly for three weeks. Nothing was wrong with the "
     "sensor — the river runs backwards twice a day and we had assumed flow direction was "
     "constant. Estuary sites now need a tide table at install time, and the installer form "
     "asks for it."),

    ("hiring the field engineer before the salesperson",
     "With eleven customers we could not decide between a second salesperson and a field "
     "engineer. Chose the engineer, on the grounds that our churn was caused by units nobody "
     "visited rather than by insufficient pipeline. Churn went from three a year to zero. The "
     "salesperson came eight months later and had an easier job."),

    ("the supplier who changed the cell without telling us",
     "Our pack supplier substituted a cell with the same nominal capacity and a different "
     "internal resistance, which is what turned the cold-weather sag from marginal into a "
     "reboot. They considered it an equivalent part. We now hold the exact cell part number in "
     "the contract and get thirty days' notice of any change."),

    ("why every unit reports its own battery curve",
     "After the winter dropout we stopped trusting a single voltage reading. Each unit now "
     "reports the shape of its discharge over the last week, which shows a failing pack weeks "
     "before it dies and would have shown the cold-weather sag immediately if we had had it."),

    ("the pricing argument we got wrong twice",
     "Priced first on cost-plus, which made large councils look unprofitable when they were our "
     "cheapest customers to serve. Then priced per site, which punished exactly the multi-site "
     "customers we wanted. Landed on per sensor per month with a volume break at twenty, which "
     "is boring and has not needed changing since."),

    ("what the regulator actually accepts as evidence",
     "A reading is not evidence. A reading with a calibration record, a timestamp from a source "
     "the sensor cannot alter, and an unbroken chain of custody is evidence. We spent a quarter "
     "on that chain and it is the reason our data has been used in two prosecutions."),

    ("why we refuse to give councils an API before month three",
     "Every council asks for raw API access on day one and every one that got it early built a "
     "dashboard against a schema we then could not change. Access now opens at month three, by "
     "which point they know which three numbers they actually look at."),

    ("the Ashcombe renewal we nearly lost",
     "Ashcombe declined to renew after the winter of silent units, and renewed six weeks later "
     "when we showed them the root cause, the firmware fix and the eleven wasted engineer "
     "visits, and credited the silent months without being asked. They are now the reference "
     "customer other councils phone."),

    ("what we say when a competitor undercuts us",
     "Nothing about price. We ask what happens when a unit stops reporting — who notices, how "
     "fast, and who pays to visit it. Our whole cost base is built around that answer being "
     "'we do, within a day, and we do'. Customers who do not care about that are not our "
     "customers."),

    ("the two numbers we run the company on",
     "Days of silence per sensor per year, and months from install to first renewal. Revenue is "
     "an outcome of those two. We stopped reporting a growth number internally because it made "
     "people chase installs that then churned."),

    ("why the alerts are text, not a dashboard",
     "River wardens are outdoors and on a phone. A dashboard is something you visit; a text is "
     "something that reaches you. The dashboard exists because procurement asks for one, and it "
     "is used mostly at renewal time."),

    ("the calibration drift nobody wanted to own",
     "Optical sensors drift as the window fouls, and for a while every party assumed another "
     "was handling it. Now a unit compares itself against its own baseline and flags when it is "
     "drifting, rather than waiting for someone to doubt it. Ownership sits with the device "
     "because the device is the only party that is always there."),

    ("what we would do differently from the start",
     "Instrument our own product first. Nearly every expensive lesson — the cold-weather sag, "
     "the fouling drift, the dairy false positives — was invisible to us until we added the "
     "telemetry that would have shown it. We built the product before we built the ability to "
     "see it working."),
]

# (question, fragment of the subject that should answer it)
# These are also the questions printed for the user to try. Deliberately phrased
# the way someone would actually ask, not in the memory's own words.
QUESTIONS = [
    ("why do the sensors go quiet when it gets cold", "winter dropout, root cause"),
    ("who was annoyed about how hard the units were to fit", "mounting bracket complaint"),
    ("should we go after the tap water market", "do not chase the drinking-water"),
    ("what happened with all the fake alarms at the first trial", "false-positive problem"),
    ("who owns the readings we collect", "data goes to the customer"),
    ("we cannot decide between another salesperson and an engineer", "hiring the field engineer"),
    ("a parts supplier swapped a component on us", "supplier who changed the cell"),
    ("how did we end up charging what we charge", "pricing argument we got wrong"),
    ("what makes a measurement stand up in court", "regulator actually accepts as evidence"),
    ("a customer nearly walked after an outage", "Ashcombe renewal we nearly lost"),
    ("someone is cheaper than us, what do we say", "when a competitor undercuts"),
    ("what do we actually measure ourselves on", "two numbers we run the company on"),
    ("the readings drift over time and no one fixes it", "calibration drift nobody wanted"),
    ("biggest regret in how we built this", "would do differently from the start"),
]


def seeded(conn) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM memories WHERE project = %s", (PROJECT,))
    n = cur.fetchone()[0]
    cur.close()
    return n >= len(MEMORIES)


def seed() -> int:
    from path_memory.db import get_conn
    from path_memory.memory import Memory
    conn = get_conn()
    try:
        if seeded(conn):
            print(f"[demo] '{PROJECT}' demo already present ({len(MEMORIES)} memories)")
            return 0
    finally:
        conn.close()

    stored = 0
    for subject, body in MEMORIES:
        try:
            Memory.save(subject=subject, body=body, person=None, project=PROJECT,
                        origin="contribution", tier="curated", source_system="demo")
            stored += 1
            print(f"\r[demo] stored {stored}/{len(MEMORIES)}", end="", file=sys.stderr)
        except Exception as exc:
            print(f"\n[demo] could not store {subject!r}: {exc}", file=sys.stderr)
    print(file=sys.stderr)
    return stored


def verify() -> int:
    """Prove recall works on THIS instance. Returns the number of failures."""
    from path_memory.recall import recall
    print(f"\n  Checking that {len(QUESTIONS)} questions each find their answer.")
    print("  These share almost no words with the memories that answer them —\n"
          "  keyword search cannot do this.\n")
    failures = 0
    for question, expected in QUESTIONS:
        try:
            hits = recall(question, project=PROJECT, limit=3, increment_weight=False)
        except Exception as exc:
            print(f"  FAIL  {question!r}\n        recall raised {type(exc).__name__}: {exc}")
            failures += 1
            continue
        top = hits[0]["subject"] if hits else "(nothing found)"
        if expected.lower() in top.lower():
            print(f"  ok    {question}\n           -> {top}")
        else:
            print(f"  FAIL  {question}\n           -> {top}\n           expected something about: {expected}")
            failures += 1
    print()
    if failures:
        print(f"  {len(QUESTIONS) - failures}/{len(QUESTIONS)} passed, {failures} FAILED.")
        print("  A failure here means recall is not working on this instance — check that the")
        print("  embedding key is set and that it is the same provider that wrote the memories.")
    else:
        print(f"  {len(QUESTIONS)}/{len(QUESTIONS)} passed. Storage, embedding and semantic")
        print("  recall are all working on this instance.")
    return failures


def main() -> int:
    from path_memory.embed import provider_ready
    if not provider_ready():
        print("[demo] no embedding provider configured — set a key first (see: get_started)",
              file=sys.stderr)
        return 2

    seed()
    rc = 0
    if "--verify" in sys.argv:
        rc = 1 if verify() else 0

    print(f"""
  TRY IT YOURSELF — attach your agent and ask it these, in your own words:

{chr(10).join('    ' + q for q, _ in QUESTIONS[:8])}

  Or from the shell:

    pm recall "why do the sensors go quiet when it gets cold" --project {PROJECT}

  The interesting part is that none of those questions use the words the
  memories use. Ask follow-ups, ask something not in the list, ask badly.

  WHEN YOU ARE DONE — remove every trace of the demo:

    pm forget-project {PROJECT} --yes
""")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
