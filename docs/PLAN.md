# Daily Creative Intelligence System — Implementation Plan

Status: **Phases 0 to 9 built.** 57 tests passing. Runs end to end on real data.
Awaiting API keys to run for real.
Spec: `docs/SPEC.md` (read in full, 30 sections)
Last updated: 2026-09-10

The one question this system answers every morning:
**"What are the 5 most interesting creative ideas we should test today, and why?"**

---

## 1. CURRENT STATE

The folder was empty apart from the spec. No code, no git repo, no `.env`, no config, no n8n, no database, no credentials, no dependencies.

```
/Users/hemant/tiktok hook finder/
├── CLAUDE.md          (written in Phase 0)
└── docs/
    ├── SPEC.md        (yours, moved here from the root to match the brief)
    └── PLAN.md        (this file)
```

I moved `SPEC.md` from the folder root into `docs/` because the brief specifies `docs/SPEC.md`. Nothing else changed.

### Decisions taken from the spec

| Thing | Value | Spec ref |
|---|---|---|
| Market | **United States.** `country=US`, `en-US`, `America/New_York` | §4, §13 |
| Global content | Secondary signal only, must be tagged with its country | §4 |
| Database | Google Sheets first, 8 tabs named in the spec | §22 |
| LLM provider | OpenAI preferred | §2 |
| Categories | 15 named categories, not just English learning | §4 |
| Competitors | Duolingo, Praktika, Loora, Speak, ELSA Speak, Airlearn, Pingo, Stimuler, in config | §12 |
| Hook types | 20 named categories, multiple allowed per hook | §7 |
| Cost ladder | 100 raw → 50 candidates → 20 patterns → 10 trends | §26 |
| Report | Top 10 patterns, top 20 hooks, top 5 ads to produce | §17 |
| No prediction claims | High / Medium / Experimental / Low opportunity only | §28 |

### Decisions made since Phase 0 was approved

| Decision | Outcome |
|---|---|
| TikTok source | **Approved.** Apify `apidojo/tiktok-scraper`, $0.0003 a post. Verified with a live run. |
| Meta ads source | **Approved.** Apify `apify/facebook-ads-scraper`. The official API returns no US commercial ads. |
| Scope | **Widened.** All organic TikTok content, not only ads, and specifically things on the way up. |
| Duration cap | **2 minutes.** Cuts cost and removes long-form podcasts that are not what this is for. |
| Video analysis | Adapter built, off by default. Set `CI_VIDEO_PROVIDER=gemini` to switch it on. |
| Embeddings | Local. `sentence-transformers` when installed, deterministic hashing fallback otherwise, so tests need no network. |
| Storage | A third `local` JSONL adapter was added so the pipeline runs with zero credentials. Sheets is still adapter one. |

### Open environment choices

* Repo root. I have used `/Users/hemant/tiktok hook finder` directly. Spec §29 shows a `creative-intelligence/` folder. Say the word and I will nest it.
* Python 3.11, `uv`, `ruff`, `pytest` unless you prefer otherwise.
* Git is not initialised yet. Phase 1 does it.

---

## 2. ARCHITECTURE

Every box is swappable. Nothing downstream of the adapter line knows which source or which store it is talking to.

```
   SOURCES (adapter per source, one interface)                      §3
   ┌──────────────────────────────────────────────────────────────┐
   │ youtube.py   tiktok.py   meta_ads.py   instagram_stub.py     │
   │ csv_import.py                                                 │
   │      every one: fetch(cfg) -> list[NormalizedContent]         │
   └────────────────────────────┬─────────────────────────────────┘
                                │  ci collect <source>
                                ▼
                    normalize → dedup → cheap filter          §26
                    100 raw  →  50 candidates
                                │
   ┌────────────────────────────┴─────────────────────────────────┐
   │              Repository interface (database/base.py)      §22 │
   │   ┌──────────────┬──────────────┬───────────────────────┐    │
   │   │ SheetsRepo(1)│ InMemoryRepo │ PostgresRepo (later)  │    │
   │   └──────────────┴──────────────┴───────────────────────┘    │
   └────────────────────────────┬─────────────────────────────────┘
                                │
     ┌──────────────┬───────────┴──────────┬─────────────────┐
     ▼              ▼                      ▼                 ▼
  analyze        patterns              generate           report
  ┌──────────┐  ┌────────────────┐   ┌─────────────┐   ┌──────────┐
  │ LLM      │  │ scoring/       │   │ LLM strong  │   │ renderer │
  │ cheap    │  │ PURE PYTHON    │   │ + quality   │   │ + notify │
  │ cache    │  │ unit tested    │   │   gate      │   │ slack /  │
  │ schema   │  │ NO prompts     │   │ (§27, §28)  │   │ telegram │
  │ cost log │  │ (§8,§9,§11,§16)│   └─────────────┘   └──────────┘
  └──────────┘  └────────────────┘
        │                                    │
        └──── prompts/*.md, versioned, JSON schema ────┘
        └──── config/product.yaml, competitors.yaml, scoring.yaml ────┘

   n8n schedules and chains the CLI commands. It holds zero logic.       §23
```

### Repo layout

Spec §29 asks for `src/collectors, processors, analyzers, scoring, generators, database, notifications`. The brief requires `python -m ci <stage>`. A src layout satisfies both exactly.

