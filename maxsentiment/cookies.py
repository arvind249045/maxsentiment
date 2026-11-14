"""Parse browser-exported cookies into a plain {name: value} dict.

Two formats cover almost every export extension:
  * Netscape cookies.txt  — "Get cookies.txt LOCALLY", "cookies.txt"
  * Cookie-Editor JSON    — Cookie-Editor's Export button (array of {name,value,...})

We never ask for a password. A session cookie — the operator's own, exported by hand —
is all the private web APIs need.
"""
import json


def _from_netscape(text: str) -> dict:
    jar = {}
    for line in text.splitlines():
        line = line.rstrip("\r\n")
        if not line:
            continue
        if line.startswith("#"):
            # curl/wget write httponly cookies as "#HttpOnly_<tab-separated line>"
            if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_"):]
            else:
                continue
        parts = line.split("\t")
        if len(parts) >= 7:
            jar[parts[5]] = parts[6]
    return jar


def _from_cookie_editor(data) -> dict:
    jar = {}
    for c in data:
        if isinstance(c, dict) and "name" in c and "value" in c:
            jar[c["name"]] = c["value"]
    return jar


def parse_cookies(raw: str) -> dict:
    """Accept either a Netscape cookies.txt string or a Cookie-Editor JSON string.

    Returns {name: value}. Raises ValueError if nothing parseable is found.
    """
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("empty cookie text")
    jar = {}
    if raw[0] in "[{":
        data = json.loads(raw)
        if isinstance(data, dict) and "cookies" in data:
            data = data["cookies"]
        jar = _from_cookie_editor(data)
    else:
        jar = _from_netscape(raw)
    if not jar:
        raise ValueError("no cookies found — expected Netscape cookies.txt or Cookie-Editor JSON")
    return jar
