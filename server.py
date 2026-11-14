"""maxsentiment MCP server — drive your own logged-in social sessions from Claude.

Scraping tools harvest to JSONL on disk and return small summaries (so the agent's
context stays light); the intelligence tools read those files back. Cookies are
loaded once per platform and stored under ~/.maxsentiment/, outside any repo.

Run:  OPENAI_API_KEY=...  python server.py        (stdio MCP server)
The OpenAI key is only needed for the classify / tree tools, not for scraping.
"""
import json
import os
import time

from mcp.server.fastmcp import FastMCP

from maxsentiment.cookies import parse_cookies
from maxsentiment.store import save_session, load_session, session_status
from maxsentiment.platforms import client_for, SESSIONLESS
from maxsentiment.urls import resolve as resolve_url
from maxsentiment.intel import (classify_many, propose_question, build_tree, score_comment,
                                 mark_genuine, split_genuine)
from maxsentiment.intel.tree import flatten_leaves

mcp = FastMCP("maxsentiment")

DATA = os.environ.get("MAXSENTIMENT_DIR", os.path.join(os.getcwd(), "maxsentiment_runs"))


def _dir():
    os.makedirs(DATA, exist_ok=True)
    return DATA


def _client(platform):
    if platform.lower() in SESSIONLESS:
        return client_for(platform, {})
    sess = load_session(platform)
    if not sess:
        raise RuntimeError(f"no saved session for {platform!r}; call ms_load_cookies first")
    return client_for(platform, sess["cookies"])


