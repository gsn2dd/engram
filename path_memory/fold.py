"""
Fold a JSON structure into the brain — and reassemble it back out.

"Attach a JSON string" — hand engram a JSON blob (a config, a record, an export)
and each leaf value becomes a recallable memory keyed by its dotted path, so you
can later ask the brain about its contents in natural language. This is the
bridge between the structured-data lineage (JSON in) and the agent-memory
lineage (semantic recall out).

`fold_json` is the way in; `recall_json` is the way back out — it gathers the
folded leaves for a scope and rebuilds the original nested object. Each leaf is
stored as  subject = its path (e.g. "business.hours.mon"),  body = "<path>:
<json-encoded value>"  — the value is JSON-encoded so the exact type (string,
number, bool, null) round-trips. Perspectives default OFF for folds (leaves are
short key/values and the literal embedding is enough), and a node cap bounds
cost on large blobs — both are tunable.
"""
import json as _json
import re

from .memory import Memory
from .db import get_conn

_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def fold_json(data, person=None, project=None, perspectives=False, max_nodes=200):
    """Recursively fold parsed-or-string JSON into memories. Returns created ids."""
    if isinstance(data, (str, bytes, bytearray)):
        data = _json.loads(data)

    ids = []

    def walk(obj, path):
        if len(ids) >= max_nodes:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")
        else:
            subject = path or "root"
            ids.append(Memory.save(
                subject=subject,
                body=f"{subject}: {_json.dumps(obj)}",
                person=person,
                project=project,
                perspectives=perspectives,
            ))

    walk(data, "")
    return ids


def _parse_path(path):
    """'a.b[0].c' -> ['a', 'b', 0, 'c'] (str = dict key, int = list index)."""
    tokens = []
    for m in _TOKEN.finditer(path):
        if m.group(1) is not None:
            tokens.append(m.group(1))
        else:
            tokens.append(int(m.group(2)))
    return tokens


def _set_path(root, tokens, value):
    cur = root
    for i, tok in enumerate(tokens):
        last = i == len(tokens) - 1
        nxt = tokens[i + 1] if not last else None
        if isinstance(tok, int):
            while len(cur) <= tok:
                cur.append(None)
            if last:
                cur[tok] = value
            else:
                if cur[tok] is None:
                    cur[tok] = [] if isinstance(nxt, int) else {}
                cur = cur[tok]
        else:
            if last:
                cur[tok] = value
            else:
                if cur.get(tok) is None:
                    cur[tok] = [] if isinstance(nxt, int) else {}
                cur = cur[tok]
    return root


def recall_json(person=None, project=None):
    """Reassemble JSON previously folded via fold_json back into its nested
    object, scoped by project and/or person. The inverse of fold_json.

    Assumes an object (dict) root — the common case for configs/records. Only
    rows that look like folded leaves ("<subject>: <json>") are used, so regular
    memories sharing the scope are ignored."""
    clauses, params = ["archived = false"], []
    if person is not None:
        clauses.append("person = %s"); params.append(person)
    if project is not None:
        clauses.append("project = %s"); params.append(project)

    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT subject, body FROM memories WHERE " + " AND ".join(clauses) + " ORDER BY id", params)
    rows = cur.fetchall()
    cur.close(); conn.close()

    root = {}
    for subject, body in rows:
        prefix = f"{subject}: "
        if not body.startswith(prefix):
            continue
        try:
            value = _json.loads(body[len(prefix):])
        except (ValueError, TypeError):
            continue
        _set_path(root, _parse_path(subject), value)
    return root
