# CLAUDE.md

## Project purpose

A Daily Creative Intelligence System for a consumer English learning app whose mascot is a cat.

It answers one question every morning:
**"What are the 5 most interesting creative ideas we should test today, and why?"**

Not a viral video scraper. The chain is: detect emerging creative patterns → understand why they work → adapt the pattern to the product → generate original hooks → rank them → learn from our own ad performance.

Every design decision serves the morning question. Useful to a growth and creative team beats technically impressive. If a feature does not make the report better, it does not get built.

**Market: United States.** All discovery, competitor research, hooks, slang and cultural references are built for US audiences first. Global content is a secondary signal only and must be tagged with its country.

* Product spec: `docs/SPEC.md` (source of truth for WHAT)
* Implementation plan: `docs/PLAN.md` (living, with checkboxes)

## Current phase status

| Phase | State |
|---|---|
| 0. Inspect and plan | Complete |
| 1. Foundation | Complete |
| 2. Sources end to end | Complete. TikTok verified against live US data. |
| 3. AI analysis | Complete. Needs `OPENAI_API_KEY` to judge output quality. |
| 4. Patterns, trends, saturation | Complete |
| 5. Generation | Complete |
| 6. Daily report and notifications | Complete. Needs `SLACK_BOT_TOKEN` to send. |
| 7. Remaining sources | Complete. Competitor UGC and Meta ads verified live. |
| 8. Performance feedback loop | Complete |
| 9. n8n and ops | Complete |

**117 tests passing. The pipeline runs end to end on real US TikTok data.**

What is left is credentials, not code. Fill `.env`, then `python -m ci healthcheck`.
The one thing still genuinely unproven is **output quality**, because that needs a real
model. Run `python -m ci analyze dna --limit 20` with an OpenAI key and read five
outputs before trusting anything downstream of them.

No code has been written. The repo contains `CLAUDE.md`, `docs/SPEC.md` and `docs/PLAN.md`.

**Do not start Phase 1 until section 3 of `docs/PLAN.md` is approved.** It contains 11 spec fixes, five of which change behaviour: the Trend Score split, the OpenAI plus Gemini provider split, scoring moving out of prompts into Python, the stored versus sent report split, and the hook count.

## How to run each stage

None of these exist yet. This is the target shape, defined in Phase 1, filled in as phases land.

```bash
python -m ci healthcheck              # config loads, env vars present, Sheets reachable
python -m ci collect youtube          # discover, normalize, dedup, cheap filter, snapshot
python -m ci collect tiktok
python -m ci collect meta_ads
python -m ci collect csv --path FILE
python -m ci analyze dna              # creative mechanism extraction, cheap tier, cached
python -m ci analyze hooks            # hook classification, cheap tier, cached
python -m ci patterns cluster         # extract, embed, match across days, merge
python -m ci patterns score           # momentum, saturation, cross category, opportunity
python -m ci generate                 # adapt, hooks, cat execution, score, quality gate
python -m ci report                   # render §17 output, store in DAILY_REPORTS
python -m ci notify slack             # send the §18 concise report
python -m ci import ads --path FILE   # TEST_RESULTS CSV, winner marking, winner DNA
```

Every stage reads from storage and writes to storage. Every stage is runnable and testable on its own. n8n schedules and chains these commands and holds zero logic.

## Test commands

```bash
pytest                    # full suite
pytest -m unit            # fast, no network, no API keys, in memory repo
pytest -m integration     # touches Sheets and live APIs, needs .env
ruff check .
ruff format .
```

The unit suite must run with no network and no API keys. Tests use the in memory repository adapter and recorded LLM fixtures.

## Conventions

### Architecture rules, non negotiable