```
.
├── src/ci/
│   ├── __main__.py            # python -m ci <stage>
│   ├── config.py              # .env + config/*.yaml via pydantic Settings
│   ├── models.py              # one pydantic model per table
│   ├── logging.py             # structured JSON, run_id on every line
│   ├── run.py                 # run context, failure isolation, run summary   §25
│   ├── collectors/            # base.py + youtube.py tiktok.py meta_ads.py
│   │                          #   instagram_stub.py csv_import.py
│   ├── processors/            # normalize.py dedup.py cheap_filter.py snapshots.py
│   ├── analyzers/             # creative_dna.py hooks.py winners.py
│   ├── scoring/               # momentum.py saturation.py opportunity.py
│   │                          #   hook_score.py  (PURE PYTHON, unit tested)
│   ├── patterns/              # extract.py embed.py match.py
│   ├── generators/            # adapt.py hooks.py cat.py quality_gate.py originality.py
│   ├── database/              # base.py sheets.py memory.py
│   ├── notifications/         # slack.py telegram.py
│   └── llm/                   # client.py cache.py providers/{openai,gemini}.py
├── config/
│   ├── product.yaml           # market, product, mascot, audience          §13
│   ├── competitors.yaml       # editable without code changes             §12
│   ├── sources.yaml           # query sets, quota budgets, region codes
│   └── scoring.yaml           # every weight and threshold                §8,§16
├── prompts/                   # 11 files, versioned, JSON schema each      §24
├── docs/  tests/  workflows/n8n/
├── .env.example  docker-compose.yml  CLAUDE.md  pyproject.toml
```

### Tables

Spec §22 names 8 tabs. I am adding 3 for reasons given below. All 11 go behind the repository interface.

| Tab | Key | Spec | Notes |
|---|---|---|---|
| `RAW_CONTENT` | `content_id` | §5 | Written once per item. Idempotent. |
| `HOOKS` | `hook_id` | §6 | |
| `CREATIVE_PATTERNS` | `pattern_id` | §22 | **Persistent across days. Never recreated.** |
| `TRENDS` | `pattern_id` + `date` | §22 | Daily scores. This is what trends over time. |
| `ADAPTATIONS` | `adaptation_id` | §22 | Generated hooks, approved and rejected, with reasons. |
| `TEST_RESULTS` | `creative_id` | §19 | CSV import. |
| `WINNERS` | `winner_id` | §20 | Winning DNA as reusable patterns. |
| `DAILY_REPORTS` | `date` | §22 | Full §17 output stored. |
| `CONTENT_SNAPSHOTS` | `content_id` + `captured_at` | **new** | Required for real velocity. See 3.2. |
| `RUN_LOG` | `run_id` | **new** | Run summary, failures, duration, cost. §25 needs somewhere to land. |
| `LLM_CALLS` | `call_id` | **new** | Tokens, cost, cache hit, model, prompt version. §26 needs this to be enforceable. |

`content_id` = platform ID where one exists, otherwise `sha256(canonical_url)[:16]`, per §5 and brief rule 8.

---

## 3. SPEC ISSUES AND FIXES

Four were flagged in the brief. Reading the spec surfaced seven more. Nothing here needs a big rewrite, but I want sign off before Phase 1.

### 3.1 Trend Score labels conflict (§8)

**The problem is worse than the brief described,** because the spec gives the actual formula:

```
Trend Score = 30% Growth Velocity + 20% Cross Category Adoption
            + 20% Novelty + 15% Audience Relevance + 15% Product Applicability

0-30 Emerging | 31-55 Rising | 56-75 Saturating | 76-100 Exhausted
```

Every one of those five components is a *good* thing. Fast growth, wide adoption, novel, relevant, applicable. So a score of 100 describes the best possible pattern, and the label calls it Exhausted. The sample report in §18 proves the intent: Trend Score 91, Saturation Low, five stars, PRODUCE. Under the label table 91 is Exhausted. The spec already half admits this in §8: "The label must be based on both momentum and saturation, not only the number."

**Fix, which keeps your weights untouched.** Three numbers and a label.

```
momentum_score     0-100   how fast is it growing right now        §9
saturation_score   0-100   how crowded is it already               §11
opportunity_score  0-100   should we make this today               §8 weights, unchanged
lifecycle_label            Emerging | Rising | Saturating | Exhausted
```

The key move is one line: **`novelty = 100 - saturation_score`**. That makes your own formula self penalising, which is exactly what §8 asks for, and it stops being a separate thing to define.

```
opportunity_score = 0.30 * momentum_score
                  + 0.20 * cross_category_score
                  + 0.20 * (100 - saturation_score)
                  + 0.15 * audience_relevance_score
                  + 0.15 * product_applicability_score
```

`momentum_score` from velocity in a recent window only, log scaled because view counts are heavily skewed and one outlier would otherwise own the whole report:

```
pattern_velocity = median(views_per_day of pattern content published within lookback_days)
momentum_score   = clamp(0,100, 100*(log10(1+pattern_velocity) - floor)/(ceiling - floor))
                   * velocity_confidence_factor
```

`saturation_score` from the eight signals §11 already lists:

```
saturation_score = clamp(0,100,
    20 * norm(recent_occurrences)      + 15 * norm(distinct_brands)
  + 15 * norm(distinct_competitors)    + 12 * norm(trend_age_days)
  + 14 * norm(exact_wording_repetition)+ 12 * norm(visual_repetition)
  +  6 * norm(audio_repetition)        +  6 * norm(distinct_categories))
```

`cross_category_score` from §10, `audience_relevance_score` and `product_applicability_score` read from `config/product.yaml` so no product assumption sits in the scoring code (brief rule 5).

**`lifecycle_label`, from momentum and saturation together.** Evaluated top to bottom, first match wins:

