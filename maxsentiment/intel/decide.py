"""Deterministic labeling via the OpenAI Decisions API (model gpt-6-luna).

One /v1/decisions call per item answers a frozen set of questions, each with a
calibrated probability/confidence. Output tokens are free; input is $0.10/M, so a
few-thousand-comment corpus costs well under a dollar.

The API key is read from the OPENAI_API_KEY environment variable and never logged.
"""
import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

ENDPOINT = "https://api.openai.com/v1/decisions"
MODEL = "gpt-6-luna"

# A reasonable default taxonomy. Callers pass their own `questions` for anything real.
DEFAULT_QUESTIONS = [
    {"type": "choice", "name": "sentiment",
     "instructions": "Overall sentiment the author expresses toward the subject of the post. Judge attitude, not topic.",
     "choices": [{"value": "positive"}, {"value": "negative"}, {"value": "neutral"}]},
    {"type": "predicate", "name": "is_substantive",
     "instructions": "True if this is a genuine opinion, argument, or question from a real person; False if spam, an ad, a bot, or empty filler."},
]


def _key(key=None):
    key = key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set — the intelligence layer needs an OpenAI key")
    return key


def classify(text, questions=None, key=None, model=MODEL, retries=4):
    """Label one text against `questions`. Returns {name: value, name_conf/_p: ..., input_tokens}."""
    questions = questions or DEFAULT_QUESTIONS
    key = _key(key)
    body = json.dumps({"model": model, "input": (text or "")[:4000], "questions": questions}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read())
            out = {"input_tokens": data.get("usage", {}).get("input_tokens", 0)}
            for a in data.get("answers", []):
                if a.get("type") == "choice":
                    out[a["name"]] = a.get("choice")
                    out[a["name"] + "_conf"] = round(a.get("confidence", 0.0), 3)
                elif a.get("type") == "predicate":
                    p = a.get("probability", 0.0)
                    out[a["name"]] = bool(p >= 0.5)
                    out[a["name"] + "_p"] = round(p, 3)
            return out
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(2 * (attempt + 1)); continue
            return {"error": f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}"}
        except Exception as e:
            time.sleep(2 * (attempt + 1))
            if attempt == retries - 1:
                return {"error": str(e)[:200]}
    return {"error": "exhausted retries"}


def classify_many(rows, questions=None, key=None, workers=8, text_key="text", on_progress=None):
    """Label many rows concurrently. Returns rows augmented with the label fields,
    preserving input order. Each row must carry a stable 'id'."""
    key = _key(key)
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(classify, r.get(text_key, ""), questions, key): r for r in rows}
        done = 0
        for fut in as_completed(futs):
            r = futs[fut]
            results[id(r)] = {**r, **fut.result()}
            done += 1
            if on_progress and done % 50 == 0:
                on_progress(done, len(rows))
    return [results[id(r)] for r in rows]
