"""YouTube client over the internal `youtubei/v1` (innertube) API.

Video comments are public, so this needs no login — it uses the web client's own
embedded API key and the comments continuation token from the watch page, exactly as
youtube.com does when you scroll. A cookie jar is accepted for parity with the other
platforms but is not required.

Comment engagement: likeCount x1 + replyCount x2 (effort-weighted downstream).
"""
import json
import re
import random
import time

from curl_cffi import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
BASE = "https://www.youtube.com"
# bypass the EU consent interstitial without logging in
CONSENT = {"SOCS": "CAI", "CONSENT": "YES+"}


def _count(s):
    """'2.1K' -> 2100, '1,234' -> 1234, '' -> 0."""
    if s is None:
        return 0
    s = str(s).strip().replace(",", "")
    if not s:
        return 0
    mult = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    if s[-1] in mult:
        try:
            return int(float(s[:-1]) * mult[s[-1]])
        except ValueError:
            return 0
    try:
        return int(float(re.sub(r"[^\d.]", "", s) or 0))
    except ValueError:
        return 0


class YouTube:
    name = "youtube"
    required_cookies = ()  # public

    def __init__(self, jar: dict | None = None):
        self.jar = dict(CONSENT, **(jar or {}))
        self.s = requests.Session()
        self._key = None
        self._cv = None

    def _watch(self, video_id):
        """Fetch the watch page; return (innertube_key, client_version, comment_token)."""
        r = self.s.get(f"{BASE}/watch?v={video_id}",
                       headers={"user-agent": UA, "accept-language": "en-US,en"},
                       cookies=self.jar, impersonate="chrome", timeout=30)
        h = r.text
        km = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', h)
        cvm = re.search(r'"clientVersion":"([0-9.]+)"', h)
        dm = re.search(r"ytInitialData\s*=\s*(\{.*?\});</script>", h, re.S) or \
            re.search(r"ytInitialData\s*=\s*(\{.*?\});", h, re.S)
        if not (km and cvm and dm):
            raise RuntimeError("could not read innertube key / ytInitialData from the watch page")
        self._key, self._cv = km.group(1), cvm.group(1)
        data = json.loads(dm.group(1))
        token = self._first_comment_token(data)
        if not token:
            raise RuntimeError("no comments section found (comments may be disabled on this video)")
        return token

    @staticmethod
    def _first_comment_token(data):
        found = []
        def walk(x):
            if isinstance(x, dict):
                isr = x.get("itemSectionRenderer")
                if isr and "comment" in str(isr.get("sectionIdentifier", "")):
                    for c in isr.get("contents", []):
                        t = (((c.get("continuationItemRenderer") or {}).get("continuationEndpoint")
                              or {}).get("continuationCommand") or {}).get("token")
                        if t:
                            found.append(t)
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        walk(data)
        return found[0] if found else None

    def _next(self, token):
        body = {"context": {"client": {"clientName": "WEB", "clientVersion": self._cv,
                                       "hl": "en", "gl": "US"}}, "continuation": token}
        r = self.s.post(f"{BASE}/youtubei/v1/next?key={self._key}", json=body,
                        headers={"user-agent": UA, "content-type": "application/json",
                                 "accept-language": "en-US,en"},
                        cookies=self.jar, impersonate="chrome", timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"next {r.status_code}: {r.text[:200]}")
        return r.json()

    @staticmethod
    def _top_continuation_items(d):
        """Merge the continuationItems of every comment-targeted action (the first
        reload holds only the header; the second holds the comments + next token)."""
        items = []
        for ep in d.get("onResponseReceivedEndpoints", []):
            action = ep.get("reloadContinuationItemsCommand") or ep.get("appendContinuationItemsAction")
            if action and "comment" in str(action.get("targetId", "")):
                items.extend(action.get("continuationItems", []))
        if items:
            return items
        for ep in d.get("onResponseReceivedEndpoints", []):  # fallback: any action
            action = ep.get("reloadContinuationItemsCommand") or ep.get("appendContinuationItemsAction")
            if action:
                items.extend(action.get("continuationItems", []))
        return items

    def comments(self, video_id, max_pages=40):
        """Yield normalized top-level comments for a video, paginating the list."""
        token = self._watch(video_id)
        for _ in range(max_pages):
            d = self._next(token)
            muts = (((d.get("frameworkUpdates") or {}).get("entityBatchUpdate") or {}).get("mutations") or [])
            for mu in muts:
                p = (mu.get("payload") or {}).get("commentEntityPayload")
                if not p:
                    continue
                props = p.get("properties") or {}
                if str(props.get("replyLevel", 0)) not in ("0", "None"):
                    continue  # top-level only
                author = p.get("author") or {}
                tb = p.get("toolbar") or {}
                yield {"id": props.get("commentId"), "video_id": video_id,
                       "handle": (author.get("displayName") or "").lstrip("@"),
                       "name": author.get("displayName"), "verified": author.get("isVerified", False),
                       "text": (props.get("content") or {}).get("content", ""),
                       "like_count": _count(tb.get("likeCountNotliked") or tb.get("likeCountLiked")),
                       "reply_count": _count(tb.get("replyCount")),
                       "created_at": props.get("publishedTime"), "platform": "youtube"}
            # next page token = trailing continuationItemRenderer in the main list
            nxt = None
            for it in self._top_continuation_items(d):
                cir = it.get("continuationItemRenderer")
                if cir:
                    nxt = (((cir.get("continuationEndpoint") or {}).get("continuationCommand") or {}).get("token"))
            if not nxt:
                return
            token = nxt
            time.sleep(random.uniform(0.6, 1.4))

    def whoami(self):
        return {"ok": True, "note": "YouTube comments are public; no login required"}
