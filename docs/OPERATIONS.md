# Running it

n8n schedules and chains. It holds no logic. Everything real is a Python stage that
reads from storage and writes to storage, reachable over HTTP.

## Setup from zero

```bash
cp .env.example .env          # then fill it in
docker compose up -d
docker compose logs -f ci     # wait for "server listening"
curl localhost:5678           # n8n
```

Import the two workflows at http://localhost:5678, then activate them:

| File | Schedule | What it does |
|---|---|---|
| `workflows/n8n/daily.json` | 6am America/New_York | collect, radar, trends, sheet, Slack |
| `workflows/n8n/watch.json` | every 30 minutes | re-polls the watchlist so waves are measurable |

## Why HTTP and not `docker exec`

The first version had n8n shell out with `docker compose exec`. That cannot work: the
n8n image has no docker CLI. Mounting the docker socket to get one would work, and is a
privilege escalation nobody should accept on a box that runs unattended jobs.

So the `ci` service exposes a small stdlib HTTP server and n8n makes HTTP requests. It
gets structured JSON back and can branch on it. Same behaviour on a laptop, a VPS, or
split across two machines.

```
n8n  --HTTP-->  ci:8000/run/<stage>  -->  storage (local JSONL or Sheets)
```

The port is `expose`d, not `ports`d, so nothing outside the compose network can reach it.
If you ever publish it, set `CI_API_TOKEN` and it is enforced. These endpoints spend money.

## The endpoints

```bash
GET  /health                  # what is running, and every stage name
GET  /prompt/<name>           # a prompt from prompts/*.md, for the Claude node
POST /run/<stage>             # run one stage, get JSON back
```

Stages that take input read a JSON body: `{"brief": "..."}` for `save_brief`,
`{"limit": 12}` for `brief_input_*`.

Every response carries what n8n needs to branch:

```json
{"ok": true, "stage": "radar", "status": "ok",
 "duration_seconds": 12.4, "counts": {...}, "failures": [], "result": {...}}
```

`status` is `ok`, `partial` or `failed`. **`partial` is not an error.** It means a source
failed and the run continued, which is the design. The daily workflow alerts on `failed`
and on any non-empty `failures`, and stays quiet on a clean run.

Two stages never run at once: the second gets a `409` rather than being queued. Two
concurrent runs would double-write snapshots and corrupt the velocity history that the
whole wave detection depends on.

## Two flows, not one

Ads and UGC run as separate workflows. They are not the same job:

|  | UGC | Ads |
|---|---|---|
| source | TikTok search, via Apify | Meta Ad Library, via Apify |
| has view counts | yes | **no** — Meta publishes none for US commercial ads |
| scored on | waves, share rate, views-against-age, creator lift | days running, variation count |
| day-over-day trends | yes | not applicable, there is no velocity to trend |
| runs at | 6:00 | 6:45 |

Splitting them buys three things. A throttled TikTok actor no longer stops ads from being
scored and written. Each graph is a straight line you can read top to bottom. And each
half lands in its own sheet tabs, so no column is blank for half the rows.

They stay 45 minutes apart because the `ci` service runs one stage at a time — a second
concurrent stage gets a `409` rather than being queued, since two runs would double-write
snapshots and corrupt the velocity history that wave detection depends on.

### The UGC flow — `workflows/n8n/ugc.json`

```
6:00 ─ collect UGC ─ radar_ugc ─ trends ─ SHEET ─ brief input ─ prompt ─ Claude ─ SHEET ─ broken? ─┬─ alert
                                                                                                   └─ done
```

### The ads flow — `workflows/n8n/ads.json`

```
6:45 ─ collect ads ─ radar_ads ─ SHEET ─ brief input ─ prompt ─ Claude ─ SHEET ─ broken? ─┬─ alert
                                                                                          └─ done
```

Collection is `continueRegularOutput` in both: a throttled actor or an unverified handle
is normal, and scoring what did come back is still worth doing. Scoring is not — everything
after it is meaningless without it, so a failed `radar_*` halts that flow.

**The sheet is the endpoint.** Slack is a notification, not a destination. If Slack is down
the day's work is still in the sheet, which is the opposite of how it read before.

## Claude in the flow

Both graphs end with a Basic LLM Chain wired to an Anthropic chat model, using the
credential already connected in n8n. Nothing about the API key lives in this repo or in
the exported JSON.