1. **Source adapters.** Every source implements `fetch() -> list[NormalizedContent]`. Adding, swapping or deleting a source touches nothing downstream.
2. **Storage adapters.** Intelligence code talks to the repository interface, never to Google Sheets directly. Sheets is adapter one. Postgres, Supabase, Airtable and BigQuery must be addable later without changing a line of intelligence code.
3. **LLM adapter.** One client wrapper. Tiers `cheap` and `strong`. Retries, timeouts, JSON schema validation, token and cost logging, and a cache keyed on content hash plus prompt version plus tier. Provider swappable via config.
4. **Prompts live in `prompts/*.md`**, each with a version header and a defined JSON output schema. No prompt text inside Python, ever.
5. **Product profile lives in `config/product.yaml`.** No product, mascot or audience assumption appears anywhere else. If you find one, it is a bug. This includes the two product components of the Trend Score, which are computed by prompt against the config and passed into the scorer as plain numbers.
6. **Every stage is a CLI command** reading from and writing to storage. All real logic in Python so it is testable without n8n.
7. **Failure isolation.** One source or one item failing logs a structured error and the run continues. The run summary lists what failed. If TikTok dies, YouTube and Meta still ship.
8. **Idempotent.** Re-running a day never creates duplicates. `content_id` is the platform ID, or `sha256(canonical_url)[:16]`.

### Working rules

* Work in phases. Never start the next until the current one passes its acceptance checks.
* End of every phase: run tests, run the stage on real or sample data, fix errors, then report what changed, what works, what does not, what Hemant needs to do.
* Ask before any major architecture change, before adding a paid service, and before anything that costs money to run.
* Never hardcode secrets. Everything through env vars listed in `.env.example`.
* Never invent API capabilities. If unsure an endpoint exists or what it returns, say so and check the docs or test it. Do not write a collector until access is confirmed.
* Update this file and tick `docs/PLAN.md` at the end of every phase.

### Code conventions

* Python 3.11, `uv`, `ruff`, `pytest`. Src layout: package is `src/ci/`, so `python -m ci` works and §29's folder names are preserved.
* Pydantic models for every table. Nothing untyped crosses a module boundary.
* Structured JSON logging with `run_id` on every line.
* **Scoring math is pure Python with unit tests, never in a prompt.** An LLM cannot be unit tested for arithmetic.
* Thresholds and weights live in `config/scoring.yaml`. Never literals in code.
* Prompt version bumps invalidate the cache. That is the point of the cache key.
* **Never write prediction claims.** High / Medium / Experimental / Low opportunity only. Never "this will go viral". The quality gate enforces it.

## Tables

Spec §22 names 8 tabs. Three more are added for reasons in `docs/PLAN.md` sections 3.2 and 2.

`RAW_CONTENT`, `HOOKS`, `CREATIVE_PATTERNS`, `TRENDS`, `ADAPTATIONS`, `TEST_RESULTS`, `WINNERS`, `DAILY_REPORTS`, plus `CONTENT_SNAPSHOTS` (velocity needs two readings), `RUN_LOG` (§25 needs somewhere to land), `LLM_CALLS` (§26 needs to be enforceable).

`CREATIVE_PATTERNS` is persistent across days and must never be recreated. `TRENDS` is one row per pattern per day.

## Scoring model

The spec's single Trend Score was split, because one number cannot mean both momentum and saturation while §8's label table calls a high score Exhausted and §18's sample report calls 91 a five star PRODUCE. Full derivation in `docs/PLAN.md` section 3.1.

**§8's weights are unchanged.** The one change is `novelty = 100 - saturation_score`, which makes the formula self penalising, exactly as §8 asks.

```
momentum_score     0-100   how fast it is growing right now
saturation_score   0-100   how crowded it already is
opportunity_score  = 0.30 momentum + 0.20 cross_category + 0.20 (100 - saturation)
                   + 0.15 audience_relevance + 0.15 product_applicability
lifecycle_label    Emerging | Rising | Saturating | Exhausted, from momentum AND saturation
```