| Label | Condition |
|---|---|
| Exhausted | `saturation >= 80` OR momentum fell 3 days running |
| Saturating | `saturation >= 60` |
| Emerging | `saturation < 35` AND `pattern_age_days <= 7` |
| Rising | `momentum >= 60` |
| Saturating | everything else |

Check against your own sample: momentum 91, saturation low (say 20), five days old. Not exhausted, not saturating, saturation under 35 and age under 7, so **Emerging**, opportunity ≈ 0.30(91) + 0.20(cross 6 cats → ~85) + 0.20(80) + 0.15(85) + 0.15(88) = **86**. Five stars. That matches the report you wrote.

**The daily report sorts by `opportunity_score`.** That is the number that answers the morning question. `momentum_score` and `saturation_score` are still shown, because the creative team needs to see why.

### 3.2 Velocity needs history (§9)

§9 asks for `growth_rate`, and §22's tab list has nowhere to put a second reading of the same video. One snapshot only gives a lifetime average, which lies badly.

**Fix.** Add `CONTENT_SNAPSHOTS` (`content_id`, `captured_at`, `views`, `likes`, `comments`, `shares`). Every collect run appends a snapshot for every tracked item, including ones already in `RAW_CONTENT`. This is exactly why Phase 2's acceptance test says content once, snapshots twice.

```
1. Two or more snapshots >= 12h apart
   views_per_day = (v_latest - v_prior) / days_between
   confidence high, factor 1.0

2. Exactly one snapshot
   views_per_day = views / max(days_since_publish, 0.5)
   confidence LOW, factor 0.7, flagged low_confidence everywhere including the report
```

The 0.7 factor means a single snapshot item cannot top the report on its own. It needs a second day.

**The old viral video trap, which §9 raises directly** ("10M views over 6 months is less interesting than 500K in 2 days"):

1. Only content published within `lookback_days` (default 30) feeds `momentum_score`. A three year old video with 10M views computes to 9,000 views/day and would otherwise look like a rocket.
2. Older content is not discarded. It goes to a `reference` bucket used for creative DNA and pattern examples, never for momentum. Flag `is_reference=true`.

Both are Phase 4 unit tests.

### 3.3 Clustering across days (§24, prompt 03)

§24 lists `03_cluster_patterns` but nothing in the spec says today's patterns must be matched to yesterday's. Without that, `CREATIVE_PATTERNS` gets recreated every morning, and momentum, saturation, trend age and cross category all become impossible to compute.

**Fix.** Two stage matching, cheap first, LLM only for the ambiguous middle.

Every pattern stores a canonical text (`creative_mechanism` + `hook_type` + `structure`) and its embedding.

```
for each candidate pattern from today:
    sim = max cosine(candidate, existing patterns)

    sim >= 0.86          AUTO MATCH        attach a TRENDS row to the existing pattern
    0.72 <= sim < 0.86   LLM ADJUDICATE    candidate + top 3 existing to the strong tier
                                           strict JSON {"match":bool,"pattern_id":str,"why":str}
    sim <  0.72          NEW PATTERN       create, embed, store
```

Thresholds live in `config/scoring.yaml` and get tuned in Phase 4 against about 50 hand labelled pairs. Every decision writes similarity, decider (`vector` or `llm`) and runner up, so a bad merge is auditable instead of invisible. Merged patterns keep an `aliases` list so the name the team learned does not silently change.

**Embedding provider.** Recommendation: local `sentence-transformers` `all-MiniLM-L6-v2`. Free, no extra key, runs offline so unit tests need no network, about 90MB on disk. The alternative is OpenAI embeddings, which are cheap but add a network call to the test path. **This adds a Python dependency so I am flagging it for approval as the brief requires.**

### 3.4 Originality check (§14, §27)

§14 says "Never copy the source video's exact wording" and §27 rejects "copied wording". Neither is implementable without a similarity measure.

**Fix.** Four checks, all thresholds configurable. Normalize first: lowercase, strip punctuation and emoji, collapse whitespace, expand contractions.

```
Candidate set = source hooks of the parent pattern
              + top 200 nearest source hooks globally by embedding

check 1  word trigram Jaccard            reject if >= 0.60
check 2  longest common contiguous run   reject if >= 7 words
check 3  embedding cosine                reject if >= 0.93
check 4  the same three against the other 4 hooks in this batch,
         so we never ship five near duplicates of each other
```

Every rejection logs the hook, the matched source hook, which check fired and the score, into `ADAPTATIONS` with `status=rejected`. That log is how the thresholds get tuned in Phase 5, on real output rather than a guess today.

### 3.5 The spec's own stack cannot fill the spec's own fields (§2 vs §5, §6, §7)

§6 requires `first_3_second_description`, `visual_hook`, `on_screen_text`. §5 requires `raw_transcript`. §7 wants "Visual: Creator whispers into camera".

None of that is derivable from a title and a description. §2 prefers the OpenAI API, and **OpenAI has no native video input**. There is an open feature request on the OpenAI SDK asking for parity with Gemini on this. The only OpenAI route is extracting frames yourself, which means downloading the video, which is against YouTube's terms.

**Fix.** §2 allows a deviation for "a strong technical reason". This is one.

* **OpenAI stays the default provider for all 11 text prompts**, exactly as §2 asks.
* **One narrow exception: a Gemini adapter for video ingestion only.** The Gemini API accepts a public YouTube URL directly as a video input. We download nothing. It reads audio and on screen text, which is precisely what §6 and §7 need. Costs about $7 a month at 50 candidates a day.
* Provider stays swappable via config (brief rule 3), so this is one adapter, not a rewrite.
* If you reject it, the fallback is metadata only, and `first_3_second_description`, `visual_hook` and `on_screen_text` will be weak guesses from the title. I would rather you knew that than found out in Phase 3.