Three nodes make it work:

1. `brief_input_<kind>` — the day's top rows, trimmed to the fields a written read
   actually turns on, plus yesterday's for comparison. Sending the raw radar feed would
   be tens of thousands of tokens of numbers Claude does not need, and pays for.
2. `GET /prompt/daily_brief_<kind>` — **the prompt is fetched from `prompts/*.md` at run
   time, not pasted into the workflow JSON.** Edit the markdown file and the next run uses
   it; nobody re-imports a workflow to change a sentence.
3. `save_brief` — writes what Claude wrote into the `DAILY_BRIEF` tab, keyed on date *and*
   source, so the 6:45 ads brief cannot overwrite the 6:00 UGC one.

The Claude node is `continueRegularOutput`. A missing credential or a rate limit costs you
the written summary, not the data — which is already in the sheet by then.

The two prompts are deliberately different. The ads one is told, in as many words, that
there are no impressions or spend for US commercial ads, because without that it will
confidently invent reach numbers.

## Where it runs

n8n Cloud cannot reach a service on a laptop, and it blocks `$env`. Both flows are
built for that: the host lives in one **Config** node per workflow, and the token
comes from a credential. See `DEPLOY.md` — it is the file that decides whether any
of this runs at all.

## Importing the workflows

```
n8n → Workflows → Import from File → workflows/n8n/ugc.json   (then ads.json, watch.json)
```

On first import, open the `Claude writes the read model` node and pick your Anthropic
credential. Then activate both.

Do **not** also import `workflows/n8n/_superseded/daily.json`. It ran both halves in one
graph; running it alongside these would double-write snapshots for the same videos.

## The watch workflow

Fires 48 times a day, and is deliberately silent unless at least 3 watchlist videos moved
or the run genuinely failed. A job that notifies every 30 minutes is a job nobody reads.

30 minutes is what wave detection wants. This is also why it is an n8n schedule and not a
Claude scheduled task: those have an hourly minimum.

## Without Docker

```bash
uv venv && uv pip install -e ".[dev]"
python -m ci serve --port 8000        # then point n8n at http://localhost:8000
```

Or skip n8n entirely and use cron. Keep the two flows 30 minutes apart for the same
reason n8n does:

```
0  6  * * *   cd /path/to/repo && ./run_ugc.sh   >> data/ugc.log 2>&1
45 6  * * *   cd /path/to/repo && ./run_ads.sh   >> data/ads.log 2>&1
*/30 * * * *  cd /path/to/repo && ./run_watch.sh >> data/watch.log 2>&1
```

Without n8n there is no Claude node, so `run_*.sh` stops at the sheet. That is the point of
the sheet being the endpoint: everything essential has already landed.

## Before the first real run

1. `APIFY_TOKEN` in `.env`, on a **paid plan**. The free tier throttles after about five
   search calls and reports it as an empty result, not an error.
2. `GOOGLE_SERVICE_ACCOUNT_JSON` and the sheet shared with that service account as
   **Editor**, or every write returns 403.
3. `SLACK_BOT_TOKEN` and `SLACK_CHANNEL`.
4. `docker compose exec ci python -m ci healthcheck` and read `missing_env`.

`OPENAI_API_KEY` is only needed for the hook analysis and generation stages. The radar,
trends and sheet all run without it.

## Getting the competitor's actual script

The radar stores numbers and captions. It has never stored what happens inside a
video, so anything the dashboard shows under "Our idea" is written by us, not
lifted from them. Two ways to get the real thing.

**Free, on this machine.**

```bash
./tools/setup_transcribe.sh            # once: ffmpeg, tesseract, yt-dlp, whisper
python tools/transcribe.py --top 3     # the three best scoring videos
python tools/transcribe.py --tier "BREAKING OUT" "DAY TWO"
python tools/transcribe.py --url https://www.tiktok.com/@someone/video/123
```

It downloads the video, uses TikTok's own captions when they exist and Whisper
when they do not, finds the cuts with ffmpeg, and reads the text burned into a
frame from each one. Output lands in `data/transcripts/` as JSON and markdown,
and the dashboard picks it up automatically: open a row's script and the real
one appears above ours, tagged "From the video".

TikTok is blocked by most Indian ISPs and this downloads straight from TikTok,
so it needs a VPN or a machine outside India.

