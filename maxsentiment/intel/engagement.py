"""Effort-weighted engagement.

A like is a tap; a comment is someone who stopped to write; a quote is someone who
wrote AND rebroadcast to their own followers. Weighting by effort is what flips the
"loud minority" into view: a theme can be small by headcount yet huge by reach.

    like / favorite      x1
    reply / comment      x2
    repost / retweet     x2
    quote                x3
"""
WEIGHTS = {"like": 1, "favorite": 1, "reply": 2, "comment": 2,
           "repost": 2, "retweet": 2, "quote": 3}


def effort_score(like=0, reply=0, repost=0, quote=0) -> int:
    like = like or 0; reply = reply or 0; repost = repost or 0; quote = quote or 0
    return like * WEIGHTS["like"] + reply * WEIGHTS["reply"] + repost * WEIGHTS["repost"] + quote * WEIGHTS["quote"]


def score_comment(c: dict) -> int:
    """Reach of a single comment/reply across platforms.

    The comment itself is the author's effort (its own weight is folded in by the
    caller when counting items); this scores the reactions it attracted.
    Instagram: like_count + reply_count. X: fav + reply + rt + quote."""
    return effort_score(
        like=c.get("like_count", c.get("fav", 0)),
        reply=c.get("reply_count", c.get("reply", 0)),
        repost=c.get("rt", 0),
        quote=c.get("quote", 0),
    )
