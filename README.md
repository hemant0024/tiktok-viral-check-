# Daily Creative Intelligence System

Finds emerging creative patterns on TikTok and YouTube, works out why they work, adapts
them into original hooks for an English learning app with a cat mascot, scores them, and
sends one short report every morning.

It answers one question:
**"What are the 5 most interesting creative ideas we should test today, and why?"**

Market: United States.

---

## Setup from zero

```bash
git clone https://github.com/hemant0024/tiktok-viral-check-.git && cd tiktok-viral-check-
cp .env.example .env          # then fill it in, see below
docker compose up -d
docker compose exec ci python -m ci healthcheck
```

If the healthcheck is green, run a day:

```bash
docker compose exec ci python -m ci pipeline --notify slack
```

Then import `workflows/n8n/daily.json` at http://localhost:5678 and activate it. It runs
at 6am in the timezone set in `config/product.yaml`.

### Running it without Docker

```bash
uv venv && uv pip install -e ".[dev]"
cp .env.example .env
python -m ci healthcheck
python -m ci pipeline
```

---

## What you need in `.env`

| Variable | Needed for | Cost |
|---|---|---|
| `OPENAI_API_KEY` | all analysis and generation | about $20/month at 100 videos a day |
| `APIFY_TOKEN` | TikTok and Meta ads | about $7/month |
| `YOUTUBE_API_KEY` | YouTube | free, 10,000 quota units a day |
| `GOOGLE_SERVICE_ACCOUNT_JSON` + `GOOGLE_SHEET_ID` | Sheets storage | free |
| `SLACK_BOT_TOKEN` + `SLACK_CHANNEL` | the daily report | free |
| `GEMINI_API_KEY` | optional video analysis | about $7/month |

Nothing is ever hardcoded. Everything is read through `.env` and `config/*.yaml`.

**Start with `CI_STORAGE_BACKEND=local`.** It writes JSONL into `./data` and needs no
Google credentials at all, so you can run the whole pipeline the day you clone it. Switch
to `sheets` when the sheet is ready. The intelligence code never knows the difference.

---

## Stages

Every stage reads from storage and writes to storage, and each one runs on its own.
n8n only schedules and chains them. All the logic is in Python, so it is testable
without n8n.

```bash
python -m ci healthcheck              # config, storage, prompts, which keys are missing
python -m ci collect all              # every enabled source
python -m ci collect tiktok           # or one at a time
python -m ci collect csv --path f.csv # manual import, works for any source
python -m ci analyze dna              # creative mechanism + hook breakdown, cheap tier
python -m ci patterns cluster         # match today's patterns to existing ones
python -m ci patterns score           # momentum, saturation, opportunity
python -m ci generate                 # hooks, cat executions, scoring, quality gate
python -m ci report --show            # build and print today's report
python -m ci notify slack             # send it
python -m ci import ads --path r.csv  # ad results, winner marking, winner DNA
python -m ci pipeline --notify slack  # the whole morning run
```

A failing source never ends a run. It is logged as a structured error, the run
continues, and the report says at the bottom what it is missing.

---

## How the scoring works

The spec had one Trend Score doing two opposite jobs: every component of its formula
was a good thing, yet a high score was labelled Exhausted, and the sample report showed
91 with low saturation as a five star produce.

The weights are unchanged. The one change is that novelty is defined as
`100 - saturation`, which makes the formula penalise crowding on its own.

```
momentum_score     how fast it is growing right now
saturation_score   how crowded it already is
opportunity_score  0.30 momentum + 0.20 cross_category + 0.20 (100 - saturation)
                   + 0.15 audience_relevance + 0.15 product_applicability
lifecycle_label    Emerging | Rising | Saturating | Exhausted, from momentum AND saturation
```

**The report sorts by opportunity, not momentum.** Momentum and saturation are still
shown, because the team needs to see why.

### Catching things on the way up

Absolute views tell you what already happened. This system is built to find what is
happening now.

- Every run writes a **snapshot**, so growth is measured between two real readings
  rather than as a lifetime average. One snapshot is marked low confidence and
  discounted by 30 percent so it cannot top the report on its own.
- Three readings give **acceleration**. A video that is speeding up gets a momentum
  bonus; one that has plateaued does not.
- The cheap filter **ranks by heat** rather than just cutting, and reserves 40 percent of
  the candidate slate for young climbers, so yesterday's big winners cannot crowd out
  today's breakouts.
- Only content published inside the lookback window feeds momentum, so a three year old
  video with 10 million views does not read as a rocket. Older content is kept as
  reference material for creative DNA.
- TikTok is collected in two passes every run: `MOST_LIKED` for what is already big and
  `DATE_POSTED` for what is climbing. The contrast between them is the signal.

Videos over **2 minutes are dropped**. Hooks live in short form, and duration is the
single biggest lever on analysis cost.

---

## Configuration

| File | What lives there |
|---|---|
| `config/product.yaml` | market, product, mascot, audience. The only place these exist. |
| `config/competitors.yaml` | the competitor list, editable without touching code |
| `config/sources.yaml` | categories, query rotation, quota budgets, actor names |
| `config/scoring.yaml` | every weight and threshold in the system |
| `config/llm.yaml` | model tiers and per-token prices |
| `prompts/*.md` | all 11 prompts, each with a version header and a JSON schema |

Bumping a prompt's version invalidates its cache. That is the point of the cache key.

---

## Tests

```bash
pytest              # everything
pytest -m unit      # no network, no API keys
ruff check .
```

The unit suite runs with no credentials, using the in memory repository and a fake
LLM provider that builds its answers from each prompt's own JSON schema, so the real
validation path is exercised rather than a hand-written happy answer.

---

## What each data source can actually do

Verified 2026-09-10. Full detail in `docs/PLAN.md`.

| Source | Reality |
|---|---|
| YouTube Data API | Free. 10,000 units a day, and `search.list` costs 100, so 100 searches a day is the hard ceiling. The budget is enforced in code. |
| YouTube transcripts | Not available for videos you do not own. Optional Gemini video analysis is the only compliant route to the visual fields. |
| TikTok | No official access. The Research API is academic and non-profit only. Collected through Apify at $0.0003 a post. Auto-captions come back in the same result at no extra cost. |
| Meta Ad Library API | Returns commercial ads only for EU and UK target countries, so it returns nothing for US competitors. Collected through Apify instead. |
| Instagram | No trend discovery API exists for content you do not own. Stub adapter plus CSV import. |

---

## Repo layout

```
src/ci/
  collectors/   one adapter per source, all returning the same shape
  processors/   dedup, snapshots, cheap filter
  analyzers/    creative DNA, hooks, video, winners
  patterns/     embeddings, cross-day matching
  scoring/      velocity, momentum, saturation, opportunity. Pure Python, unit tested.
  generators/   adaptation, hooks, cat execution, originality, quality gate
  database/     repository interface, Sheets, local JSONL, in memory
  notifications/slack, telegram
  llm/          one client: tiers, retries, schema validation, cache, cost log
```

Adding a source means writing one adapter with a `fetch()` method. Nothing downstream
changes. Moving off Sheets means writing one repository adapter. Same deal.