**Paid, through Apify.** The same scraper we already use has two switches:
`downloadSubtitlesOptions: TRANSCRIBE_ALL_VIDEOS` and `aiVideoDescription`, which
gives a scene by scene account of what is seen and heard. About 9 cents a video,
so $1.11 for the twelve that crossed BREAKING OUT or DAY TWO, $5.70 for all 52.
No VPN needed. It needs credit on the Apify account.

## The local dashboard

```bash
./dashboard.sh                  # http://127.0.0.1:8787, opens the browser too
./dashboard.sh 9001             # a different port
```

Use the script rather than calling python directly. `python -m ci dashboard`
needs `PYTHONPATH=src` and the right interpreter; get either wrong and you get
"No module named ci", or a dashboard running against a different data folder,
which looks exactly like a dashboard with no data in it.

Localhost only by default, deliberately: this server can rewrite config files,
so it must never be the thing left listening on `0.0.0.0`.

**The Run menu.** Five jobs can be started from the top bar, one at a time:

| Job | What it does | Cost |
| --- | --- | --- |
| Re-score what is stored | Applies the current settings to videos already collected | free |
| Re-check the watchlist | Re-measures the ones taking off, which is the only way the waves signal ever becomes measurable | ~$0.18 |
| Collect creator videos | Full keyword sweep, then scores what comes back | ~$0.34 |
| Collect competitor ads | Meta ad library for the competitor pages, then scores | ~$0.05 |
| Push to Google Sheet | Writes the current radar to the shared sheet | free |

Collection is always followed by scoring in the same job. Collecting without
scoring leaves the screen exactly as empty as it was, which reads as a failure
even when the sweep worked.

Jobs run on a background thread and the page polls for progress, so closing the
menu does not stop them. Only one runs at a time: two collectors writing
snapshots at once corrupts the velocity history, and that is the one thing here
that cannot be recomputed afterwards.

A job that needs a credential you do not have is disabled and says which one.

**When the screen is empty it tells you why.** There are several different
reasons and they need different answers, so the page asks `/api/health` and
says which one it is: nothing collected yet, collected but never scored, scores
with no raw collection behind them, or filters on screen excluding everything.
A sweep that returns nothing is called out separately, because out of credit
Apify reports SUCCEEDED and returns an empty dataset, and that failure otherwise
looks like a quiet week for the competitors.

### A copy that opens with a double click

```bash
PYTHONPATH=src python tools/bake_dashboard.py   # writes radar-dashboard.html
```

Freezes every API answer into one HTML file and points fetch at them instead of
at a server. Filters, search, sorting, the plot, the score breakdowns, CSV
export and the live re-tiering when you move a threshold all still work. Running
jobs and saving settings do not, and say so rather than failing quietly. A
yellow bar across the top carries the date it was frozen, because a stale
dashboard that looks live is worse than no dashboard.

Use it to send someone the morning list without asking them to install python.
Re-run the command to refresh it.

**The videos.** Everything scored, filterable by tier, competitor, status, date,
score, views, age, share rate, follower count and free text, plus a jackpot
toggle. Sort by any column. Export what you are looking at as CSV.

It reads storage, not the morning list, on purpose. The list is capped at 25 with
per-creator and per-competitor limits and a tier filter, so the dashboard is
where you go to see what those caps hid.

**Settings.** Every threshold worth tuning: tier bars, the seven score
weights, the reaction bands, the feed caps, and the volume dials. Cost per day
for each Apify actor updates as you move them.

**Preview before saving.** Pending changes are replayed against the stored
videos and it tells you exactly how many move tier and which. Tier is only ever
views and age, so that replay is exact rather than an estimate. Nothing touches
disk until you press save.

### Why the config editor is written the way it is

These YAML files carry the reasoning behind every threshold, and that reasoning
is worth more than the numbers. `yaml.safe_load` then `yaml.dump` would delete
every comment, reorder keys and reformat the tier table in one round trip.

So edits are surgical text replacements on the one line holding the value. The
tier table keeps its column alignment. A round trip, change it and change it
back, produces a byte-identical file, and there is a test that asserts exactly
that.

Three rules the editor enforces:

* **Allowlisted fields only.** An arbitrary dotted path from a request can never
  reach the file.
* **Bounds checked.** Out of range is refused with a reason, not silently clamped.
* **All or nothing.** Edits are staged in memory across every affected file and
  written only once all of them validate. A rejected change cannot leave half a
  config for the 6am run to choke on.