**The daily report sorts by `opportunity_score`.** That is the number that answers the morning question. Momentum and saturation are still shown, because the creative team needs to see why.

Velocity needs two snapshots at least 12 hours apart. With one snapshot, fall back to views per day since publish, mark it low confidence, and multiply momentum by 0.7 so it cannot top the report on its own. Only content published within `lookback_days` (default 30) feeds momentum, so a three year old viral video does not read as a rocket.

## Data source status

Verified 2026-09-10. Details and sources in `docs/PLAN.md` section 4.

| Source | Status |
|---|---|
| YouTube Data API v3 | Available. 10,000 units a day. `search.list` costs 100, so 100 searches a day maximum. Budget enforced in code. `regionCode=US`. |
| YouTube transcripts | Not available via the official API for videos we do not own. `captions.download` needs ownership. |
| Gemini video analysis | Built, off by default. Set `CI_VIDEO_PROVIDER=gemini`. Only YouTube needs it now. About $8 a month. |
| OpenAI | Default provider for all 11 text prompts per §2. **Has no native video input**, which is why the Gemini adapter exists. |
| TikTok | **Built.** Apify `apidojo/tiktok-scraper`, $0.0003 a post, verified live. Two passes: MOST_LIKED for what is big, DATE_POSTED for what is climbing. Auto-captions included free, so TikTok transcripts cost nothing. |
| Meta Ad Library | **Built via Apify**, because the official API returns no US commercial ads and every competitor in config is a US commercial advertiser. Incremental after the first run. |
| Instagram | No trend discovery API for content we do not own. Hashtag Search is capped at 30 hashtags per 7 days and cannot return usernames. Stub plus CSV import. |

## The viral radar

Competitor Hook Radar was merged into this repo on 2026-09-10 rather than run as a second
system. One schedule, one report, one bill.

**`python -m ci radar` is the headline output.** Per video, not per pattern: which
competitor video is taking off or about to, with link, title, creator, date and every
number behind it. No LLM call, so it costs nothing and can run more than once a day.

```bash
python -m ci collect competitor_ugc   # UGC mentioning any of the 17 competitors
python -m ci collect meta_ads         # their US ads, with days running
python -m ci radar                    # the feed
python -m ci watch                    # re-poll candidates, every 30 min
python -m ci notify-radar slack
python -m ci sheets-push              # into "Competitor Viral Radar" in Drive
```

Full detail in `docs/RADAR.md`.

### We track videos and hooks, not accounts

Two rules follow, both enforced in `collectors/competitor_ugc.py`:

* **Posts made BY a competitor's own account are dropped.** `brand_handles()` collects
  every known handle and filters them out. A brand posting its own content is marketing,
  not a signal that anything is spreading.
* **Duolingo was removed from the competitor list entirely on 2026-09-10.** 18M followers
  meant its own posts flooded the feed, and "duolingo" as a search term dragged in Gacha
  Club memes, Roblox videos and anime rants. **17 competitors remain. Do not add it back.**

### Takeoff detection

The question is not "most views", it is "which video is behaving abnormally well for how
old it is".

* **Views relative to AGE**, via an expected-views curve, with `vs_expected` as the ratio.
* **Already-viral is PENALISED, not promoted.** 500K+ views and older than 48h gets a
  0.25x multiplier. We hunt takeoff, not history.
* **Distribution waves** are the strongest signal: an hour whose view rate is 1.5x the
  hour before. 1K to 2.5K to 7K to 22K to 70K is 4 waves and reads VIRAL. 20K to 22K to
  24K to 25K is 0 waves and reads FLAT, despite more views early on.
* **`ci watch`** re-polls every 30 minutes, because a daily snapshot cannot see an hourly
  wave. It is what makes waves measurable at all.
* **shares/views carries the heaviest weight** of the four engagement ratios, and a
  normal-band share rate with no waves takes a 0.7x penalty. Being watched is not the same
  as spreading.