**`raw_transcript` semantics also need fixing.** The official YouTube API only returns captions for videos you own. Add a `transcript_source` column with values `owned_captions | gemini_video | manual | none`, and let `raw_transcript` be empty where nothing compliant exists.

### 3.6 Scoring is specified as prompts, but must be Python (§24 vs brief rule)

§24 lists `04_detect_trends` and `05_score_saturation` as AI prompts. The brief requires scoring math in plain Python with unit tests, not in prompts, and it is right. An LLM cannot be unit tested for arithmetic, and §8, §9, §11 and §16 are all arithmetic.

**Fix.** The math moves to `src/ci/scoring/`, fully unit tested. Prompts 04 and 05 survive but change job: they take the computed numbers and write the "Why It Matters" narrative that §17 requires per pattern. The numbers come from Python, the sentence comes from the model. Flagging because it changes what two of your eleven prompts do.

### 3.7 Prompt list mismatch between §24 and §29

§24 lists 11 prompts. §29's tree lists 10 files, drops `adapt_to_product`, and renames `generate_cat_execution` to `cat_adaptation`.

**Fix.** Use §24's list of 11, with numeric prefixes so execution order is obvious on disk:

```
01_extract_creative_dna.md   02_classify_hook.md      03_cluster_patterns.md
04_detect_trends.md          05_score_saturation.md   06_adapt_to_product.md
07_generate_hooks.md         08_generate_cat_execution.md
09_score_hooks.md            10_analyze_winners.md    11_generate_daily_report.md
```

### 3.8 §17 full output versus §18 concise report

§17 asks for top 10 patterns, top 20 hooks and top 5 ads. §18 shows a short message and says "keep it concise", and the brief says one phone screen per concept. Twenty hooks will not fit on a phone screen.

**Fix, and I do not think these are actually in conflict.** §17 is what gets written to `DAILY_REPORTS` in full. §18 is what gets sent to Slack: the top 5 ads to produce, one screen each, in the exact format of your example. The Slack message ends with a line pointing at the full report in the sheet. Confirm that reading is right.

### 3.9 Hook count arithmetic (§14 vs §17 vs §26)

§26's ladder ends at 10 trends. §14 says 5 hooks per high opportunity pattern. §17 wants top 20 hooks. 10 × 5 = 50, not 20.

**Fix.** Generate 5 hooks for the top 5 patterns by `opportunity_score` (25 hooks), score them with §16, report the top 20. Generating for all 10 doubles the biggest cost line for hooks that will not be shown. If you would rather generate all 50, it is a config change and about $13 a month more.

### 3.10 §8's product components must not live in scoring code

"Audience Relevance" and "Product Applicability" are 30% of the score and are entirely product specific. Brief rule 5 says no product assumption outside `config/product.yaml`.

**Fix.** Both are computed by prompt against the product profile loaded from config, then passed into the Python scorer as plain numbers. The scorer never knows what the product is.

### 3.11 US market changes what each source is worth

§4 sets the market to US. That is not a cosmetic change: it makes TikTok more important, because the US is where this app's audience actually is, and it makes the Meta Ad Library API less useful, because the API's commercial coverage stops at the EU border. Details in section 4 below.

---

## 4. DATA SOURCE REALITY CHECK

Checked against current documentation on 2026-09-10. Market is US throughout.

### YouTube Data API v3 — AVAILABLE, quota is the real constraint

* Free. Default **10,000 units per day** per Google Cloud project.
* `search.list` costs **100 units**. `videos.list` costs **1 unit** for up to 50 IDs. `playlistItems.list` costs 1 unit.
* So it is **100 searches a day and nothing else**, or a smarter mix.
* US targeting is supported: `regionCode=US`, `relevanceLanguage=en`.

**Proposed daily budget:**

| Call | Count | Unit cost | Units |
|---|---|---|---|
| `search.list` discovery, 15 categories rotated | 60 | 100 | 6,000 |
| `videos.list` hydrate 3,000 IDs at 50 per call | 60 | 1 | 60 |
| `videos.list` snapshot ~400 tracked videos | 8 | 1 | 8 |
| `channels.list` creator context | 20 | 1 | 20 |
| `playlistItems.list` uploads of tracked channels | 40 | 1 | 40 |
| **Total** | | | **~6,130** |
| Headroom for retries and manual pulls | | | ~3,870 |

The uploads playlist trick matters. To pull a known channel's recent videos, use its uploads playlist at 1 unit instead of `search.list` at 100. Reserve search purely for discovering creators we do not already track. Quota increases exist via a Google audit form but are slow and not guaranteed, so nothing is planned around getting one.

**Transcripts.** `captions.download` only works on videos you own, authenticated as the channel. Third party transcript scrapers are against YouTube's terms. See 3.5 for the fix.

### TikTok — no official access, but the spec sanctions compliant third parties

* **Research API**: academic institutions and non profits only, in the US, EEA, UK, Canada and Switzerland. Applicants must be "independent of commercial interests". Confirmed on TikTok's own developer page. **We do not qualify.**
* **Commercial Content API**: ads only, EU focused. Does not cover organic trends.
* **Creative Center**: web UI only, no public API, despite §3 mentioning it as a source.

§3 explicitly permits "compliant third party APIs where necessary", so this is a budget decision, not a spec violation. Current pricing:

