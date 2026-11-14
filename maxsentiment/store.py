"""Per-platform session store under ~/.maxsentiment/ — outside any repo.

A session is just the cookie jar plus a little metadata. It lives in the operator's
home directory, never in the project, so it can never be committed by accident.
"""
import json
import os
import time

DIR = os.path.join(os.path.expanduser("~"), ".maxsentiment")


def _path(platform: str) -> str:
    safe = "".join(c for c in platform if c.isalnum() or c in "-_")
    return os.path.join(DIR, f"{safe}.json")


def save_session(platform: str, jar: dict, meta: dict | None = None) -> dict:
    os.makedirs(DIR, exist_ok=True)
    rec = {"platform": platform, "cookies": jar, "saved_at": int(time.time()), "meta": meta or {}}
    tmp = _path(platform) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f)
    os.replace(tmp, _path(platform))
    try:
        os.chmod(_path(platform), 0o600)
    except OSError:
        pass
    return rec


def load_session(platform: str) -> dict | None:
    p = _path(platform)
    if not os.path.exists(p):
        return None
    return json.load(open(p, encoding="utf-8"))


def session_status() -> dict:
    out = {}
    if not os.path.isdir(DIR):
        return out
    for f in os.listdir(DIR):
        if not f.endswith(".json"):
            continue
        try:
            rec = json.load(open(os.path.join(DIR, f), encoding="utf-8"))
            age = int(time.time()) - rec.get("saved_at", 0)
            out[rec["platform"]] = {
                "saved_at": rec.get("saved_at"),
                "age_hours": round(age / 3600, 1),
                "cookie_names": sorted(rec.get("cookies", {}).keys()),
                "meta": rec.get("meta", {}),
            }
        except Exception:
            pass
    return out
