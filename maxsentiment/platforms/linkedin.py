"""LinkedIn client over the SDUI feed API, driven by the operator's own cookies.

Needs li_at + JSESSIONID from a logged-in session (the CSRF token is the JSESSIONID
value, quotes stripped). LinkedIn serves post comments as a server-driven-UI (SDUI)
React-Flight stream. The flow:

  1. GET the post permalink — the SSR page embeds the first page of comments and the
     "pagedComments" pager as a React-Flight stream (window.__como_rehydration__).
  2. Parse that flight for comments + the pager tokens (threadUrn / updateKey).
  3. POST the pager to /flagship-web/rsc-action/actions/pagination for each next page.

A fully fresh session matters — a stale one 302-loops. Comment pages are large
(tens of MB), so this is heavier than the other platforms.
"""
import re

from curl_cffi import requests

from ._rsc import Flight
from . import _li_sdui as sdui

BASE = "https://www.linkedin.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
_ACT_RE = re.compile(r"(?:activity[:-]|urn:li:activity:)(\d{18,20})")


def activity_id_from_url(url):
    m = _ACT_RE.search(url or "")
    return m.group(1) if m else (url if re.fullmatch(r"\d{18,20}", url or "") else None)


class LinkedIn:
    name = "linkedin"
    required_cookies = ("li_at", "JSESSIONID")

    def __init__(self, jar: dict):
        missing = [c for c in self.required_cookies if not jar.get(c)]
        if missing:
            raise ValueError("LinkedIn session is missing cookies: " + ", ".join(missing) +
                             ". Export cookies for linkedin.com while logged in.")
        self.jar = jar
        self.s = requests.Session()
        self.csrf = (jar.get("JSESSIONID") or "").strip('"')
        self._cookie_header = "; ".join(f"{k}={v}" for k, v in jar.items())

    def _headers(self, extra=None):
        h = {"user-agent": UA, "cookie": self._cookie_header, "csrf-token": self.csrf,
             "accept-language": "en-US,en", "referer": BASE + "/feed/"}
        if extra:
            h.update(extra)
        return h

    def whoami(self):
        r = self.s.get(BASE + "/voyager/api/me", headers=self._headers(
            {"accept": "application/vnd.linkedin.normalized+json+2.1",
             "x-restli-protocol-version": "2.0.0"}), impersonate="chrome",
            timeout=30, allow_redirects=False)
        return {"ok": r.status_code == 200, "status": r.status_code}

    def _seed(self, activity_id):
        """Fetch the permalink and return (Flight, first-page comments, pager|None)."""
        r = self.s.get(f"{BASE}/feed/update/urn:li:activity:{activity_id}/",
                       headers=self._headers(), impersonate="chrome", timeout=90, allow_redirects=True)
        if r.status_code != 200:
            raise RuntimeError(f"linkedin permalink {r.status_code} (session may be stale)")
        raw = sdui.extract_flight(r.text)
        if not raw:
            raise RuntimeError("could not find the embedded SDUI flight in the permalink page")
        flight = Flight(raw)
        comments = sdui.parse_comments(flight, f"urn:li:activity:{activity_id}")
        pgs = [p for p in sdui.pagers(flight) if p.get("pagerId") == sdui.PAGED_COMMENTS]
        return flight, comments, (pgs[0] if pgs else None)

    def _page(self, pager, activity_id):
        """POST one pager and return (comments, next_pager|None)."""
        url, body = sdui.request_for(pager)
        r = self.s.post(url, data=body, headers=self._headers(
            {"content-type": "application/json", "accept": "text/x-component"}),
            impersonate="chrome", timeout=120, allow_redirects=False)
        if r.status_code != 200:
            raise RuntimeError(f"linkedin pager {r.status_code}")
        flight = Flight(r.content)
        comments = sdui.parse_comments(flight, f"urn:li:activity:{activity_id}")
        nxt = [p for p in sdui.pagers(flight) if p.get("pagerId") == sdui.PAGED_COMMENTS]
        return comments, (nxt[0] if nxt else None)

    def comments(self, activity_id, max_pages=15):
        """Yield normalized top-level comments for a post (urn:li:activity:<id>)."""
        activity_id = str(activity_id)
        seen = set()
        flight, first, pager = self._seed(activity_id)
        for c in first:
            if c["id"] not in seen and not c.get("is_reply"):
                seen.add(c["id"]); yield c
        pages = 0
        while pager and pages < max_pages:
            batch, pager = self._page(pager, activity_id)
            new = 0
            for c in batch:
                if c["id"] not in seen and not c.get("is_reply"):
                    seen.add(c["id"]); new += 1; yield c
            pages += 1
            if new == 0:
                return