| Provider | Price | Note |
|---|---|---|
| **Apify TikTok actors** | **~$1.70 per 1,000 results** | Pay as you go, no subscription. **You already have Apify connected.** |
| Bright Data | ~$1.50 per 1,000 records | Pay as you go |
| ScrapeCreators | $47 / 25,000 credits | ~21 TikTok endpoints |
| EnsembleData | $100/month | 1,500 units/day, keyword search returns 20 posts per unit |
| ScrapingDog | $40/month | 200,000 credits |
| TikAPI | $29/month | 300 requests/day |

**APPROVED AND BUILT.** `apidojo/tiktok-scraper` at **$0.0003 a post**, roughly six times cheaper than the widely used clockworks actor. Verified with a live run on 2026-09-10 against US data.

Confirmed capabilities from that run, not from documentation:
`keywords`, `location` (ISO code, US available), `sortType` (RELEVANCE, MOST_LIKED, DATE_POSTED), `dateRange` (YESTERDAY, THIS_WEEK, THIS_MONTH and others), `maxItems`, and `startUrls` for re-checking known posts.

**One unexpected win.** Each result carries `subtitleInformation` with a caption URL and `is_auto_generated`. TikTok auto-captions come back inside the same $0.0003, so TikTok transcripts cost nothing extra. That is the transcript problem solved for TikTok without touching the $0.048 per minute transcript add-on and without Gemini.

The collector runs **two passes every time**, and the pairing is the whole point:
`MOST_LIKED` shows what is already big, `DATE_POSTED` shows what is climbing.

Honest caveat: every provider on that list operates against TikTok's terms of service, and the exposure sits with us rather than with them. §3 tells me to use compliant third parties where necessary, and I want you to make that call knowingly rather than have it arrive as a line item. I am not a lawyer and this is not legal advice.

### Meta Ad Library API — works, but not for US commercial ads

* Requires identity verification with government ID, plus app review. Tokens expire about every 60 days, so refresh logic is mandatory or the source dies silently two months in.
* **Political and issue ads**: worldwide, with spend and impressions as bounded ranges.
* **All commercial ads**: only where `ad_reached_countries` targets the **EU or UK**, because that is what the Digital Services Act compels. Returns `eu_total_reach`, no spend.
* **US commercial ads are not in the API.** Our entire competitor list from §12 is commercial and US targeted.
* **No engagement metrics anywhere.** No likes, comments, shares or CTR. Run duration is the only performance proxy.
* Rate limit around 200 calls per hour per user token, and every pagination page counts.

**What this actually means for §12.** Duolingo, Speak, ELSA and Babbel all run EU and UK campaigns, so we can legitimately pull their creative through the EU route and read the hook, emotional trigger and CTA, which is all §12 asks for. It is a proxy: US specific creative will not appear. The smaller US only players (Praktika, Loora, Airlearn, Pingo, Stimuler) may return nothing at all.

**Recommendation.** Build the API adapter in Phase 7 scoped to EU and UK reached countries, and cover the US gap with an Apify Meta Ad Library actor or manual capture plus CSV import. Start the Meta ID verification now regardless, because it takes days.

### Instagram — no trend discovery API, saying it plainly

There is no Instagram API for discovering trending content we do not own.

The one exception is IG Hashtag Search on the Instagram Graph API, and it cannot do this job:

* **30 unique hashtags per rolling 7 day window.** Roughly four new hashtags a day, forever.
* `recent_media` covers **only the last 24 hours**. `top_media` is engagement ranked.
* **`username` cannot be requested**, so no creator, no follower context, no tracking a creator over time.
* 50 results per page, Business or Creator account, Facebook Login required.

**Recommendation: stub adapter plus CSV import,** per the brief. If we ever want Instagram signal, the honest answer is a person with the Explore tab and a spreadsheet.

### Summary

| Source | Status | Phase | Cost |
|---|---|---|---|
| YouTube Data API | Available, 10k units/day, US region | 2 | $0 |
| Gemini video analysis on YouTube URLs | Available, **needs approval** | 3 | ~$7/mo |
| TikTok via Apify | **Built and verified live** | 2 | ~$2/mo |
| TikTok transcripts | **Free**, auto-captions ship with each result | 3 | $0 |
| Meta ads via Apify | **Built**, incremental after first run | 7 | ~$5/mo |
| Meta Ad Library official API | Not used. No US commercial ads. | - | - |
| Instagram | Stub + CSV import | 7 | $0 |
| Manual CSV import | Always available | 2 | $0 |

---

## 5. MISSING COMPONENTS

Everything except the spec. In build order:

- [x] Python project, git repo, `pyproject.toml`, `.env.example`, `.gitignore`
- [x] `config/product.yaml` (§13), `competitors.yaml` (§12), `sources.yaml`, `scoring.yaml`
- [x] Pydantic models for all 11 tables
- [x] Repository interface, Google Sheets adapter, in memory adapter
- [ ] Google Cloud project, YouTube Data API enabled, API key  **(you)**
- [ ] Google service account, spreadsheet with the 11 tabs shared to it  **(you)**
- [ ] OpenAI API key  **(you)**, LLM client with `cheap` and `strong` tiers, cache, cost log
- [x] 11 prompt files with version headers and JSON schemas
- [x] CLI skeleton and structured logging
- [x] pytest setup, in memory fixtures, recorded LLM fixtures
- [x] Scoring module, pure Python, unit tested
- [x] Embedding model for clustering and originality
- [ ] Slack app, bot token, test channel  **(you)**
- [ ] Telegram bot token  **(you)**
- [x] ~~Meta developer app with ID verification~~  no longer needed, Apify covers US
- [ ] Apify token  **(you)**
- [x] docker-compose with n8n, and the workflow JSON

