<div align="center">

# maxsentiment

### An MCP server that tells you what people actually think about any social post.

**Give the post link. It reads every comment, finds the themes, and shows you which themes got the most engagement. Works on LinkedIn, Instagram, X, YouTube and Reddit.**

![Python](https://img.shields.io/badge/python-3.10+-3776ab?style=flat-square&logo=python&logoColor=white)
![MCP](https://img.shields.io/badge/MCP-server-5c4ee5?style=flat-square)
![Platforms](https://img.shields.io/badge/platforms-5-7f8c5c?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-f4c430?style=flat-square)

[What it does](#what-it-does) · [Examples](#examples) · [Platforms](#platforms) · [Quick start](#quick-start) · [FAQ](#faq)

</div>
---

## What it does

Two things:

**1. It reads the engagement on a post.** Every comment and every reply. On any platform you
support: LinkedIn, Instagram, X, YouTube, Reddit. You paste a link, it pulls the lot.

**2. It makes sense of it.** It uses the OpenAI Decisions API to classify every comment, and
GPT-5 to work out the themes. Then it buckets the themes with engagement and ranks top to bottom.:

So instead of "412 comments," you get the real breakdown:

> 38% of the engagement was people asking for proof. 22% was price complaints. 15% was
> praise. 9% was "not for us."

That is the whole point. What the conversation was actually about, and which parts of it
people actually cared about. (A comment counts for more than a like, because writing takes
more effort than tapping. So the ranking reflects real attention, not drive-by taps.)

## Examples

Point it at a post and you get four things:

| | |
|---|---|
| 📊 **Engagement** | which themes pulled the most comments, replies and shares, ranked |
| 🎭 **Sentiment** | how people felt about each theme. for it, against it, or just asking |
| 👥 **Who's engaging** | the accounts showing up, the repeat voices, the verified names |
| 🧵 **The theme** | the one objection or idea that keeps coming back, even on different platforms |

### One theme, every channel

Deepinder Goyal (Zomato founder) pots about Temple, his health wearable. Here is what maxsentiment found across his Temple posts on X: **2,404 comments, 30,274 engagement units** (a like counts 1, a reply or repost 2, a quote 3).

| sentiment | comments | % of comments | engagement | % of engagement |
|---|---|---|---|---|
| Negative | 1,217 | 51% | 23,242 | **77%** |
| Positive | 639 | 27% | 5,162 | 17% |
| Neutral | 548 | 23% | 1,870 | 6% |

| theme | comments | engagement | % of engagement |
|---|---|---|---|
| Political / social critique ("not for India") | 138 | 9,204 | **30%** |
| Science & claims skepticism ("show the proof") | 277 | 7,882 | **26%** |
| Fraud / unethical-conduct allegations | 128 | 2,842 | 9% |
| Product design, price, privacy | 276 | 2,523 | 8% |
| Product enthusiasm | 119 | 2,132 | 7% |
| Supportive advice / questions | 144 | 1,286 | 4% |
| Cheerleading / support | 236 | 1,150 | 4% |
| "How does it work" (neutral) | 349 | 1,016 | 3% |

The top two themes are 415 comments, 17% of the thread, but they drove 56% of all the engagement. That is the whole point of weighting by effort: the loud minority is not loud by headcount, it is loud by reach.

One tool, one question ("where's the proof?"), and you can see it's not a few loud trolls, it's
a consistent, credentialed objection across every place the product is being talked about. That
is the kind of thing a founder or a brand actually needs to know, and it is buried in thousands
of comments until something reads all of them.

### One post, up close

Kunal Shah's "WhatsApp" post on X, 360 replies: the raw top of the feed was all promo spam
(trading pitches, ads). maxsentiment drops that on its own, and the real chorus underneath is
one clear theme: "WhatsApp has become a spam and ads machine." Under it, people ask for a
separate business inbox, an opt-in AI, and a fix for the fraud and impersonation. Loudest
single reply: "it no longer feels like a messenger."

### See it for yourself

The [`examples/`](examples) folder has the real JSON from the Deepinder run:

- [`raw_comments_x.json`](examples/raw_comments_x.json) and [`raw_comments_instagram.json`](examples/raw_comments_instagram.json) — every comment maxsentiment pulled (8,000+ in total), the raw input.
- [`analysis_output.json`](examples/analysis_output.json) — what it found: the cross-channel theme, the counts, and the quotes.

## Platforms

| platform | paste a post link, get | login |
|---|---|---|
| LinkedIn | comments on the post | your cookies |
| Instagram | comments on the post | your cookies |
| X / Twitter | replies on the tweet | your cookies |
| YouTube | comments on the video | **none (public)** |
| Reddit | the whole thread | your cookies |

Every platform reads the same internal web API your browser uses. Nothing is logged in, made,
or evaded. You export your session cookies once, with a browser extension. YouTube needs
nothing.

## Quick start

```bash
pip install -r requirements.txt
```

Register the MCP server with your agent (Claude Code or Desktop). Command `python`, args
`["server.py"]`, env `{ "OPENAI_API_KEY": "sk-..." }`. Then just talk to it:

```text
What are people saying on https://x.com/user/status/123456?
Which themes got the most engagement, and how did people feel?
```

The agent walks you through exporting cookies (it points you at the open-source "Get
cookies.txt LOCALLY" extension), reads the post, and reports back. The skill in
`skills/maxsentiment/` teaches it the whole workflow.

**The two calls it runs under the hood:**

```text
ms_post(url)         pull every comment on the post
ms_build_tree(...)   group them by theme, ranked by engagement
```

## How it's built

- **Platform clients** read each site's own internal web API with your session cookies.
- **The OpenAI Decisions API** classifies every comment. Fast, deterministic, cheap: a few
  thousand comments costs under a dollar. **GPT-5** names and groups the themes.
- **A spam filter runs first**, so promo, ads and giveaways never pollute the ranking.

## FAQ

<details>
<summary><strong>Does this log into my accounts or post anything?</strong></summary>

No. It never logs in, posts, likes, follows, or makes accounts. It reads public comments
using a session cookie you exported yourself. It only reads.
</details>

<details>
<summary><strong>Where do my cookies live?</strong></summary>

In `~/.maxsentiment/`, outside any repo, one file per platform. They're never committed and
never sent anywhere except the platform they belong to. Scraped comments write to
`maxsentiment_runs/`, which is `.gitignore`d.
</details>

<details>
<summary><strong>What does it cost to run?</strong></summary>

Scraping is free. The theme analysis uses the OpenAI Decisions API, where input is cheap and
output is free, so a run over a few thousand comments is well under a dollar. The key is read
from `OPENAI_API_KEY`.
</details>

<details>
<summary><strong>Which agents can use it?</strong></summary>

Any agent that supports a local MCP server (Claude Code, Claude Desktop, and others). Or use
the Python library directly.
</details>

<details>
<summary><strong>Why is LinkedIn different?</strong></summary>

LinkedIn serves its comments as a heavier server-driven page, not a clean data feed, so it
needs a fully fresh session. Same input and output as the others, just more machinery behind
it.
</details>

## Privacy

Sessions live in `~/.maxsentiment/`, outside any repo, so cookies never get committed.
Scraped comments write to `maxsentiment_runs/`, which is `.gitignore`d. This repo is the tool.
Whatever you point it at stays on your machine.

## Not for

Making fake accounts, scraping strangers at scale, evading blocks, or building a dossier on a
private person. It drives your own session against public posts. Keep it there.

## License

[MIT](LICENSE).
