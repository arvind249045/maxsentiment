"""maxsentiment — scrape your own logged-in social sessions, then extract real intelligence.

You bring two things: the cookies from a platform you're already logged into (exported
with a browser extension), and an OpenAI key for the intelligence layer. maxsentiment
replays the platform's own internal web APIs — search, profile, posts, comments, reactions —
and then runs a recursive, self-labeling sentiment tree over what it pulls.

Nothing here logs in for you, creates accounts, or evades anything. It drives the exact
private endpoints your browser already calls, with the session you already have.
"""
__version__ = "0.1.0"

from .cookies import parse_cookies
from .store import save_session, load_session, session_status

__all__ = ["parse_cookies", "save_session", "load_session", "session_status", "__version__"]