---

## 6. IMPLEMENTATION PLAN

One phase per session. Nothing starts until the previous phase passes.

### Phase 0: Inspect and plan
- [x] Inspect repo
- [x] Read spec in full
- [x] Data source reality check
- [x] Spec issues and fixes (11 found)
- [x] Cost model
- [x] `docs/PLAN.md` and `CLAUDE.md`
- [x] **Approved 2026-09-10**

### Phase 1: Foundation
- [x] Repo structure, `pyproject.toml`, `.env.example`, `.gitignore`, git init
- [x] `config/product.yaml` with §13's shape, `competitors.yaml` with §12's list
- [x] Pydantic model per table, all 11
- [x] Repository protocol, Sheets adapter, in memory adapter
- [x] LLM client: `cheap` and `strong` tiers, retries with backoff, timeouts, JSON schema validation, token and cost logging, cache keyed on content hash + prompt version + tier (§25, §26)
- [x] Structured logging, `run_id` on every line
- [x] `python -m ci` CLI skeleton
- [x] pytest setup

**Acceptance:** `pytest` green. `python -m ci healthcheck` loads config, confirms every env var, and reads and writes a probe row in Sheets.

### Phase 2: YouTube end to end
- [x] `collectors/base.py` protocol
- [x] `collectors/youtube.py`, US region, quota budget from section 4 enforced in code
- [x] Normalization to `RAW_CONTENT` shape (§5)
- [x] Dedup on `content_id`
- [x] Cheap filter, 100 raw → 50 candidates (§26), pure Python
- [x] Snapshot writing every run
- [x] Quota accounting logged per run

**Acceptance:** run `python -m ci collect youtube` twice in one day. `RAW_CONTENT` gains rows once, `CONTENT_SNAPSHOTS` twice, zero duplicates. I show you 10 sample rows.

### Phase 3: AI analysis
- [x] `01_extract_creative_dna.md` v1 with JSON schema, mechanism not topic (§7)
- [x] `02_classify_hook.md` v1, the 20 hook categories, multiple allowed (§7)
- [x] Cheap tier with cache and schema validation
- [x] Gemini video path for §6 fields, if approved, metadata fallback if not

**Acceptance:** 20 real videos analyzed and saved. Re-run makes zero new LLM calls, all cache hits. **I show you 5 outputs and you judge quality before anything gets built on top.** This is the real gate in the project. If the DNA reads generic, we fix prompts here rather than discover it in Phase 5.

### Phase 4: Patterns, trends, saturation
- [x] Pattern extraction, canonical text, embeddings
- [x] Cross day matching, the three band rule from 3.3
- [x] `03_cluster_patterns.md` for the ambiguous band only
- [x] `scoring/`: momentum, saturation, cross category, opportunity, lifecycle, hook score. Pure Python
- [x] `04_detect_trends.md` and `05_score_saturation.md` rewritten as narrative writers (3.6)
- [x] Merge decision audit log

**Acceptance:** unit tests cover single snapshot low confidence, brand new pattern, single category pattern, three year old viral video versus a fresh fast grower, zero adopters, `days_between` of zero, and momentum falling three days running.

### Phase 5: Generation
- [x] `06_adapt_to_product.md`, `07_generate_hooks.md`, `08_generate_cat_execution.md`, `09_score_hooks.md`
- [x] 5 hooks per pattern for the top 5 patterns, all 10 fields from §14
- [x] Cat as part of the mechanism, 12 roles from §15 rotated, not pasted on
- [x] Hook score with §16's weights, plus strengths, weaknesses, risk, recommended_test
- [x] Quality gate (§27): originality per 3.4, product relevance, weak hook, no clear visual, impossible production, too generic, saturated, unsafe claim
- [x] §28 language check: High / Medium / Experimental / Low opportunity, never "will go viral"
- [x] 70/30 proven versus experimental once winners exist (§21)

**Acceptance:** one full run produces hooks for the top patterns. Every rejection logged with the check that fired and the score. I show you the top 5.

### Phase 6: Daily report and notifications
- [x] §17 full output written to `DAILY_REPORTS`
- [x] §18 concise renderer, Slack first
- [x] Telegram behind the same interface
- [x] `11_generate_daily_report.md`

**Acceptance:** a real report lands in a test Slack channel, each concept fits one phone screen, and the stored report has all three §17 sections.

### Phase 7: Remaining sources
- [x] `collectors/tiktok.py` via Apify, if approved
- [x] `collectors/meta_ads.py`, EU and UK scope
- [x] Competitor tracking from `config/competitors.yaml`
- [x] `collectors/instagram_stub.py`
- [x] `collectors/csv_import.py`

**Acceptance:** kill a source deliberately. The run completes, the failure appears in the run summary as a structured error, the report still ships (§25).

### Phase 8: Performance feedback loop
- [x] `TEST_RESULTS` CSV import, all 21 fields from §19
- [x] Winner rules, configurable thresholds
- [x] `10_analyze_winners.md`, the 8 winning fields from §20, stored in `WINNERS` as reusable patterns
- [x] Winners and losers injected into generation (§21)

**Acceptance:** importing a sample CSV marks winners, extracts their DNA, and the next generation run visibly references them.

### Phase 9: n8n and ops
- [x] `docker-compose.yml` with n8n
- [x] `workflows/n8n/daily.json`, the §23 chain, schedule in `market.timezone`
- [x] Failure alert carrying the run summary
- [x] README with setup from zero