* **Watch time, completion and rewatch are absent on purpose.** Creator-side analytics,
  invisible for a competitor's video. Not estimated, not faked.

### The baseline is learned, not guessed

`expected_curve` in config is a cold-start fallback only. `learn_baseline_curve()` replaces
it with our own observed medians per age bucket once there are 8+ samples.

This mattered: a curve set at viral-trajectory numbers (1h to 5K, 12h to 150K) made every
real video read as below par and killed the pace signal entirely. The real median in a US
pull was about 8.5K views at 18 hours. Those original numbers now live in `viral_curve`,
where they define what a 100 pace score means.

### Ads are scored differently, on purpose

The Meta Ad Library publishes no views, likes or spend for US commercial ads, so ads get
`winner_signal`: days running, variations, relaunch, platforms, hook reuse. Scoring ads on
views put a Linguza ad running 99 days with 5 variations at the bottom of the feed.

### History and trends

**Nothing in RADAR is ever overwritten.** It is keyed on `(date, content_id)`, so every
day's rows accumulate. That is the only reason `ci trends` can exist: a sheet or table that
overwrites itself can never tell you a video has been climbing for four days.

`ci trends` computes, needing 2+ days of history:

* **Per video**: direction (RISING / FALLING / FLAT / NEW), score delta, views gained, rank
  change, days on radar, peak score, and a 14 day mini history.
* **Per competitor**: videos on the radar vs yesterday, average score, direction. Direction
  weighs BOTH count and score, because counting videos alone called a competitor FLAT while
  its average fell from 74 to 53.
* **Hashtags**: which tags are appearing more than they were.
* **Dropped off**: what was on the radar yesterday and is not today.

### The shared Google Sheet

"Competitor Viral Radar — UGC", id `1mioM_FQSkLYjMX6X9wzbfM_Lo2W81lU1LN_Db06M4mg`.
**Must be shared with the service account as Editor or every write returns 403.**

**The sheet is the endpoint.** Both flows end there. Slack is a notification, not
a destination — if it fails, the day's work is still in the sheet.

Ads and UGC get their own tabs. They are scored on different signals (ads on days
running and variation count, UGC on waves, share rate and views-against-age), so a
shared tab leaves every column blank for half the rows.

| Tab | Written by | Behaviour |
|---|---|---|
| `UGC_TODAY` | ugc flow | replaced every morning, what is hot now |
| `UGC_HISTORY` | ugc flow | **accumulates, never overwritten** |
| `ADS_TODAY` | ads flow | replaced every morning |
| `ADS_HISTORY` | ads flow | **accumulates** |
| `DAILY_BRIEF` | both | Claude's written read, one row per day per flow |
| `VIDEO_TRENDS` | ugc flow | day over day per video |
| `COMPETITOR_TRENDS` | ugc flow | day over day per competitor |
| `HASHTAG_TRENDS` | ugc flow | which tags are rising |
| `RUN_LOG` | both | what ran, what failed |

Only the `*_TODAY` tabs are replaced. Everything else merges, so history survives —
and trends are only computable from kept history.

```bash
ci sheets-push --kind ugc     # UGC tabs + trends
ci sheets-push --kind ads     # ads tabs only
ci sheets-push                # everything
```

### Scheduling: n8n, over HTTP

n8n schedules and chains. It holds no logic. Full detail in `docs/OPERATIONS.md`.

**n8n talks to the `ci` service over HTTP, never by shelling into it.** The first version
used `docker compose exec` from inside the n8n container, which cannot work because that
image has no docker CLI, and mounting the docker socket to get one is a privilege
escalation nobody should accept on a box running unattended jobs.

```
n8n --HTTP--> ci:8000/run/<stage> --> storage
```

`python -m ci serve` runs it. Stdlib only, no web framework. Every response carries
`ok`, `status`, `counts` and `failures` so n8n can branch on it.

