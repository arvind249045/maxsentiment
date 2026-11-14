"""The junk filter — what makes the reach ranking intelligent instead of hijacked.

Big accounts' reply/comment threads fill with promo: trading pitches, giveaways,
channel plugs, affiliate spam. Unfiltered, that junk out-reaches the real audience
and poisons every theme. One Decisions predicate marks each comment genuine-or-not;
the tree drops the junk before it ranks anything.
"""
from .decide import classify_many

GENUINE_Q = [{"type": "predicate", "name": "genuine",
    "instructions": "True if this is a genuine reaction, opinion, question, or argument "
    "from a real person engaging with the subject of the post. False if it is promotion, "
    "an advertisement, a trading/stock/crypto/forex pitch, a giveaway or airdrop, a "
    "self-channel or self-account plug, affiliate/referral spam, or empty filler."}]


def mark_genuine(rows, key=None, workers=10, text_key="text"):
    """Set r['genuine'] (bool) on every row lacking it. On a classifier error we keep
    the row (genuine=True) — the filter removes junk, it never silently drops signal."""
    todo = [r for r in rows if "genuine" not in r]
    if todo:
        labeled = classify_many(todo, GENUINE_Q, key=key, workers=workers, text_key=text_key)
        for r, l in zip(todo, labeled):
            g = l.get("genuine")
            r["genuine"] = True if (g is None or l.get("error")) else bool(g)
    return rows


def split_genuine(rows):
    """Return (genuine, junk). Rows default to genuine when unmarked."""
    gen = [r for r in rows if r.get("genuine", True)]
    junk = [r for r in rows if not r.get("genuine", True)]
    return gen, junk