**Acceptance:** clone, fill `.env`, `docker compose up`, get tomorrow's report without touching code.

---

## 7. API REQUIREMENTS

| What | Needed by | Who | Lead time | Cost |
|---|---|---|---|---|
| Google Cloud project + YouTube Data API v3 key | Phase 2 | You or me | minutes | $0 |
| Google service account JSON + spreadsheet shared | Phase 1 | You | minutes | $0 |
| OpenAI API key | Phase 1 | You | minutes | see §8 |
| Gemini API key, if video analysis approved | Phase 3 | You | minutes | ~$7/mo |
| Slack app, bot token, test channel | Phase 6 | You | ~15 min | $0 |
| Telegram bot token | Phase 6 | You | ~5 min | $0 |
| Meta developer app, ID verification | Phase 7 | You | **days, start now** | $0 |
| Apify token, if TikTok approved | Phase 7 | You | minutes | ~$5/mo |

Every one goes in `.env.example` as a named variable with no value. Nothing is ever hardcoded.

---

## 8. ESTIMATED MONTHLY COSTS

Following §26's ladder: **100 raw videos a day → cheap filter → 50 candidates → AI analysis → 20 patterns → detailed analysis → 10 trends → generate for top 5.**

Prices checked 2026-09-10. Cheap tier GPT-5.6-Luna at $0.20 in / $1.20 out per 1M. Strong tier GPT-5.6-Sol at $4 in / $20 out per 1M. Cached input is a tenth of standard, which matters because the prompt template is identical on every call.

### Cheap tier

**Creative DNA + hook classification**, 50 candidates a day, 1,500 a month, two calls each (§24 keeps them separate).

```
DNA:     in 1,100  out 350       Hook:  in 900  out 250
per video: 2,000 in, 600 out
1,500 videos = 3.00M in, 0.90M out
3.00 x 0.20 = $0.60      0.90 x 1.20 = $1.08        $1.68
```

**Trend and saturation narrative** (3.6), 20 patterns a day, 600 a month, in 1,200 out 300.

```
0.72M x 0.20 = $0.14     0.18M x 1.20 = $0.22       $0.36
```

**Hook scoring** (§16), 25 hooks a day, 750 a month, in 1,200 out 400.

```
0.90M x 0.20 = $0.18     0.30M x 1.20 = $0.36       $0.54
```

### Strong tier

**Pattern adjudication** (3.3), about 20 candidates a day, ~25% ambiguous, 5 calls a day, 150 a month, in 2,500 out 150.

```
0.375M x 4 = $1.50       0.023M x 20 = $0.45        $1.95
```

**Generation**, top 5 patterns a day, 150 a month, three calls each (adapt, hooks, cat).

```
adapt in 2,000 out 500 | hooks in 3,500 out 1,500 | cat in 2,500 out 800
per pattern: 8,000 in, 2,800 out
150 patterns = 1.20M in, 0.42M out
1.20 x 4 = $4.80         0.42 x 20 = $8.40          $13.20
```

**Winner analysis**, ~20 a month, in 2,500 out 800.

```
0.05M x 4 = $0.20        0.016M x 20 = $0.32        $0.52
```

**Daily report**, 30 a month, in 6,000 out 1,500 (§17 is a big output).

```
0.18M x 4 = $0.72        0.045M x 20 = $0.90        $1.62
```

### Optional: Gemini video hook analysis

50 candidates a day, 1,500 a month. Shorts average about 35 seconds, video tokens run about 100 per second at default resolution, so 3,500 video tokens plus a 700 token prompt.

```
1,500 x 4,200 in = 6.30M      1,500 x 400 out = 0.60M
Gemini 3.8 Flash $0.75 / $3.75:  4.73 + 2.25 =  $6.98
```

Volume check: 1,500 × 35s ≈ 14.6 hours a month, about half an hour a day, comfortably inside Gemini's free tier cap of 8 hours of YouTube content a day. We can trial it at zero cost.

### Totals

| Line | Monthly |
|---|---|
| Cheap tier: DNA, hook classification, narrative, hook scoring | $2.58 |
| Strong tier: adjudication, generation, winners, report | $17.29 |
| **LLM subtotal** | **$19.87** |
| Plus 30% for retries, cache misses, prompt iteration | **~$26** |

### Apify, now that both sources are approved and built

**TikTok**, `apidojo/tiktok-scraper` at $0.0003 a post. Two passes a day, roughly 100
posts each after the keyword rotation:

```
200 posts/day x 30 days = 6,000 posts
6,000 x $0.0003 = $1.80/month
```

Transcripts are included, so the $0.048 per minute transcript add-on is never used.

**Meta ads**, `apify/facebook-ads-scraper` at $0.0058 an ad, incremental after the
first run:

```
first run:  400 ads x $0.0058 = $2.32   (one time)
then:        30 new ads/day x 30 = 900 x $0.0058 = $5.22/month
```

### Optional: Gemini video hook analysis

Built, off by default. Only YouTube needs it now, since TikTok captions are free.

```
50 YouTube candidates/day x 30 = 1,500 videos
capped at 120s, average about 45s -> 4,500 video tokens + 700 prompt
1,500 x 5,200 in = 7.80M    1,500 x 400 out = 0.60M
Gemini 3.8 Flash $0.75 / $3.75:  5.85 + 2.25 = $8.10/month
```

Volume: 1,500 x 45s is about 19 hours a month, well inside the free tier's 8 hours a
day, so it can be trialled at zero cost first.

### Everything together

