"""X (Twitter) client over the GraphQL web API, driven by the operator's own cookies.

Needs two cookies from a logged-in session: auth_token and ct0 (ct0 is the CSRF token).
The web app's public bearer is a constant. The single-post use case — give a tweet URL,
pull its replies and read the room — runs on TweetDetail.

Read-only and gentle. queryId / feature flags drift every few weeks; override via the
constructor if TweetDetail starts 404-ing.
"""
import json
import random
import re
import time

from curl_cffi import requests

API = "https://x.com/i/api/graphql"
BEARER = ("Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
          "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA")
TWEETDETAIL_QID = "dQDdKtt882nl-Km98FJGSQ"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

FEATURES = {"rweb_video_screen_enabled": False, "rweb_cashtags_enabled": True,
    "profile_label_improvements_pcf_label_in_post_enabled": True, "responsive_web_profile_redirect_enabled": True,
    "rweb_tipjar_consumption_enabled": False, "verified_phone_label_enabled": True,
    "creator_subscriptions_tweet_preview_api_enabled": True, "responsive_web_graphql_timeline_navigation_enabled": True,
    "premium_content_api_read_enabled": False, "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True, "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": True, "rweb_cashtags_composer_attachment_enabled": True,
    "responsive_web_jetfuel_frame": True, "rweb_sports_post_context_enabled": False,
    "x_elections_post_context_enabled": True, "responsive_web_grok_share_attachment_enabled": True,
    "responsive_web_grok_annotations_enabled": True, "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True, "rweb_conversational_replies_downvote_enabled": False,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True, "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True, "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "content_disclosure_indicator_enabled": True, "content_disclosure_ai_generated_indicator_enabled": True,
    "responsive_web_grok_show_grok_translated_post": True, "responsive_web_grok_analysis_button_from_backend": True,
    "post_ctas_fetch_enabled": True, "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True, "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True, "longform_notetweets_inline_media_enabled": False,
    "responsive_web_nested_quote_preview_enabled": True, "responsive_web_grok_image_annotation_enabled": True,
    "responsive_web_grok_imagine_annotation_enabled": True, "responsive_web_made_on_x_label_enabled": False,
    "responsive_web_grok_community_note_auto_translation_is_enabled": True, "responsive_web_enhance_cards_enabled": False}
FIELD_TOGGLES = {"withArticleRichContentState": True, "withArticlePlainText": False,
    "withArticleSummaryText": True, "withArticleVoiceOver": True, "withGrokAnalyze": False,
    "withDisallowedReplyControls": False, "withPayments": False, "withDmBlocks": False}

_ID_RE = re.compile(r"status/(\d+)")


def tweet_id_from_url(url):
    m = _ID_RE.search(url or "")
    return m.group(1) if m else (url if (url or "").isdigit() else None)


