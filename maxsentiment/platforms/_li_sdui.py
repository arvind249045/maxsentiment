"""LinkedIn SDUI helpers: parse comments out of a React-Flight response, and build
the next-page pager request. Ported from the Deepinder reference, self-contained.
"""
import copy
import json
import re
from urllib.parse import quote, urlsplit

PAGED_COMMENTS = "com.linkedin.sdui.pagers.feed.pagedComments"
DETAIL_SCREEN = "com.linkedin.sdui.flagshipnav.feed.UpdateDetail"


# --- state + view helpers ----------------------------------------------------
def state_values(flight):
    result = {}
    for node in flight.index["states"]:
        for state in node.get("modelStates", []):
            try:
                key = state["key"]["key"]["value"]["id"]
                value = state["value"]
                result[key] = value.get(value["$case"])
            except (KeyError, TypeError):
                pass
    return result


def view_name(flight, node):
    spec = flight.deref(node.get("viewTrackingSpecs")) if isinstance(node, dict) else None
    return spec.get("viewName") if isinstance(spec, dict) else None


def tracking_id(flight, node):
    spec = flight.deref(node.get("viewTrackingSpecs")) if isinstance(node, dict) else None
    return spec.get("contentTrackingId") if isinstance(spec, dict) else None


def profile_from(flight, node):
    for item in flight.walk(node, follow=True):
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if item.get("$type", "").endswith("NavigateToUrl"):
            url = item.get("urlValue", {}).get("url")
        if isinstance(url, str):
            url = "https://www.linkedin.com" + url if url.startswith("/") else url
            parsed = urlsplit(url)
            path = parsed.path.strip("/").split("/")
            if parsed.hostname not in ("www.linkedin.com", "linkedin.com") or len(path) < 2 or path[0] not in ("in", "company", "school"):
                continue
            return {"username": path[1], "profile_url": url.split("?")[0].rstrip("/") + "/"}
    return {"username": None, "profile_url": None}


def _reaction_counts(states, urn):
    suffix = "_" + urn
    return {k[:-len(suffix)]: v for k, v in states.items()
            if k.startswith("ReactionType_") and k.endswith(suffix) and isinstance(v, int)}


def parse_comments(flight, post_urn):
    """Return normalized comment dicts from a parsed Flight."""
    states = state_values(flight)
    result = {}
    for node in flight.views("comment-container"):
        key = node.get("componentKey", "")
        if not key.startswith("CommentComponentReference_urn:li:comment:"):
            continue
        urn = key[len("CommentComponentReference_"):]
        m = re.fullmatch(r"urn:li:comment:\(([^,]+),(\d+)\)", urn)
        if not m:
            continue
        own_tracking = tracking_id(flight, node)
        own = [x for x in flight.walk(node, follow=True)
               if isinstance(x, dict) and tracking_id(flight, x) == own_tracking]
        bodies = [flight.text(x) for x in own
                  if view_name(flight, x) in ("comment-commentary", "comment-reply-commentary")]
        body = max(bodies, key=len, default="")
        actor = next((x for x in own if view_name(flight, x) in
                      ("comment-actor-description", "reply-actor-description") and flight.text(x)), None)
        profile = profile_from(flight, actor) if actor else profile_from(flight, node)
        name = None
        for x in flight.walk(node, follow=True):
            if not isinstance(x, dict):
                continue
            label = flight.deref(x.get("aria-label"))
            if isinstance(label, str):
                mm = re.fullmatch(r"View more options for (.+)[’']s comment\.", label)
                if mm:
                    name = mm[1]; break
        counts = _reaction_counts(states, urn)
        record = {"id": urn, "post_id": post_urn,
                  "handle": profile.get("username"), "name": name or profile.get("username"),
                  "headline": None, "text": body, "platform": "linkedin",
                  "like_count": sum(counts.values()) if counts else 0,
                  "reply_count": states.get("replyCountBinding-" + urn) or 0,
                  "is_reply": any(view_name(flight, x) == "comment-reply-commentary" for x in own),
                  "verified": False}
        prev = result.get(urn)
        if prev is None or len(body) > len(prev["text"]):
            result[urn] = record
    return list(result.values())


# --- pagination --------------------------------------------------------------
def pagers(flight):
    found, seen = [], set()
    for value in flight.index["pagination"]:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                continue
        if not isinstance(value, dict) or value.get("$type") != "proto.sdui.actions.requests.PaginationRequest":
            continue
        sig = (value.get("pagerId"), json.dumps(value.get("requestedArguments", {}).get("payload", {}), sort_keys=True))
        if sig not in seen:
            seen.add(sig); found.append(value)
    return found


def request_for(pager, screen_id=DETAIL_SCREEN):
    arguments = copy.deepcopy(pager.get("requestedArguments", {}))
    arguments.update({"states": [], "screenId": screen_id, "knownTemplateIds": []})
    pagination = {k: copy.deepcopy(pager[k]) for k in
                  ("$type", "pagerId", "trigger", "retryCount", "requestedArguments") if k in pager}
    body = {"pagerId": pager["pagerId"], "clientArguments": arguments, "paginationRequest": pagination}
    url = "https://www.linkedin.com/flagship-web/rsc-action/actions/pagination?sduiid=" + quote(pager["pagerId"])
    return url, json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# --- SSR flight extraction ---------------------------------------------------
_REHYDRATE = re.compile(r"window\.__como_rehydration__\s*=\s*(\[.*?\])\s*;?\s*</script>", re.S)


def extract_flight(html):
    """Pull the embedded RSC flight stream out of a LinkedIn SSR page.
    The page carries it as window.__como_rehydration__ = ["row","row",...]."""
    m = _REHYDRATE.search(html)
    if not m:
        return None
    chunks = json.loads(m.group(1))
    return "".join(chunks).encode("utf-8")
