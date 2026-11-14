"""Resolve a post URL to (platform, post_id).

X:          https://x.com/<user>/status/<id>            -> ("x", "<id>")
Instagram:  https://instagram.com/p/<shortcode>/        -> ("instagram", "<media_id>")
            https://instagram.com/reel/<shortcode>/
Instagram shortcodes are base64 of the numeric media id, so we decode them locally.
"""
import re

_IG_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
_X_RE = re.compile(r"(?:twitter\.com|x\.com)/[^/]+/status/(\d+)", re.I)
_IG_RE = re.compile(r"instagram\.com/(?:p|reel|tv)/([A-Za-z0-9_-]+)", re.I)
_YT_RE = re.compile(r"(?:youtube\.com/(?:watch\?v=|shorts/|live/)|youtu\.be/)([A-Za-z0-9_-]{11})", re.I)
_RD_RE = re.compile(r"(?:reddit\.com/(?:r/[^/]+/)?comments/|redd\.it/)([a-z0-9]+)", re.I)
_LI_RE = re.compile(r"linkedin\.com/(?:posts/|feed/update/urn:li:activity:)[^?]*?(?:activity[:-])?(\d{18,20})", re.I)


def ig_shortcode_to_media_id(code: str) -> str:
    n = 0
    for ch in code:
        n = n * 64 + _IG_ALPHABET.index(ch)
    return str(n)


def resolve(url: str):
    url = (url or "").strip()
    m = _YT_RE.search(url)
    if m:
        return "youtube", m.group(1)
    m = _RD_RE.search(url)
    if m:
        return "reddit", m.group(1)
    m = _LI_RE.search(url)
    if m:
        return "linkedin", m.group(1)
    m = _X_RE.search(url)
    if m:
        return "x", m.group(1)
    m = _IG_RE.search(url)
    if m:
        return "instagram", ig_shortcode_to_media_id(m.group(1))
    if url.isdigit():
        return None, url  # bare id, platform unknown
    raise ValueError(f"could not resolve a post id from URL: {url!r}")
