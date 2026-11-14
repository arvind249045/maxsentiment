"""Grow a recursive semantic theme tree until every leaf states a concrete meaning.

At each bucket the reader PROPOSES one question (propose_question); the Decisions API
LABELS every item in the bucket (classify_many); the bucket splits by label. Any
'uncovered_meaning' escape bucket is reopened and split again. A bucket stops when it
is small, when the tree is deep enough, or when a question fails to divide it — at
which point it is an honest endpoint, described by the path that led to it.

The reader sees only a sample and never the counts; the counts come from the
deterministic classifier. That separation is the whole point.
"""
from .decide import classify_many
from .filter import mark_genuine, split_genuine
from .propose import propose_question

ESCAPE = "uncovered_meaning"
_VAGUE = {"other", "misc", "miscellaneous", "general", "unknown", "remaining", ESCAPE}


def _weight(rows, weight_key):
    if not weight_key:
        return len(rows)
    return sum((r.get(weight_key) or 0) for r in rows)


def build_tree(rows, context, key=None, max_depth=4, min_bucket=12, max_opts=7,
               weight_key=None, workers=8, drop_spam=True, on_event=None, _depth=0, _path=None):
    """Return a nested node:
        {meaning, path, count, weight, kind, children:[...]}
    `rows` is a list of {id, text, [weight_key]}. `context` describes the corpus.

    When `drop_spam` is set (default), the corpus is run through the genuine filter
    once at the root, so promo/ad/giveaway junk never reaches the reach ranking.
    """
    rows = list(rows)
    path = _path or []
    if drop_spam and _depth == 0:
        mark_genuine(rows, key=key, workers=workers)
        rows, _junk = split_genuine(rows)
    node = {"meaning": path[-1] if path else "all comments", "path": path,
            "count": len(rows), "weight": _weight(rows, weight_key), "kind": "branch", "children": []}

    # Base cases: too small, too deep, or nothing to read.
    if len(rows) < min_bucket or _depth >= max_depth or len(rows) < 2:
        node["kind"] = "leaf"
        return node

    try:
        questions = propose_question(rows, name="branch",
                                     context=context + " | path: " + " > ".join(path),
                                     min_opts=4, max_opts=max_opts)
    except Exception as e:
        node["kind"] = "leaf"; node["note"] = f"propose failed: {str(e)[:120]}"
        return node

    labeled = classify_many(rows, questions, key=key, workers=workers)
    buckets = {}
    for r in labeled:
        buckets.setdefault(r.get("branch") or ESCAPE, []).append(r)

    # No real split (everything landed in one bucket) -> honest endpoint.
    real = {k: v for k, v in buckets.items()}
    if len(real) <= 1:
        node["kind"] = "leaf"
        return node

    if on_event:
        on_event({"event": "split", "path": path, "into": len(real),
                  "count": len(rows), "labels": {k: len(v) for k, v in real.items()}})

    # Recurse into each child (escape buckets reopen just like the rest).
    children = []
    for label, group in sorted(real.items(), key=lambda kv: -_weight(kv[1], weight_key)):
        child = build_tree(group, context, key=key, max_depth=max_depth, min_bucket=min_bucket,
                           max_opts=max_opts, weight_key=weight_key, workers=workers,
                           on_event=on_event, _depth=_depth + 1, _path=path + [label])
        children.append(child)
    node["children"] = children
    return node


def flatten_leaves(node, out=None):
    """Return the leaves of a tree as flat rows: {path, meaning, count, weight}."""
    out = out if out is not None else []
    if not node.get("children"):
        out.append({"path": node["path"], "meaning": node["meaning"],
                    "count": node["count"], "weight": node["weight"]})
    else:
        for c in node["children"]:
            flatten_leaves(c, out)
    return out