| Line | Monthly |
|---|---|
| LLM (OpenAI), with buffer | $26 |
| TikTok via Apify | $2 |
| Meta ads via Apify | $5 |
| YouTube, Sheets, Slack, Telegram, embeddings | $0 |
| **Running total** | **$33** |
| Gemini video analysis (optional) | +$8 |
| Small VPS if n8n needs its own box | +$6 to $12 |

**Realistic monthly cost: about $33, or $41 with video analysis.**

**Sensitivity.** Generation is 66% of the LLM bill, so generating for all 10 trends
instead of the top 5 adds about $13. The 2 minute duration cap is the other big lever:
without it the two longest videos in the live test run alone were 294 and 868 seconds,
which at video-analysis rates would have cost more than the rest of the day combined.
The `LLM_CALLS` table exists so this is visible on day two rather than in the invoice.

---

## 9. RISKS

**1. Output quality is the real risk, not the plumbing.** A technically perfect pipeline that produces five boring hooks is a failed project, and §30 says so in its own words. Phase 3 is a hard gate for this reason. Judge the DNA outputs before we build patterns on top of them.

**2. YouTube quota is a hard ceiling.** 100 searches a day, full stop. With 15 categories in §4 that is about 4 queries per category per day. Discovery breadth is capped by arithmetic, not effort. Mitigation: rotate query sets so a week covers what a day cannot, and use the uploads playlist trick at 1 unit instead of 100 for known channels.

**3. US market plus no TikTok access is a real gap.** The US is the market and TikTok is where a lot of this creative starts. Without it we are reading YouTube Shorts and inferring. Apify at about $5 a month closes it. This is the highest value $5 in the plan.

**4. Google Sheets will become the bottleneck.** It slows badly past roughly 10,000 to 20,000 rows and the API allows about 60 reads and 60 writes per minute. `CONTENT_SNAPSHOTS` grows fastest, roughly 12,000 rows a month at 400 tracked items a day, so Sheets has about a two month runway before it hurts. Mitigation: the repository interface exists from day one precisely so this is a swap and not a rewrite (§22 asks for exactly this), snapshots get rolled up, and we plan the Supabase move around Phase 7 or 8. You already have Supabase available.

**5. TikTok scraping carries terms of service exposure.** §3 permits compliant third parties, and every available provider still operates against TikTok's terms. Decide it deliberately rather than drift into it. Not legal advice.

**6. Pattern merge errors compound silently.** One bad merge poisons momentum, saturation and trend age for that pattern for weeks and nothing surfaces it. Mitigation: every merge logs similarity, decider and runner up, and we eyeball the merge log weekly for the first month.

**7. Originality thresholds are a guess until they meet real data.** Too tight and the report is empty, too loose and the team ships copied wording, which is the one failure §14 and §27 both single out. Mitigation: log every rejection with score and matched source, tune in Phase 5 on real output.

**8. Report fatigue.** If the five ideas are not good in week one, nobody opens it in week three, regardless of code quality. Mitigation: every concept carries its "Why It Matters", the report sorts by opportunity rather than momentum, and we track which ideas actually get produced. That last number is the real success metric for this system.

**9. Meta token expiry, about 60 days.** Then the source silently returns nothing. Mitigation: healthcheck asserts token validity, and the run summary alerts on any source returning zero rows twice running.

**10. The cat becomes wallpaper.** §15 warns about this directly. If the model pastes a cat onto every concept, the creative team stops trusting the output. Mitigation: role rotation is enforced in Python, not requested in the prompt, and the quality gate rejects any concept where removing the cat would not change the mechanism.

**11. One morning run, no second chance.** If the 6am run fails nobody knows until someone asks. Mitigation: failure alert with the run summary, and the report states plainly when data is stale.

---

## Waiting on you before Phase 1

1. **Section 3, the eleven spec fixes.** Especially 3.1 (three scores, and `novelty = 100 - saturation` keeping your §8 weights intact), 3.5 (OpenAI for text, one Gemini adapter for video), 3.6 (scoring in Python, prompts 04 and 05 become narrative writers), 3.8 (§17 stored, §18 sent) and 3.9 (generate for top 5, report top 20).
2. **Gemini video analysis, about $7 a month.** Without it, `first_3_second_description`, `visual_hook` and `on_screen_text` are guesses from the title. Free tier covers our volume for a trial.
3. **TikTok via Apify, about $5 a month.** US market, and you already have Apify connected.
4. **Local embedding model** as a Python dependency.
5. **Repo root**: keep it here, or nest in `creative-intelligence/` as §29 shows.
6. **Start Meta developer ID verification now** if Phase 7 should land on time.
7. The Google Sheet itself, with the 11 tabs, shared to a service account.

---

## Sources

* [YouTube API quota costs and limits](https://outlierkit.com/resources/youtube-api-quota/)
* [YouTube Data API quota cost documentation](https://developers.google.com/youtube/v3/determine_quota_cost)
* [TikTok Research Tools: Access and Eligibility](https://developers.tiktok.com/products/research-api/)
* [TikTok data API providers and pricing 2026](https://www.socialcrawl.dev/blog/best-tiktok-data-apis-2026)
* [Meta Ad Library API limitations 2026](https://adlibrary.com/posts/meta-ad-library-api-limitations)
* [Instagram official APIs reference, April 2026](https://gist.github.com/jameschapman2c/65eff9f54a2d350b17a6ce5127b9fe42)
* [Gemini API video understanding](https://ai.google.dev/gemini-api/docs/video-understanding)
* [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)
* [OpenAI API pricing](https://developers.openai.com/api/docs/pricing)
* [OpenAI native video input feature request](https://github.com/openai/openai-node/issues/1778)
