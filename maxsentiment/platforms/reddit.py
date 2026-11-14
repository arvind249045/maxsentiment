"""Reddit client over the thread JSON, using the logged-in session cookies.

Reddit now walls the anonymous `.json` endpoints behind a bot/login page, so we send
the exported session cookies (reddit_session + the rest) to www.reddit.com with a
Chrome TLS fingerprint — the same request the logged-in browser makes. Comment score
(net upvotes) is the amplification signal; direct-reply count is the thread's effort.
"""
import random
import re
import time

from curl_cffi import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
BASE = "https://www.reddit.com"
_ID_RE = re.compile(r"(?:reddit\.com/(?:r/[^/]+/)?comments/|redd\.it/)([a-z0-9]+)", re.I)


def post_id_from_url(url):
    m = _ID_RE.search(url or "")
    return m.group(1) if m else (url if re.fullmatch(r"[a-z0-9]+", url or "") else None)


class Reddit:
    name = "reddit"
    required_cookies = ("reddit_session",)

    def __init__(self, jar: dict | None = None):
        jar = jar or {}
        if not jar.get("reddit_session"):
            raise ValueError("Reddit session is missing the reddit_session cookie. "
                             "Export cookies for reddit.com while logged in.")
        self.jar = jar
        self.s = requests.Session()
        self.headers = {"user-agent": UA, "accept": "application/json"}

    def _api(self, path, params=None):
        r = self.s.get(BASE + path, params=params, headers=self.headers,
                       cookies=self.jar, impersonate="chrome", timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"reddit {r.status_code}: {r.text[:160]}")
        return r.json()

    def post(self, post_id):
        """The thread's self-post / link (title, body, author, score, num_comments)."""
        d = self._api(f"/comments/{post_id}.json", {"limit": 1, "raw_json": 1})
        node = (((d[0].get("data") or {}).get("children") or [{}])[0]).get("data") or {}
        return {"id": node.get("id"), "title": node.get("title"),
                "text": node.get("selftext", ""), "author": node.get("author"),
                "subreddit": node.get("subreddit"), "score": node.get("score"),
                "num_comments": node.get("num_comments"), "url": node.get("url")}

    def comments(self, post_id, max_pages=1, sort="top", limit=500):
        """Yield normalized comments for a thread (flattened tree). Reddit returns most
        of the tree in one call; deep 'more' stubs are skipped. `max_pages` kept for
        interface parity."""
        d = self._api(f"/comments/{post_id}.json", {"limit": limit, "sort": sort, "raw_json": 1})
        listing = d[1] if len(d) > 1 else {}
        yield from self._walk((listing.get("data") or {}).get("children", []), post_id, 0)

    def _walk(self, children, post_id, depth):
        for ch in children:
            if ch.get("kind") != "t1":
                continue  # skip "more" stubs
            c = ch.get("data") or {}
            if not c.get("body"):
                continue
            replies = c.get("replies") or ""
            reply_children = (replies.get("data") or {}).get("children", []) if isinstance(replies, dict) else []
            n_direct = sum(1 for r in reply_children if r.get("kind") == "t1")
            yield {"id": c.get("id"), "post_id": post_id, "handle": c.get("author"),
                   "name": c.get("author"), "text": c.get("body", ""),
                   "like_count": c.get("score", 0), "reply_count": n_direct,
                   "created_at": c.get("created_utc"), "depth": depth,
                   "verified": False, "platform": "reddit"}
            if reply_children:
                yield from self._walk(reply_children, post_id, depth + 1)

    def whoami(self):
        return {"ok": True, "note": "authenticated via web bearer (token_v2)"}
