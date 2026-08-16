#!/usr/bin/env python3
"""
pm — Engram CLI
Usage:
  pm save "subject" "body" [--person entity] [--anchor-start YYYY-MM-DD] [--anchor-end YYYY-MM-DD]
  pm recall "query" [--person entity] [--noun type] [--limit N]
  pm decay
  pm paths <entity>
  pm temporal-sweep [--limit N]
"""
import sys, os, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from path_memory import Memory, recall as _recall, run_decay, consolidate, needs_retensing_sweep


def cmd_save(args):
    mid = Memory.save(
        subject=args.subject, body=args.body, person=args.person or None,
        temporal_anchor_start=args.anchor_start or None,
        temporal_anchor_end=args.anchor_end or None,
    )
    print(f"Saved memory {mid}")


def cmd_recall(args):
    results = _recall(args.query, person=args.person, noun_type=args.noun, limit=args.limit)
    if not results:
        print("No memories found.")
        return
    for r in results:
        print(f"\n[{r['id']}] [{r['noun_type']}] {r['person'] or '—'} — {r['subject']}")
        print(f"     score:{r['score']:.3f}  weight:{r['weight']:.3f}  accessed:{r['access_count']}x")
        print(f"     {r['body'][:200].replace(chr(10),' ')}{'...' if len(r['body'])>200 else ''}")


def cmd_decay(args):
    decayed, archived = run_decay()
    print(f"Decayed: {decayed}  Archived: {archived}")


def cmd_consolidate(args):
    """The self-organising pass: compact co-recall edges into the path graph,
    decay/prune unused nodes and edges. Run periodically (the container loops it)."""
    summary = consolidate()
    print("Consolidated: " + "  ".join(f"{k}={v}" for k, v in summary.items()))


def cmd_paths(args):
    mems = Memory.list_by_entity(args.entity)
    if not mems:
        print(f"No memories for entity: {args.entity}")
        return
    print(f"\nStrongest paths for [{args.entity}]:")
    for m in mems:
        print(f"  [{m['id']}] w={m['weight']:.3f} ({m['access_count']}x) — {m['subject']}")


def cmd_temporal_sweep(args):
    """List calendar-anchored memories with their live-computed tense status."""
    rows = needs_retensing_sweep(limit=args.limit)
    if not rows:
        print("No calendar-anchored memories found.")
        return
    for r in rows:
        window = r["temporal_anchor_start"]
        if r["temporal_anchor_end"] and r["temporal_anchor_end"] != r["temporal_anchor_start"]:
            window = f"{r['temporal_anchor_start']} → {r['temporal_anchor_end']}"
        print(f"\n[{r['id']}] {r['person'] or '—'} — {r['subject']}  ({window})  STATUS: {r['temporal_status'].upper()}")
        print(f"     {r['body'][:160].replace(chr(10), ' ')}{'...' if len(r['body']) > 160 else ''}")


def cmd_forget_project(args):
    """Delete every memory in a project. Used to remove the starter memories once
    they have served their purpose — a starter brain that cannot be cleanly
    removed is contamination rather than a welcome."""
    from path_memory.db import get_conn
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM memories WHERE project = %s", (args.project,))
    n = cur.fetchone()[0]
    if not n:
        print(f"No memories in project '{args.project}'.")
        cur.close(); conn.close(); return
    if not args.yes:
        # Deleting memories is not undoable, so require the intent to be stated.
        print(f"This will permanently delete {n} memories in project '{args.project}'.")
        print(f"Re-run with --yes to confirm:  pm forget-project {args.project} --yes")
        cur.close(); conn.close(); return
    cur.execute("DELETE FROM memories WHERE project = %s", (args.project,))
    conn.commit()
    print(f"Deleted {n} memories from project '{args.project}'.")
    cur.close(); conn.close()


def cmd_demo(args):
    """Seed a fictional company's brain and prove recall works on this instance."""
    import subprocess, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    argv = [sys.executable, os.path.join(root, "demo_company.py")]
    if args.verify:
        argv.append("--verify")
    raise SystemExit(subprocess.call(argv))


def cmd_dream(args):
    """Run one dreaming pass: age doorways, read new memories for subjects,
    back-fill them, summarise. Bounded; safe on a timer."""
    from path_memory.dream import dream
    import json as _json
    print(_json.dumps(dream(project=args.project, llm_budget=args.budget), indent=2, default=str))


p = argparse.ArgumentParser(prog="pm")
sub = p.add_subparsers(dest="cmd")

s  = sub.add_parser("save");     s.add_argument("subject"); s.add_argument("body"); s.add_argument("--person")
s.add_argument("--anchor-start", help="YYYY-MM-DD — set if this claim's tense depends on the calendar (e.g. an event date)")
s.add_argument("--anchor-end", help="YYYY-MM-DD — defaults to --anchor-start for single-day events")
r  = sub.add_parser("recall");   r.add_argument("query"); r.add_argument("--person"); r.add_argument("--noun"); r.add_argument("--limit", type=int, default=5)
sub.add_parser("decay")
sub.add_parser("consolidate")
pa = sub.add_parser("paths");    pa.add_argument("entity")
ts = sub.add_parser("temporal-sweep"); ts.add_argument("--limit", type=int, default=50)
fp = sub.add_parser("forget-project"); fp.add_argument("project"); fp.add_argument("--yes", action="store_true")
dm = sub.add_parser("demo"); dm.add_argument("--verify", action="store_true")
dr = sub.add_parser("dream"); dr.add_argument("--project"); dr.add_argument("--budget", type=int, default=12)
bn = sub.add_parser("bench"); bn.add_argument("--health", action="store_true")
bn.add_argument("--use-signal", dest="use_signal", action="store_true")
bn.add_argument("--limit", type=int, default=10)


def cmd_bench(a):
    """--health is the cheap daily canary (no labels, exits non-zero on FAIL);
    --use-signal reports whether enough use has been attributed to judge the
    use-signal rung; bare `pm bench` runs the full policy ladder, which needs a
    brain with [[id]] wikilinks between memories to score against."""
    from path_memory import bench
    if getattr(a, "use_signal", False):
        r = bench.use_signal_readiness()
        print(f"[use-signal] events={r['events']} attributed={r['attributed']} "
              f"(of which judged-useless={r['attributed_empty']}) "
              f"use_marks={r['memory_use_marks']}\n  {r['verdict']}")
        return
    if a.health:
        r = bench.health_probe()
        print(f"[health] n={r['n']} hit@5={r['hit@5']:.2f} hit@10={r['hit@10']:.2f} "
              f"avg_rank={r['avg_rank']} -> {r['verdict']}")
        raise SystemExit(0 if r["verdict"] == "OK" else 1)
    bench.run(limit=a.limit)


def main():
    args = p.parse_args()
    {
        "save": cmd_save, "recall": cmd_recall, "decay": cmd_decay, "paths": cmd_paths,
        "consolidate": cmd_consolidate, "temporal-sweep": cmd_temporal_sweep,
        "forget-project": cmd_forget_project, "dream": cmd_dream, "demo": cmd_demo,
        "bench": cmd_bench,
    }.get(args.cmd, lambda _: p.print_help())(args)


if __name__ == "__main__":
    main()
