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
from path_memory import Memory, recall as _recall, run_decay, needs_retensing_sweep


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


p = argparse.ArgumentParser(prog="pm")
sub = p.add_subparsers(dest="cmd")

s  = sub.add_parser("save");     s.add_argument("subject"); s.add_argument("body"); s.add_argument("--person")
s.add_argument("--anchor-start", help="YYYY-MM-DD — set if this claim's tense depends on the calendar (e.g. an event date)")
s.add_argument("--anchor-end", help="YYYY-MM-DD — defaults to --anchor-start for single-day events")
r  = sub.add_parser("recall");   r.add_argument("query"); r.add_argument("--person"); r.add_argument("--noun"); r.add_argument("--limit", type=int, default=5)
sub.add_parser("decay")
pa = sub.add_parser("paths");    pa.add_argument("entity")
ts = sub.add_parser("temporal-sweep"); ts.add_argument("--limit", type=int, default=50)

def main():
    args = p.parse_args()
    {
        "save": cmd_save, "recall": cmd_recall, "decay": cmd_decay, "paths": cmd_paths,
        "temporal-sweep": cmd_temporal_sweep,
    }.get(args.cmd, lambda _: p.print_help())(args)


if __name__ == "__main__":
    main()