* **`status: partial` is NOT an error.** It means a source failed and the run continued,
  which is architecture rule 7 working. Alert on `failed` and on non-empty `failures`.
* **Two stages never run at once**; the second gets a 409 rather than queueing. Concurrent
  runs would double-write snapshots and corrupt the velocity history.
* The port is `expose`d, not published. If it is ever reachable externally, set
  `CI_API_TOKEN`; it is enforced when present. These endpoints spend money.

| Workflow | Schedule | Notes |
|---|---|---|
| `workflows/n8n/daily.json` | 6am America/New_York | collectors run in parallel and are continue-on-error; only `radar` may halt the chain |
| `workflows/n8n/watch.json` | every 30 minutes | silent unless 3+ videos moved or the run failed. It fires 48 times a day. |

The Claude scheduled tasks that briefly existed were deleted. **Do not run both schedulers**
against the same storage: double-writing snapshots corrupts wave detection.

### Silent throttling on the Apify free tier

Verified 2026-09-10: `elsa speak` returned 10 real videos, then returned
`[{"noResults": true}]` eight minutes later with identical input. The free tier throttles
after roughly 5-6 search calls and reports it as an empty result, not an error.

Handled in `collectors/apify.py`. Three empty results in a row raises `ApifyThrottled`,
stops the sweep, and records the remaining keywords as **NOT CHECKED**, which is a
different thing from zero. Never conflate them: a false zero poisons the learned baseline
and every trend line built on it.

**57 keywords across three recency passes is about 171 calls a day, so a paid Apify plan
is required.** The free tier gives you five.

### Collection is recency-first

Sorting by most-viewed only ever finds what already happened. Passes run `DATE_POSTED`
over YESTERDAY and THIS_WEEK first, with a small most-liked pass kept only as context.

## What is left for Hemant

1. **A paid Apify plan.** The free tier throttles at ~5 search calls; a full sweep needs
   ~171 a day. This changes the earlier cost estimate and needs re-pricing before you
   commit to a number.
2. **`APIFY_TOKEN`, `OPENAI_API_KEY`, `YOUTUBE_API_KEY`** in `.env`. The radar itself needs
   no OpenAI key, so it can run before the rest.
3. **Share "Competitor Viral Radar" with the service account as Editor**, or `sheets-push`
   writes will 403. Sheet id `1F1HXw28xLUsOF2gUhlmBhgMnSrkpYbEHetNxnLTgdbk`.
4. **Verify 14 competitor handles.** Only Loora, Linguza and ELSA are confirmed. Parrot,
   Learna, Fluzy, Lingopanda and Falou are generic enough names that they will pull noise.
5. **Judge Phase 3 output quality** once the OpenAI key is in. That is still the real gate.
6. **Schedule `ci watch` every 30 minutes**, separately from the morning run. Without it,
   distribution waves are never measurable and the radar loses its strongest signal.


## Apify: the one thing that blocks everything

Verified 2026-09-11 by running out of credit mid-session.

* Free plan gives about $5 a month, roughly 600 videos through the expensive
  actor. It does not last a day of real use.
* `apidojo/tiktok-scraper` is $0.0003/video flat, no add-on charges, and is the
  configured primary. On a FREE plan it returns the `{"noResults": true}`
  sentinel for every call including direct video URLs, so it is paid-only.
* `clockworks/free-tiktok-scraper` works on free: $0.003/result plus $0.0013
  each for the sorting, date and country filters a keyword search needs.

The collector runs the primary and falls back to the secondary on throttle,
recording `actor_used` and `fell_back`. Cost at full volume, 855 videos a
morning plus 2,880 watch polls a day:

| actor | per month |
|---|---|
| apidojo | **$34** |
| clockworks | **$436** |

Search and direct-URL polls are priced separately in `actor_inputs`, because a
poll buys none of the charged filters. Using one number for both overstates the
watch bill by about 2.3x.
