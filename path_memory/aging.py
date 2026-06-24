from .db import get_conn
from .links import compact_links, decay_links


def run_decay(decay_factor: float = 0.95, days_inactive: int = 7) -> int:
    """Decay weights on memories not accessed recently."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""UPDATE memories SET weight = weight * %s
            WHERE last_accessed < now() - interval '{days_inactive} days'
              AND archived = false AND weight > 0""",
        (decay_factor,),
    )
    decayed = cur.rowcount

    cur.execute(
        """UPDATE memories SET archived = true
           WHERE weight < 0.01 AND archived = false
             AND last_accessed IS NOT NULL"""
    )
    archived = cur.rowcount

    conn.commit()
    cur.close(); conn.close()
    return decayed, archived


def run_never_accessed_aging(days_old: int = 90) -> int:
    """Archive memories that were never retrieved after N days."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""UPDATE memories SET archived = true
            WHERE last_accessed IS NULL
              AND created_at < now() - interval '{days_old} days'
              AND archived = false"""
    )
    archived = cur.rowcount
    conn.commit()
    cur.close(); conn.close()
    return archived


def run_edge_aging(decay_factor: float = 0.95, days_inactive: int = 7, prune_below: float = 0.02):
    """Fold raw traversal footprints into path_edge_summary, then decay and
    prune edges that haven't been walked recently -- the edge-graph
    equivalent of run_decay() for nodes. Call this on the same schedule as
    the other aging functions."""
    conn = get_conn()
    edges_updated, footprints_folded = compact_links(conn)
    decayed, pruned = decay_links(conn, decay_factor=decay_factor,
                                   days_inactive=days_inactive, prune_below=prune_below)
    conn.close()
    return edges_updated, footprints_folded, decayed, pruned


def consolidate():
    """The full periodic consolidation pass — what makes the brain *self-organise
    over time*. It compacts raw co-recall footprints into the path graph (which
    is what spreading-activation reads), decays node weights and edges that have
    gone unused, and archives what has faded. Schedule it to run periodically;
    the container runs it on a loop (see entrypoint.sh). Returns a summary dict."""
    nodes_decayed, nodes_archived = run_decay()
    edges_updated, footprints_folded, edges_decayed, edges_pruned = run_edge_aging()
    never_archived = run_never_accessed_aging()
    return {
        "nodes_decayed": nodes_decayed,
        "nodes_archived": nodes_archived,
        "edges_compacted": edges_updated,
        "footprints_folded": footprints_folded,
        "edges_decayed": edges_decayed,
        "edges_pruned": edges_pruned,
        "never_accessed_archived": never_archived,
    }
