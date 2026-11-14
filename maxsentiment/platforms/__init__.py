"""Platform clients. Each exposes the same shape: search / profile / posts / comments.

Every client is constructed from a cookie jar (the operator's own session) and talks
to the platform's internal web API with curl_cffi's Chrome TLS impersonation, exactly
as the browser would.
"""
from .instagram import Instagram
from .youtube import YouTube
from .reddit import Reddit
from .linkedin import LinkedIn

REGISTRY = {"instagram": Instagram, "ig": Instagram, "youtube": YouTube, "yt": YouTube,
            "reddit": Reddit, "linkedin": LinkedIn, "li": LinkedIn}

# Platforms whose public data needs no login (constructed with an empty jar).
SESSIONLESS = {"youtube", "yt"}

try:  # X is beta; keep import failures from breaking the rest
    from .x import X
    REGISTRY["x"] = X
    REGISTRY["twitter"] = X
except Exception:  # pragma: no cover
    pass


def client_for(platform: str, jar: dict | None = None):
    key = platform.lower().strip()
    if key not in REGISTRY:
        raise ValueError(f"unknown platform {platform!r}; known: {sorted(set(REGISTRY))}")
    return REGISTRY[key](jar or {})