def _read_jsonl(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


@mcp.tool()
def ms_status() -> dict:
    """What platforms are logged in, and is the OpenAI intelligence key present."""
    return {"sessions": session_status(), "openai_key_present": bool(os.environ.get("OPENAI_API_KEY")),
            "data_dir": DATA}


@mcp.tool()
def ms_load_cookies(platform: str, cookies: str) -> dict:
    """Load a platform session from browser-exported cookies (Netscape cookies.txt OR
    Cookie-Editor JSON). Recommend the user the "Get cookies.txt LOCALLY" Chrome
    extension, exported from the platform while logged in. Verifies the session."""
    jar = parse_cookies(cookies)
    save_session(platform, jar, meta={"loaded_at": int(time.time())})
    try:
        who = _client(platform).whoami()
    except Exception as e:
        who = {"ok": False, "error": str(e)[:200]}
    return {"platform": platform, "cookie_names": sorted(jar.keys()), "whoami": who}


@mcp.tool()
def ms_search(platform: str, query: str, limit: int = 12) -> dict:
    """Search a platform for accounts/handles. Surfaces the real account next to
    impersonators (verified flag + follower context)."""
    return _client(platform).search(query, limit=limit)


@mcp.tool()
def ms_harvest(platform: str, username: str, since: str = "", max_posts: int = 12,
               max_comment_pages: int = 80) -> dict:
    """Harvest a user's recent posts and every comment on them to disk.

    `since` is an optional YYYY-MM-DD lower bound. Writes <data>/<platform>_<username>/
    posts.json + comments.jsonl and returns a summary (counts, top posts, file paths).
    Read the comments file afterwards with ms_classify / ms_build_tree."""
    import datetime
    cli = _client(platform)
    since_ts = None
    if since:
        since_ts = int(datetime.datetime.strptime(since, "%Y-%m-%d").replace(
            tzinfo=datetime.timezone.utc).timestamp())
    out = os.path.join(_dir(), f"{platform}_{username}")
    os.makedirs(out, exist_ok=True)
    posts = []
    for p in cli.posts(username, since_ts=since_ts):
        if since_ts and (p.get("taken_at") or 0) < since_ts:
            continue
        posts.append(p)
        if len(posts) >= max_posts:
            break
    json.dump(posts, open(os.path.join(out, "posts.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    n = 0
    with open(os.path.join(out, "comments.jsonl"), "w", encoding="utf-8") as f:
        for p in posts:
            try:
                for c in cli.comments(p["media_id"], max_pages=max_comment_pages):
                    c["post_caption"] = (p.get("caption") or "")[:200]
                    f.write(json.dumps(c, ensure_ascii=False) + "\n"); n += 1
            except Exception as e:
                c = {"error": str(e)[:150], "media_id": p["media_id"]}
    return {"platform": platform, "username": username, "posts": len(posts), "comments": n,
            "posts_file": os.path.join(out, "posts.json"),
            "comments_file": os.path.join(out, "comments.jsonl"),
            "top_posts": sorted([{"media_id": p["media_id"], "caption": (p.get("caption") or "")[:80],
                                  "like_count": p.get("like_count"), "comment_count": p.get("comment_count")}
                                 for p in posts], key=lambda x: -(x["comment_count"] or 0))[:5]}


@mcp.tool()
def ms_post(url: str, max_pages: int = 25) -> dict:
    """Pull every comment/reply on a SINGLE post from its URL (the common ask:
    'here's a link, read the room'). Resolves platform + id from the URL, fetches the
    focal post for context, writes the comments to disk, and returns a summary.
    Then run ms_classify / ms_build_tree on the comments_file."""
    platform, post_id = resolve_url(url)
    if not platform:
        raise RuntimeError("URL has no platform; pass an x.com or instagram.com post link")
    cli = _client(platform)
    out = os.path.join(_dir(), f"{platform}_post_{post_id}")
    os.makedirs(out, exist_ok=True)
    focal = None
    if hasattr(cli, "tweet"):
        try:
            focal = cli.tweet(post_id)
        except Exception as e:
            focal = {"error": str(e)[:150]}
    n = 0
    sample = []
    with open(os.path.join(out, "comments.jsonl"), "w", encoding="utf-8") as f:
        for c in cli.comments(post_id, max_pages=max_pages):
            f.write(json.dumps(c, ensure_ascii=False) + "\n"); n += 1
            if len(sample) < 5:
                sample.append({"handle": c.get("handle"), "text": (c.get("text") or "")[:120]})
    return {"platform": platform, "post_id": post_id, "focal_post": focal, "comments": n,
            "comments_file": os.path.join(out, "comments.jsonl"), "sample": sample}


@mcp.tool()
def ms_classify(infile: str, outfile: str, questions_json: str = "", limit: int = 0) -> dict:
    """Label every row of a comments JSONL with the Decisions API. `questions_json` is
    an optional JSON array of question objects; omit for the default sentiment taxonomy.
    Writes the labeled rows to `outfile` and returns a label breakdown + cost."""
    rows = _read_jsonl(infile)
    if limit:
        rows = rows[:limit]
    questions = json.loads(questions_json) if questions_json else None
    labeled = classify_many(rows, questions, workers=8)
    mark_genuine(labeled, workers=8)  # also tag promo/spam so the breakdown is honest
    with open(outfile, "w", encoding="utf-8") as f:
        for r in labeled:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tokens = sum(r.get("input_tokens", 0) for r in labeled)
    breakdown = {}
    for r in labeled:
        s = r.get("sentiment")
        if s:
            breakdown[s] = breakdown.get(s, 0) + 1
    gen, junk = split_genuine(labeled)
    return {"labeled": len(labeled), "genuine": len(gen), "spam_dropped": len(junk),
            "outfile": outfile, "input_tokens": tokens,
            "approx_cost_usd": round(tokens / 1e6 * 0.10, 4), "sentiment_breakdown": breakdown}


@mcp.tool()
def ms_build_tree(infile: str, context: str, outfile: str, max_depth: int = 4,
                  min_bucket: int = 12, weight_key: str = "reach", drop_spam: bool = True) -> dict:
    """Grow the recursive theme tree over a comments JSONL. `context` describes the
    corpus (e.g. 'comments on Deepinder Goyal's Temple posts'). `weight_key='reach'`
    ranks leaves by effort-weighted reach (default); any numeric field also works;
    '' ranks by count. `drop_spam` (default on) runs the genuine filter first so promo
    junk never hijacks the ranking. Writes the full tree to `outfile`."""
    rows = _read_jsonl(infile)
    n_in = len(rows)
    wk = weight_key or None
    if weight_key == "reach":
        for r in rows:
            r["reach"] = score_comment(r) + 2  # the comment itself counts as a reply (2)
        wk = "reach"
    tree = build_tree(rows, context, max_depth=max_depth, min_bucket=min_bucket,
                      weight_key=wk, drop_spam=drop_spam)
    json.dump(tree, open(outfile, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    leaves = sorted(flatten_leaves(tree), key=lambda x: -x["weight"])
    return {"comments_in": n_in, "kept_genuine": tree["count"], "spam_dropped": n_in - tree["count"],
            "root_weight": tree["weight"], "leaves": len(leaves), "outfile": outfile,
            "top_leaves": [{"path": " > ".join(l["path"]), "count": l["count"], "weight": l["weight"]}
                           for l in leaves[:12]]}


def main():
    mcp.run()


if __name__ == "__main__":
    main()
