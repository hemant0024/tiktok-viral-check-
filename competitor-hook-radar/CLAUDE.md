# CLAUDE.md

## Project purpose

Competitor Hook Radar. It finds the UGC style video ads and viral videos our 18
competitors are using to win in the US, pulls out the hooks that are working, and turns
them into 5 original ads we should make today.

The question it answers every morning:
**"Which competitor hooks are working right now, and what 5 ads should we make today because of them?"**

**We track videos and hooks, not accounts.** Follower counts and brand pages do not
matter. What matters is what is said and shown in the first 3 seconds, how long an ad has
been running, and how many versions the brand made of it.

Market: United States only.
Product: English learning app with a cat mascot. All product facts live in `config/product.yaml`.

* Spec: `docs/SPEC.md` (source of truth for what to build)
* Plan: `docs/PLAN.md` (living, with checkboxes)

## Current phase status

| Phase | State |
|---|---|
| 0. Plan | **Complete, awaiting approval** |
| 1. Foundation | Not started |
| 2. Competitor ads, one source | Not started |
| 3. Hook extraction | Not started |
| 4. Winner scoring and patterns | Not started |
| 5. Generate our hooks | Not started |
| 6. Slack report | Not started |
| 7. All 18 competitors plus organic | Not started |
| 8. Our ad results loop | Not started |
| 9. Schedule and docs | Not started |

No code written. The repo holds `CLAUDE.md`, `docs/SPEC.md` and `docs/PLAN.md`.

**Do not start Phase 1 until the source recommendation in `docs/PLAN.md` section 3 is
approved,** because it decides what Phase 2 is built against.

**Do not start Phase 3 until one real video download is confirmed** on the machine that
will run this. See the risk in `docs/PLAN.md` section 8.

## How to run each stage

None of these exist yet. Target shape, defined in Phase 1.

```bash
python -m chr healthcheck                 # config, storage, prompts, which keys are missing
python -m chr collect meta_ads            # US competitor ads via Apify
python -m chr collect tiktok_cc           # TikTok Creative Center Top Ads
python -m chr collect tiktok_organic      # organic UGC mentioning competitors
python -m chr collect youtube             # Shorts
python -m chr collect manual --path f.csv # team link drop
python -m chr extract hooks               # download, trim 0-3s, transcribe, extract
python -m chr score winners               # Winner Signal Score, Viral Score
python -m chr patterns cluster            # group hooks across competitors
python -m chr generate                    # 5 hooks per pattern, UGC + cat versions
python -m chr report --show               # build today's report
python -m chr notify slack                # send it
python -m chr import ads --path r.csv     # our ad results, winner analysis
python -m chr pipeline --notify slack     # whole morning run
```

Every stage reads from storage and writes to storage and runs on its own. n8n only
schedules them.

## Test commands

```bash
pytest
pytest -m unit            # no network, no keys
ruff check .
```

**Never create a virtualenv inside a connected folder.** It is a mounted share that does
not allow deletes, so a bad `.venv` cannot be removed. Put it outside the repo.

## Conventions

### Architecture rules

1. **Source adapters.** Every source implements `fetch() -> list[NormalizedVideo]`. Swapping a source changes nothing downstream.
2. **Storage adapters.** Logic talks to the repository interface, never to Sheets directly. Sheets first, Supabase later.
3. **One LLM wrapper.** Cheap and strong tiers, retries, timeouts, JSON schema validation, caching, cost logging.
4. **Prompts live in `prompts/*.md`**, versioned, with a JSON output schema. Never inside code.
5. **Competitors, product, mascot, audience, market and scoring weights live in `config/`.** Nothing hardcoded.
6. **Every stage is a CLI command.** All logic in Python so it is testable without n8n.
7. **Failure isolation.** One source or one video failing gets logged and the run continues.
8. **Idempotent.** Re-running the same day never creates duplicates. `video_id` is the platform ad or post ID, else a hash of the URL.

### Code conventions

* Python 3.10+, `uv`, `ruff`, `pytest`. Src layout: package is `src/chr/`.
* Pydantic models for every table.
* Structured JSON logging with `run_id` on every line.
* **Scoring math is pure Python with unit tests, never in a prompt.**
* Thresholds and weights live in `config/scoring.yaml`.
* Prompt version bumps invalidate the cache.
* **Never write prediction claims.** The spec's labels only: Proven winner, Likely winner, New watch it, Test signal only. Never "will go viral" or "will convert".

## Data source status

Verified 2026-09-10 by live test, not by reading product pages. Detail in `docs/PLAN.md` section 3.

| Source | Status |
|---|---|
| Meta Ad Library official API | **Unusable for us.** Political ads worldwide, plus any ad delivered to UK/EU. No US commercial ads. |
| Apify `apify/facebook-ads-scraper` | **Primary, verified live.** Start date, isActive, full copy, CTA, landing page, and real MP4 URLs. $0.0058/ad. |
| Apify `dltik/tiktok-creative-center` | US Top Ads with CTR, likes, 720p MP4, and per-second retention on enrich. $0.0035/ad. |
| Apify `apidojo/tiktok-scraper` | Organic UGC, $0.0003/post, US filter, auto-captions free. |
| YouTube Data API | Free. 100 searches a day is the hard ceiling. |
| Foreplay | Documented backup. Real API at $99/mo, but $459/mo seat for 18 brands. Unverified by me. |
| PiPiAds, BigSpy, Minea, AdSpy | **UI only, no public API.** Ruled out for an automated pipeline. |
| Instagram organic | No discovery API for content we do not own. Manual drop only. |

## Three gotchas found by testing

Do not undo these, they cost real time to find.

1. **`totalActiveTime` is null on every US ad** despite the actor advertising it. Days running is `endDate - startDate`.
2. **`collationCount` is not the variation count.** It was null on half the ads and 1 on the rest. Linguza had five separate ad IDs all titled "Try free now!" with `collationCount` = 1 each. We derive variation groups ourselves. Definition is in `docs/PLAN.md` section 5, and Linguza is the unit test fixture.
3. **Dynamic creative ads return template placeholders.** A Duolingo ad came back with `snapshot.title` = `{{product.name}}` and `displayFormat` = `DCO`. Filter these out or they pollute the hook corpus.

## The two signals everything rests on

We cannot see competitor conversions. Nobody can. Days running and variation count carry
the whole Winner Signal Score, so both are handled carefully.

* **`startDate` never changes.** Only "is it still active" changes. So daily runs discover new ads, and a weekly full sweep catches ads that died. Worst case an ad reads active for six extra days, which is noise against 30 and 60 day thresholds, and it cuts the Meta bill from $125 to $22 a month.
* **A variation group** is ads from the same page whose normalized copy has trigram Jaccard above 0.75, or which share a non-null `collationId`. Variation count is the size of that group among active ads. Grouping also gives relaunch detection free.

## Open questions for Hemant

1. Approve the source recommendation: Apify primary, Foreplay backup, manual drop always on. About $66 a month.
2. Confirm the spend ceiling.
3. Run one video download test on the machine that will host this. Both my sandboxes proxy-blocked `fbcdn.net`, so this is genuinely unproven.
4. Keys at Phase 1: `APIFY_TOKEN`, `OPENAI_API_KEY`, `YOUTUBE_API_KEY`, Slack bot token, Google Sheet shared to a service account.
5. Say if you would rather pay for Foreplay and take the lower ToS risk. It changes Phase 2, not the architecture.
