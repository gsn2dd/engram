"""
Weighted-edge path memory.

Two layers, deliberately split (LSM-tree style):

  memory_links       — raw, append-only footprints. Every traversal is just
                        another row. No uniqueness, no locking, nothing to
                        keep consistent. A trace, not an object — ethereal,
                        just flow and direction.

  path_edge_summary  — compacted, fast-read edge weights. compact_links()
                        periodically folds raw footprints into one row per
                        (from_id, to_id, link_type), so retrieval never has
                        to count a growing pile of raw rows. Strength uses
                        the same diminishing-returns shape as node weight
                        (see HISTORY.md's observer-weight formula): a path
                        walked a lot keeps gaining but never runs away
                        unboundedly.

decay_links() ages and prunes summary edges that haven't been walked in a
while, mirroring aging.py's node decay/archive.

spreading_activate() is the retrieval-time payoff: given a set of seed
memory ids (e.g. top cosine hits from recall()), it walks the *compacted*
edge graph outward a few hops, accumulating activation that decays per hop.
This is how a memory linked-by-use, but nowhere near semantically similar,
can still surface — something cosine similarity alone will never find.
"""
from .db import get_conn


def record_traversal(conn, from_id, to_id, link_type="temporal_sequence"):
    """Append-only footprint. No conflict handling on purpose -- repeats just
    pile up; compact_links() is what turns the pile into a weight."""
    if from_id == to_id:
        return
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO memory_links (from_id, to_id, link_type, strength) VALUES (%s, %s, %s, 1.0)",
        (from_id, to_id, link_type),
    )
    conn.commit()
    cur.close()


def compact_links(conn=None):
    """Fold every raw memory_links row into path_edge_summary, then delete
    the folded raw rows so the footprint log stays bounded. Returns
    (edges_updated, footprints_folded). Opens its own connection if none
    is supplied, mirroring aging.run_decay()'s style."""
    owns_conn = conn is None
    conn = conn or get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, from_id, to_id, link_type, created_at FROM memory_links ORDER BY id")
    rows = cur.fetchall()
    if not rows:
        cur.close()
        if owns_conn:
            conn.close()
        return 0, 0

    groups = {}
    for link_id, from_id, to_id, link_type, created_at in rows:
        key = (from_id, to_id, link_type)
        g = groups.setdefault(key, {"count": 0, "last": created_at, "ids": []})
        g["count"] += 1
        g["ids"].append(link_id)
        if created_at and (g["last"] is None or created_at > g["last"]):
            g["last"] = created_at

    for (from_id, to_id, link_type), g in groups.items():
        cur.execute(
            """INSERT INTO path_edge_summary (from_id, to_id, link_type, strength, hop_count, last_walked, updated_at)
               VALUES (%s, %s, %s, 0, 0, %s, now())
               ON CONFLICT (from_id, to_id, link_type) DO NOTHING""",
            (from_id, to_id, link_type, g["last"]),
        )
        cur.execute(
            """UPDATE path_edge_summary SET
                 strength    = strength + %s,
                 hop_count   = hop_count + %s,
                 last_walked = GREATEST(last_walked, %s),
                 updated_at  = now()
               WHERE from_id = %s AND to_id = %s AND link_type = %s""",
            (sum(1.0 / (n + 2) for n in range(g["count"])), g["count"], g["last"],
             from_id, to_id, link_type),
        )

    folded_ids = [i for g in groups.values() for i in g["ids"]]
    cur.execute("DELETE FROM memory_links WHERE id = ANY(%s)", (folded_ids,))
    conn.commit()
    cur.close()
    if owns_conn:
        conn.close()
    return len(groups), len(folded_ids)


def decay_links(conn=None, decay_factor=0.95, days_inactive=7, prune_below=0.02):
    """Age down edges not walked recently; prune the ones that fade out.
    Mirrors aging.run_decay() for nodes."""
    owns_conn = conn is None
    conn = conn or get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""UPDATE path_edge_summary SET strength = strength * %s
            WHERE last_walked < now() - interval '{days_inactive} days' AND strength > 0""",
        (decay_factor,),
    )
    decayed = cur.rowcount

    cur.execute("DELETE FROM path_edge_summary WHERE strength < %s", (prune_below,))
    pruned = cur.rowcount

    conn.commit()
    cur.close()
    if owns_conn:
        conn.close()
    return decayed, pruned


def spreading_activate(conn, seed_ids, hops=2, decay=0.5, limit=10):
    """Walk path_edge_summary outward from seed_ids, accumulating activation
    that decays per hop. Edge strength scales how much activation passes
    through. Returns [{id, subject, activation}], excluding the seeds
    themselves, sorted by activation desc."""
    if not seed_ids:
        return []
    cur = conn.cursor()

    activation = {sid: 1.0 for sid in seed_ids}
    frontier = {sid: 1.0 for sid in seed_ids}

    for hop in range(hops):
        if not frontier:
            break
        cur.execute(
            """SELECT from_id, to_id, strength FROM path_edge_summary
               WHERE from_id = ANY(%s) OR to_id = ANY(%s)""",
            (list(frontier.keys()), list(frontier.keys())),
        )
        edges = cur.fetchall()
        next_frontier = {}
        for from_id, to_id, strength in edges:
            for src, dst in ((from_id, to_id), (to_id, from_id)):
                if src in frontier:
                    passed = frontier[src] * strength * (decay ** (hop + 1))
                    if passed < 1e-4:
                        continue
                    activation[dst] = activation.get(dst, 0.0) + passed
                    next_frontier[dst] = next_frontier.get(dst, 0.0) + passed
        frontier = next_frontier

    for sid in seed_ids:
        activation.pop(sid, None)
    if not activation:
        cur.close()
        return []

    ids = sorted(activation, key=activation.get, reverse=True)[:limit]
    cur.execute(
        "SELECT id, subject FROM memories WHERE id = ANY(%s) AND archived = false",
        (ids,),
    )
    subjects = dict(cur.fetchall())
    cur.close()
    return [
        {"id": i, "subject": subjects[i], "activation": round(activation[i], 4)}
        for i in ids if i in subjects
    ]
