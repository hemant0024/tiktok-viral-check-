# Competitor Hook Radar: Product Spec

## What this is

A daily system that finds the UGC style video ads and viral videos our competitors are using to win in the US, pulls out the exact hooks that are working, and turns them into original hooks for our English learning app (cat mascot).

This is NOT a general trend tracker and NOT an account tracker. We don't care about follower counts or brand pages. We care about individual videos:

- Which competitor ads are running long enough that they must be converting
- Which UGC videos about these apps are blowing up
- What the first 3 seconds say and show
- Why that hook works
- How we make our own version

The question the system answers every morning:

**"Which competitor hooks are working right now, and what 5 ads should we make today because of them?"**

## Market

United States only. US ads, US creators, US audience, English content. Settings live in config.

## Competitors

Stored in `config/competitors.yaml`, editable without code changes:

Praktika AI, Parrot, Pingo AI, Loora AI, Duolingo, Airlearn, Stimuler, Lingopanda, Falou, Speak, Babbel, Learna, Fluzy, Linguza, Memrise, ELSA Speak, Cambly, Preply

For each competitor store: name, app store names, website domain, Meta page names, TikTok handles, Instagram handles, YouTube channels, brand keywords and common misspellings, hashtags.

## What we collect

Two types of videos, both saved as one row per video.

### 1. Paid ads (main focus)

Competitor video ads running in the US on Meta (Facebook, Instagram) and TikTok, with priority on UGC style ads: real person talking to camera, reaction videos, street interviews, "I tried this app" videos, testimonials, before/after speaking, skits.

### 2. Organic viral UGC

Videos by creators (paid or not) that mention or show these apps on TikTok, Instagram Reels, and YouTube Shorts. Found by brand keywords, hashtags, and app mentions. These often become the next ads.

## How we know an ad is "working"

We can't see competitor conversion data. Nobody can. So we use proxies. An ad that costs money to run and keeps running is almost always profitable.

**Winner Signal Score (0 to 100):**

| Signal | Weight | Why it matters |
|---|---|---|
| Days running | 30% | Ads running 30+ days are usually converting. 60+ days is a strong winner. |
| Number of variations | 20% | Brands duplicate ads that work (same video, new copy, new sizes, new first frame). |
| Hook reused by other competitors | 15% | If 2+ brands run the same hook style, it's working across the category. |
| Recently relaunched or scaled | 15% | Same creative appearing again or on new placements. |
| Engagement where visible | 10% | Likes, comments, shares, views on TikTok and organic posts. |
| Platforms used | 10% | Running on both Meta and TikTok means it survived two auctions. |

For organic UGC use a **Viral Score** instead: views per day since posting, engagement rate, and how far above that creator's normal views it is. 500K views in 2 days beats 10M views in 6 months.

Labels, never predictions:
- Proven winner (long running, many variations)
- Likely winner
- New, watch it
- Test signal only

Never say a hook "will go viral" or "will convert."

## What we extract from every video

The first 3 seconds matter most. For each video:

**Basics:** video_id, competitor, platform, type (paid ad / organic UGC), url, creator, ad start date, last seen date, days running, variation count, views, likes, comments, shares, video file or link, thumbnail, ad copy, headline, CTA button, landing page, date found.

**Hook breakdown:**
- spoken_hook (exact words, first 3 seconds)
- on_screen_text_hook
- visual_hook (what you see in frame 1)
- first_3_seconds (what happens)
- full transcript
- hook_type (can be multiple): Confession, Secret, POV, Reaction, Challenge, Transformation, Before/After, Comparison, Contrarian, Mistake, Problem, Question, Story, Humor, Shock, Social Proof, Street Interview, Skit, Demonstration, Pattern Interrupt
- ugc_format: talking head, green screen, street interview, reaction, skit, split screen, screen recording, text on screen with voiceover
- creator_type: learner, teacher, immigrant story, couple, parent, student, professional
- pain_point: e.g. freezing when speaking, accent embarrassment, job interviews, understanding but can't talk
- promise: what they claim the app does
- emotion: embarrassment, curiosity, relief, pride, FOMO, humor
- structure: e.g. problem → fail moment → app → result
- proof: how they make it believable
- cta
- why_it_works (one or two plain sentences)

## Hook patterns

Group similar hooks across competitors into patterns. Example:

> **Pattern: "I understand English but freeze when I speak"**
> Used by: Praktika, Speak, Loora
> Format: talking head confession
> Ads using it: 14 | Longest running: 97 days
> Status: Proven winner

For each pattern track: how many ads use it, how many competitors, longest running ad, first seen, last seen, and whether usage is growing or dropping.

Also track **saturation**. If every competitor runs the same hook with the same wording, it still works but we need a fresh angle, not a copy.

## Turning hooks into our ads

For every strong pattern, generate 5 original hooks for our app. Each one includes:

- Hook (spoken)
- On screen text
- First frame visual
- First 3 seconds action
- Short script (15 to 30 sec)
- Where the product shows up
- CTA
- UGC version (real creator)
- Cat version (cat mascot)
- Which competitor pattern it's based on
- What's different about ours

Rules:
- Never copy competitor wording. Keep the mechanism, change the words, angle, and execution.
- The cat is part of the idea, not a sticker. The cat can be the learner, the teacher, get embarrassed, react to bad pronunciation, break the fourth wall, challenge the viewer, celebrate progress.
- Product details, positioning, mascot, and audience come from `config/product.yaml`, never hard coded.

