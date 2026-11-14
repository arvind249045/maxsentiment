"""Instagram client over the private web API, driven by the operator's own cookies.

Needs three cookies from a logged-in session: sessionid, csrftoken, ds_user_id.
The GraphQL feed also needs the page's fb_dtsg / lsd tokens — we read those straight
out of the logged-in homepage HTML, so no MITM capture is required.

Read-only and gentle: small pages, jittered delays, the operator's own session.
"""
import json
import random
import re
import secrets
import time
import uuid

from curl_cffi import requests

BASE = "https://www.instagram.com"
APP_ID = "936619743392459"  # public Instagram web app id
# doc_ids for the GraphQL queries. These drift occasionally; override via the
# Instagram(jar, posts_doc_id=..., search_doc_id=...) constructor if they start 400-ing.
POSTS_DOC_ID = "29290744380560118"
SEARCH_DOC_ID = "27706427925724183"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class Instagram:
    name = "instagram"
    required_cookies = ("sessionid", "csrftoken", "ds_user_id")

    def __init__(self, jar: dict, posts_doc_id: str = POSTS_DOC_ID, search_doc_id: str = SEARCH_DOC_ID):
        missing = [c for c in self.required_cookies if not jar.get(c)]
        if missing:
            raise ValueError(
                "Instagram session is missing cookies: " + ", ".join(missing) +
                ". Export cookies for instagram.com while logged in.")
        self.jar = jar
        self.posts_doc_id = posts_doc_id
        self.search_doc_id = search_doc_id
        self.s = requests.Session()
        self._tokens = None
        self.headers = {
            "user-agent": UA,
            "x-ig-app-id": APP_ID,
            "x-csrftoken": jar.get("csrftoken", ""),
            "x-requested-with": "XMLHttpRequest",
            "x-asbd-id": "129477",
            "x-ig-www-claim": "0",
            "accept": "*/*",
            "referer": BASE + "/",
        }

    # --- low level -----------------------------------------------------------
    def _get(self, path, params=None):
        return self.s.get(BASE + path, params=params, headers=self.headers,
                          cookies=self.jar, impersonate="chrome", timeout=30)

    def _tokens_from_page(self):
        """Pull fb_dtsg / lsd out of the logged-in homepage HTML (cached)."""
        if self._tokens is not None:
            return self._tokens
        r = self.s.get(BASE + "/", headers={"user-agent": UA}, cookies=self.jar,
                       impersonate="chrome", timeout=30)
        html = r.text
        def grab(*patterns):
            for p in patterns:
                m = re.search(p, html)
                if m:
                    return m.group(1)
            return None
        lsd = grab(r'"LSD",\[\],\{"token":"([^"]+)"', r'"lsd":"([^"]+)"')
        dtsg = grab(r'"DTSGInitData",\[\],\{"token":"([^"]+)"', r'"dtsg":\{"token":"([^"]+)"')
        viewer = grab(r'"username":"([^"]+)","is_private"', r'"CONFIG",\[\],\{[^}]*"viewer_id":"([^"]+)"')
        if not (lsd and dtsg):
            raise RuntimeError("could not read fb_dtsg/lsd from the homepage — session may be expired")
        self._tokens = {"lsd": lsd, "fb_dtsg": dtsg, "viewer": viewer}
        return self._tokens

    def _graphql(self, friendly, doc_id, variables):
        """POST a GraphQL doc_id query with the session's fb_dtsg/lsd. Returns data dict."""
        tok = self._tokens_from_page()
        headers = dict(self.headers)
        headers["content-type"] = "application/x-www-form-urlencoded"
        headers["x-fb-lsd"] = tok["lsd"]
        headers["x-fb-friendly-name"] = friendly
        headers["origin"] = BASE
        form = {"av": self.jar.get("ds_user_id", ""), "fb_dtsg": tok["fb_dtsg"], "lsd": tok["lsd"],
                "variables": json.dumps(variables), "fb_api_caller_class": "RelayModern",
                "fb_api_req_friendly_name": friendly, "doc_id": doc_id, "server_timestamps": "true"}
        r = self.s.post(BASE + "/api/graphql", data=form, headers=headers,
                        cookies=self.jar, impersonate="chrome", timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"graphql {friendly} {r.status_code}: {r.text[:200]}")
        body = r.json()
        if body.get("errors"):
            raise RuntimeError(f"graphql {friendly} errors: {json.dumps(body['errors'])[:200]}")
        return body.get("data") or {}

    # --- public surface ------------------------------------------------------
    def whoami(self):
        """Confirm the session is alive; returns the logged-in viewer username/id."""
        try:
            tok = self._tokens_from_page()
            return {"ok": True, "user_id": self.jar.get("ds_user_id"), "username": tok.get("viewer")}
        except Exception as e:
            return {"ok": False, "user_id": self.jar.get("ds_user_id"), "error": str(e)[:200]}

    def search(self, query, limit=20):
        """Blended top search (accounts + hashtags) via the web GraphQL search box.

        Returns real accounts for the query — including verified status and the
        follower context string, which is enough to spot impersonators next to
        the real handle."""
        variables = {"data": {"context": "blended", "include_reel": "true", "query": query,
                     "rank_token": f"{int(time.time()*1000)}|{secrets.token_hex(32)}",
                     "search_session_id": str(uuid.uuid4()), "search_surface": "web_top_search"},
                     "hasQuery": True}
        data = self._graphql("PolarisSearchBoxRefetchableQuery", self.search_doc_id, variables)
        conn = data.get("xdt_api__v1__fbsearch__topsearch_connection") or {}
        users = []
        for row in conn.get("users", [])[:limit]:
            u = row.get("user", row)
            users.append({"username": u.get("username"), "full_name": u.get("full_name"),
                          "user_id": str(u.get("pk") or ""), "verified": u.get("is_verified"),
                          "followers": u.get("search_social_context")})
        return {"users": users,
                "hashtags": [h.get("name") or (h.get("hashtag") or {}).get("name") for h in conn.get("hashtags", [])]}

    def profile(self, username):
        """Profile header for an exact username (derived from the search results,
        since web_profile_info is session-restricted). Returns None if not found."""
        for u in self.search(username, limit=20)["users"]:
            if (u.get("username") or "").lower() == username.lower():
                return u
        return None

    def posts(self, username, max_pages=12, since_ts=None):
        """Yield a user's media (newest first) via the web GraphQL feed.

        Stops once a page runs older than since_ts (unix seconds), or at max_pages.
        """
        after = None
        for _ in range(max_pages):
            variables = {
                "after": after, "before": None,
                "data": {"count": 12, "include_reel_media_seen_timestamp": True,
                         "include_relationship_info": True, "latest_besties_reel_media": True,
                         "latest_reel_media": True},
                "first": 12, "include_multi_captions": True, "last": None, "username": username,
                "__relay_internal__pv__PolarisMultiCaptionCarouselEnabledrelayprovider": True,
                "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider": True,
                "__relay_internal__pv__PolarisSEOIsCrawlerrelayprovider": False,
                "__relay_internal__pv__PolarisThreadsStyleCommentsEnabledrelayprovider": False,
                "__relay_internal__pv__PolarisReelsRecoDebugOverlayEnabledrelayprovider": False,
            }
            data = self._graphql("PolarisProfilePostsTabContentQuery_connection",
                                  self.posts_doc_id, variables)
            conn = (data.get("xdt_api__v1__feed__user_timeline_graphql_connection")
                    or (data.get("user", {}) or {}).get("edge_owner_to_timeline_media"))
            if not conn:
                raise RuntimeError("unexpected feed shape; doc_id may be stale — pass posts_doc_id=")
            edges = conn.get("edges", [])
            oldest = None
            for e in edges:
                n = e.get("node", e)
                oldest = n.get("taken_at", oldest)
                yield self._norm_post(n)
            pi = conn.get("page_info", {})
            if since_ts and oldest and oldest < since_ts:
                return
            if not pi.get("has_next_page"):
                return
            after = pi.get("end_cursor")
            time.sleep(random.uniform(1.2, 2.4))

    @staticmethod
    def _norm_post(n):
        cap = n.get("caption") or {}
        caption = cap.get("text") if isinstance(cap, dict) else (cap or "")
        u = n.get("user") or n.get("owner") or {}
        return {"media_id": str(n.get("pk") or n.get("id") or ""), "code": n.get("code") or n.get("shortcode"),
                "taken_at": n.get("taken_at"), "owner": u.get("username"),
                "caption": caption or "", "like_count": n.get("like_count"),
                "comment_count": n.get("comment_count"), "media_type": n.get("media_type")}

    def comments(self, media_id, max_pages=80):
        """Yield normalized top-level comments for a media, paginating via next_min_id.

        Each comment carries a like_count and reply_count so engagement can be
        effort-weighted downstream (a reply costs more than a like)."""
        min_id = None
        for _ in range(max_pages):
            params = {"can_support_threading": "true", "permalink_enabled": "false"}
            if min_id:
                params["min_id"] = min_id
            r = self._get(f"/api/v1/media/{media_id}/comments/", params)
            if r.status_code != 200:
                raise RuntimeError(f"comments {r.status_code}: {r.text[:200]}")
            d = r.json()
            for c in d.get("comments", []):
                u = c.get("user") or {}
                yield {"id": str(c.get("pk")), "media_id": str(media_id),
                       "handle": u.get("username"), "name": u.get("full_name"),
                       "verified": u.get("is_verified"), "text": c.get("text", ""),
                       "like_count": c.get("comment_like_count", 0),
                       "reply_count": c.get("child_comment_count", 0),
                       "created_at": c.get("created_at"), "platform": "instagram"}
            if not (d.get("has_more_comments") or d.get("has_more_headload_comments")):
                return
            min_id = d.get("next_min_id")
            if not min_id:
                return
            time.sleep(random.uniform(0.8, 1.8))