class X:
    name = "x"
    required_cookies = ("auth_token", "ct0")

    def __init__(self, jar: dict, tweetdetail_qid: str = TWEETDETAIL_QID):
        missing = [c for c in self.required_cookies if not jar.get(c)]
        if missing:
            raise ValueError("X session is missing cookies: " + ", ".join(missing) +
                             ". Export cookies for x.com while logged in.")
        self.jar = jar
        self.qid = tweetdetail_qid
        self.s = requests.Session()
        self.headers = {
            "authorization": BEARER, "x-csrf-token": jar.get("ct0", ""),
            "x-twitter-auth-type": "OAuth2Session", "x-twitter-active-user": "yes",
            "x-twitter-client-language": "en", "content-type": "application/json",
            "user-agent": UA, "referer": "https://x.com/", "accept": "*/*",
        }

    def _get(self, qid, name, variables):
        params = {"variables": json.dumps(variables, separators=(",", ":")),
                  "features": json.dumps(FEATURES, separators=(",", ":")),
                  "fieldToggles": json.dumps(FIELD_TOGGLES, separators=(",", ":"))}
        r = self.s.get(f"{API}/{qid}/{name}", params=params, headers=self.headers,
                       cookies=self.jar, impersonate="chrome", timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"{name} {r.status_code}: {r.text[:200]}")
        body = r.json()
        if body.get("errors") and not body.get("data"):
            raise RuntimeError(f"{name} errors: {json.dumps(body['errors'])[:200]}")
        return body.get("data") or {}

    def whoami(self):
        return {"ok": bool(self.jar.get("auth_token") and self.jar.get("ct0")),
                "note": "X session validity is confirmed by the first successful call"}

    @staticmethod
    def _unwrap(result):
        if not result:
            return None
        if result.get("__typename") == "TweetWithVisibilityResults":
            result = result.get("tweet", result)
        return result

    @classmethod
    def _norm(cls, result, root_id):
        result = cls._unwrap(result)
        if not result or "legacy" not in result:
            return None
        lg = result["legacy"]
        user = (((result.get("core") or {}).get("user_results") or {}).get("result") or {})
        # X moved screen_name/name into user.core; older responses had them in legacy.
        uc = user.get("core") or user.get("legacy") or {}
        return {"id": lg.get("id_str"), "root": root_id,
                "handle": uc.get("screen_name"), "name": uc.get("name"),
                "blue": bool(user.get("is_blue_verified")), "text": lg.get("full_text", ""),
                "fav": lg.get("favorite_count", 0), "reply": lg.get("reply_count", 0),
                "rt": lg.get("retweet_count", 0), "quote": lg.get("quote_count", 0),
                "created_at": lg.get("created_at"), "reply_to": lg.get("in_reply_to_status_id_str"),
                "platform": "x"}

    def _entries(self, data):
        conv = data.get("threaded_conversation_with_injections_v2") or {}
        for ins in conv.get("instructions", []):
            if ins.get("type") == "TimelineAddEntries":
                return ins.get("entries", [])
        return []

    def tweet(self, tweet_id):
        """The focal tweet itself (text, author, engagement)."""
        data = self._get(self.qid, "TweetDetail", self._vars(tweet_id))
        for e in self._entries(data):
            if e.get("entryId", "").startswith("tweet-"):
                res = (((e.get("content") or {}).get("itemContent") or {}).get("tweet_results") or {}).get("result")
                norm = self._norm(res, tweet_id)
                if norm:
                    return norm
        return None

    def _vars(self, tweet_id, cursor=None):
        v = {"focalTweetId": str(tweet_id), "referrer": "tweet", "with_rux_injections": False,
             "rankingMode": "Relevance", "includePromotedContent": True, "withCommunity": True,
             "withQuickPromoteEligibilityTweetFields": True, "withBirdwatchNotes": True, "withVoice": True}
        if cursor:
            v["cursor"] = cursor
        return v

    def replies(self, tweet_id, max_pages=25):
        """Yield normalized replies to a tweet, paginating the conversation."""
        tweet_id = str(tweet_id)
        cursor = None
        seen = set()
        for _ in range(max_pages):
            data = self._get(self.qid, "TweetDetail", self._vars(tweet_id, cursor))
            next_cursor = None
            new = 0
            for e in self._entries(data):
                eid = e.get("entryId", "")
                content = e.get("content") or {}
                if eid.startswith("cursor-bottom-"):
                    next_cursor = content.get("value")
                elif eid.startswith("conversationthread-"):
                    for it in content.get("items", []):
                        res = (((it.get("item") or {}).get("itemContent") or {}).get("tweet_results") or {}).get("result")
                        norm = self._norm(res, tweet_id)
                        if norm and norm["id"] and norm["id"] not in seen and norm["id"] != tweet_id:
                            seen.add(norm["id"]); new += 1
                            yield norm
                elif eid.startswith("tweet-"):
                    res = ((content.get("itemContent") or {}).get("tweet_results") or {}).get("result")
                    norm = self._norm(res, tweet_id)
                    if norm and norm["id"] and norm["id"] not in seen and norm["id"] != tweet_id:
                        seen.add(norm["id"]); new += 1
                        yield norm
            if not next_cursor or new == 0:
                return
            cursor = next_cursor
            time.sleep(random.uniform(1.0, 2.2))

    # Single-post use case lives on replies()/tweet(). Profile/search for X need their
    # own queryIds (not captured here) and are intentionally left out of v1.
    def comments(self, media_id, max_pages=25):
        """Alias so the platform interface matches Instagram.comments()."""
        yield from self.replies(media_id, max_pages=max_pages)