**Hook Score (0 to 100):**
- 30% Based on a proven pattern
- 20% Stops the scroll in 3 seconds
- 15% Clear pain point for our audience
- 15% Fresh angle vs competitors
- 10% Product fits naturally
- 10% Easy to produce

Plus: strengths, weaknesses, risk, how to test it.

**Quality gate.** Reject anything that: copies wording, is generic, has no clear visual, makes false claims ("fluent in 7 days"), can't be produced cheaply, or ignores our product.

## Daily report

Sent to Slack (Telegram optional). Short. Tells us what to make, no raw data dumps.

```
🎯 COMPETITOR HOOK RADAR
September 10, 2026

NEW WINNERS SPOTTED
1. Praktika: "I've lived in the US 8 years and still..."
   Talking head confession · 41 days running · 6 variations
   Why it works: shame + identity, hits immigrants hard

TOP PATTERNS THIS WEEK
1. Freeze when speaking · 5 brands · Proven · Saturation: High
2. AI roleplay job interview · 2 brands · Likely winner · Saturation: Low

MAKE THESE 5 TODAY
#1 "My cat speaks better English than me"
   Based on: freeze confession
   UGC: creator tries to order coffee, freezes, cat judges from counter
   Score: 88 · Priority: HIGH
...
```

Each of the 5 includes: concept name, hook, visual, script, UGC version, cat version, product moment, CTA, why test it, risk, priority. Plus links to the original competitor videos for reference.

## Our ad performance loop

Import our own ad results (CSV first, Meta and TikTok API later):

creative_id, hook_id, pattern_id, launch_date, spend, impressions, 3_sec_view_rate, 25/50/95_percent_view_rate, ctr, cpc, installs, install_rate, trials, purchases, cac, roas, winner

When our ad wins or loses, save which hook type, pattern, format, pain point, emotion, and cat role it used. Feed winners and losers into future hook generation. Mix: 70% proven patterns, 30% new experiments.

## Data sources

Use official APIs and compliant tools first. The system must work even if a source is missing.

- **Meta Ad Library:** shows every active ad with start date. The official API mainly returns political ads for the US, so regular competitor ads may need an approved third party ad intelligence tool or a manual CSV export.
- **TikTok Creative Center (Top Ads):** shows top performing ads by region and industry in the web UI. No public API.
- **TikTok, Instagram, YouTube organic:** YouTube Data API for Shorts. TikTok and Instagram likely need a third party data provider.
- **Ad intelligence tools** (evaluate: Foreplay, PiPiAds, BigSpy, Minea, Atria, Apify actors): check US coverage, video downloads, days running data, API access, price, and terms of service.
- **Transcripts:** download video where allowed and transcribe (Whisper or similar). First 3 seconds transcript is required.
- **Manual input:** a Slack command or CSV where the team can drop a competitor ad link they saw. It goes through the same pipeline.

Every source is an adapter with the same output schema so it can be swapped.

## Database

Google Sheets first, behind a storage interface so we can move to Supabase later without rewriting logic.

Tabs: COMPETITORS, VIDEOS, VIDEO_SNAPSHOTS (daily views and days running history), HOOKS, PATTERNS, GENERATED_HOOKS, OUR_ADS, WINNERS, DAILY_REPORTS, RUN_LOG

No duplicates. video_id is the platform ad ID or post ID, or a hash of the URL.

## Tech stack

- Python for all logic, each stage runnable from the command line
- n8n for scheduling only
- LLM API with cheap model for extraction, strong model for hook generation
- Whisper or similar for transcripts
- Google Sheets, Slack
- Env vars for all keys, `.env.example` included

## Prompts

Separate files in `prompts/`, each with a version and JSON output format:

1. extract_hook
2. classify_ugc_format
3. analyze_why_it_works
4. cluster_patterns
5. score_saturation
6. generate_hooks
7. cat_and_ugc_versions
8. score_hooks
9. quality_gate
10. analyze_our_winners
11. daily_report

## Reliability and cost

- Every API call: retry, timeout, rate limit handling, logged errors
- One source failing never stops the run
- Never analyze the same video twice unless it changed
- Only transcribe and deeply analyze videos that pass a cheap filter (UGC style, running 7+ days or strong views)
- Log LLM and data tool cost per run

## Project structure

```
competitor-hook-radar/
├── README.md
├── CLAUDE.md
├── .env.example
├── docker-compose.yml
├── config/
│   ├── product.yaml
│   ├── competitors.yaml
│   └── scoring.yaml
├── prompts/
├── src/
│   ├── sources/
│   ├── processing/
│   ├── analysis/
│   ├── scoring/
│   ├── generation/
│   ├── storage/
│   └── notify/
├── workflows/n8n/
├── tests/
└── docs/
```

## Version 1 is done when

Every morning it:
1. Pulls new and still running competitor ads plus viral UGC videos for all 18 competitors in the US
2. Updates days running and views for videos already tracked
3. Extracts hooks from the first 3 seconds
4. Scores which ads look like winners
5. Groups hooks into patterns across competitors
6. Generates original hooks with UGC and cat versions
7. Scores and filters them
8. Sends a short Slack report with the 5 ads to make today
