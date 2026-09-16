# Competitor Hook Radar — Implementation Plan

Status: **Phase 0 complete. Awaiting approval.** No code written.
Spec: `docs/SPEC.md`
Last updated: 2026-09-10

The question this answers every morning:
**"Which competitor hooks are working right now, and what 5 ads should we make today because of them?"**

---

## 1. CURRENT STATE

Empty folder. No code, no git, no `.env`, no config, no n8n, no credentials.

```
competitor-hook-radar/
└── docs/
    ├── SPEC.md     (yours)
    └── PLAN.md     (this file)
```

**One note on location.** This session can only write inside the connected folder, so the
repo sits at `/Users/hemant/tiktok hook finder/competitor-hook-radar/`. Move it wherever
you want, nothing depends on the path. Your original `SPEC (1).md` is still in the parent
folder because this mount does not allow deletes.

**Python 3.10.12, uv 0.12.3, git 2.34.1 and ffmpeg/ffprobe are all present** on the
machine. ffmpeg matters: it is how we trim the first 3 seconds locally instead of paying
to transcribe whole videos twice.

---

## 2. ARCHITECTURE

```
   SOURCES (one adapter each, identical output)
   ┌──────────────────────────────────────────────────────────────────┐
   │ meta_ads.py      TikTok CC.py    tiktok_organic.py   youtube.py  │
   │ manual_drop.py   csv_import.py                                    │
   │        every one: fetch() -> list[NormalizedVideo]                │
   └──────────────────────────────┬───────────────────────────────────┘
                                  │  ci collect <source>
                                  ▼
                   dedup -> snapshot -> cheap filter
              (UGC style AND (7+ days running OR strong views))
                                  │
   ┌──────────────────────────────┴───────────────────────────────────┐
   │              Repository interface (storage/base.py)               │
   │   SheetsRepo (first)  |  LocalJsonRepo (day one)  |  Supabase     │
   └──────────────────────────────┬───────────────────────────────────┘
                                  │
     ┌───────────────┬────────────┴──────────┬──────────────────┐
     ▼               ▼                       ▼                  ▼
  download +      analysis               scoring            generation
  transcribe      ┌──────────┐        ┌─────────────┐    ┌────────────┐
  ┌──────────┐    │ LLM cheap│        │ PURE PYTHON │    │ LLM strong │
  │ ffmpeg   │    │ extract  │        │ Winner Sig. │    │ 5 hooks    │
  │ trim 0-3s│    │ ugc fmt  │        │ Viral Score │    │ UGC + cat  │
  │ whisper  │    │ why works│        │ saturation  │    │ gate       │
  └──────────┘    └──────────┘        └─────────────┘    └────────────┘
                                  │
                                  ▼
                          report -> Slack
   n8n schedules the CLI commands. It holds zero logic.
```

### Repo layout (spec section "Project structure", with a src layout so `python -m chr` works)

```
src/chr/
  sources/     meta_ads.py tiktok_cc.py tiktok_organic.py youtube.py
               manual_drop.py csv_import.py base.py apify.py
  processing/  dedup.py snapshots.py cheap_filter.py download.py transcribe.py
  analysis/    hooks.py ugc_format.py why_it_works.py winners.py
  scoring/     winner_signal.py viral.py saturation.py hook_score.py
  patterns/    embed.py match.py
  generation/  hooks.py cat_ugc.py quality_gate.py originality.py
  storage/     base.py sheets.py localjson.py memory.py
  notify/      slack.py telegram.py
  llm/         client.py cache.py prompts.py providers/
config/   product.yaml competitors.yaml scoring.yaml llm.yaml sources.yaml
prompts/  11 files, versioned, JSON schema each
```

### Tables (spec section "Database", plus two for ops)

`COMPETITORS`, `VIDEOS`, `VIDEO_SNAPSHOTS`, `HOOKS`, `PATTERNS`, `GENERATED_HOOKS`,
`OUR_ADS`, `WINNERS`, `DAILY_REPORTS`, `RUN_LOG`, plus **`LLM_CALLS`** and
**`PATTERN_MATCHES`** so cost and merge decisions are auditable rather than invisible.

`video_id` = platform ad ID or post ID, else `sha256(canonical_url)[:16]`.

---

## 3. DATA SOURCE COMPARISON

I tested the two that decide the project rather than trusting product pages.

### What I verified live on 2026-09-10

I ran `apify/facebook-ads-scraper` against the real US Meta Ad Library. Results below are
observed field values, not documentation claims.

**It found two of your 18 competitors immediately.** Linguza had five active video ads,
the oldest running since 3 June, which is **99 days**. Loora had an active ad from 13
June. It also surfaced Jumpspeak running a direct attack ad on Duolingo, which is exactly
the kind of thing this system should catch.

| Field we need | Comes back? | Detail |
|---|---|---|
| Ad start date | **Yes** | `startDate` unix + `startDateFormatted` |
| Days running | **Yes, derived** | `endDate - startDate`. See the gotcha below. |
| Still active | **Yes** | `isActive` |
| **Video file** | **Yes** | `snapshot.videos[].videoHdUrl` and `videoSdUrl`, real MP4s |
| Thumbnail | Yes | `videoPreviewImageUrl` |
| Ad copy | Yes | `snapshot.body.text`, full text |
| Headline / CTA | Yes | `snapshot.title`, `ctaText`, `ctaType` |
| Landing page | Yes | `snapshot.linkUrl` |
| Platforms | Yes | `publisherPlatform` array |
| Variation count | **Unreliable** | `collationCount` was null on half the ads, and 1 on the rest |
| Spend / reach / impressions | **No** | all null for US commercial, as expected |

**Three gotchas found by testing, not reading:**

1. **`totalActiveTime` is null on every US ad.** The field exists and the actor's
   description implies it works. It does not. Days running must be computed as
   `endDate - startDate`. That is reliable, and it leads to a useful insight in section 5.
2. **`collationCount` cannot be trusted as the variation count.** We derive it ourselves.
   The evidence is right there in the test: Linguza had five separate ad IDs, all titled
   "Try free now!", all with different start dates, and `collationCount` said 1 for each.
   Five ads, one concept. That is the variation signal, and grouping is how we get it.
3. **Dynamic creative ads return template placeholders.** A Duolingo ad came back with
   `snapshot.title` = `{{product.name}}` and `displayFormat` = `DCO`. Those must be
   filtered out or they will pollute the hook corpus with literal template syntax.

### The comparison

| Source | US Meta | US TikTok | Video file | Days running | Variations | API | Price/mo | ToS risk |
|---|---|---|---|---|---|---|---|---|
| **Meta Ad Library official API** | **No** | no | no | political only | no | yes | free | none |
| **Apify Meta Ad Library scraper** | **Yes, verified** | no | **yes, verified** | **yes, derived** | derive ourselves | yes | ~$22 | medium |
| **Apify TikTok Creative Center** | no | **yes** | **yes, 720p** | period filter only | no | yes | ~$6 | medium |
| **Apify TikTok organic** | no | **yes** | yes | n/a | n/a | yes | ~$5 | medium |
| **Foreplay** | yes | yes | yes | "creative-test timelines" | "creative velocity" | **yes, real** | $99 API + $59-459 seat | low |
| **Atria** | yes | yes | **yes, auto-stored** | not documented | not documented | Pro/Team only, custom price | $159 Basic | low |
| PiPiAds | partial | yes | yes | yes | no | **no** | ~$77 | medium |
| BigSpy | yes | yes | yes | yes | no | **no** | ~$9 | medium |
| Minea | yes | yes | yes | yes | no | **no** | ~$49 | medium |
| AdSpy | yes | no | yes | yes | no | **no** | $149 | medium |
| adlibrary.com | yes | yes | yes | yes | unclear | yes | €329 | medium |
| YouTube Data API | no | no | no | n/a | n/a | yes | free | none |

**The single most important line in that table: almost every ad spy tool is UI only.**
PiPiAds, BigSpy, Minea, AdSpy and Dropispy have no public API at all. For a pipeline that
runs itself every morning, that rules them out no matter how good their data is. It comes
down to Apify, Foreplay, Atria and adlibrary.com.

**On Atria specifically**, since you named it. It is the closest thing on the list to what
we are building: $159/month, Meta and TikTok, and it **already downloads the video and
extracts the spoken script and on-screen text automatically**, which is our entire Phase 3.
Two things keep it out of the primary slot. Its API is gated behind Pro/Team at custom
pricing, so the one feature that decides whether it can drive a pipeline has no published
price. And nothing in its public material commits to ad start dates, days running or
variation counts, which are the three fields the Winner Signal Score is built on. It is
worth a demo call. If their API returns days running and their transcripts are good, Atria
could collapse Phases 2 and 3 into one integration. I would not architect around it before
seeing that in writing.

### Recommendation

**Primary: Apify.** Three actors behind three adapters.

| Job | Actor | Price | Why |
|---|---|---|---|
| US competitor Meta ads | `apify/facebook-ads-scraper` | $0.0058/ad | Official Apify actor, 35k users. **Verified live today**: video URLs, start dates, full copy. |
| US TikTok Top Ads | `dltik/tiktok-creative-center` | $0.0035/ad | CTR, likes, 720p MP4, duration, and **per-second retention on enrich**, which is literally hook performance data |
| Organic UGC | `apidojo/tiktok-scraper` | $0.0003/post | $0.30 per 1,000, US location filter, and auto-captions ship free inside the result |

**Backup: Foreplay API.** $99/month for 100,000 credits, one ad = one credit including
transcript, video and copy. It is purpose-built for exactly this, its Spyder product does
creative-test timelines and auto-transcribed hooks, and the ToS position is cleaner
because they are a licensed vendor rather than us scraping. Two reasons it is the backup
and not the primary: tracking 18 brands needs the $459/month Agency seat on monthly
billing (Workflow covers 15), and **I could not verify any of it without an account**, so
every claim in that row is theirs, not mine.

**Worth a call, not a commitment: Atria.** See above. If you are already inclined to buy
rather than build, ask them two questions: does the API return ad start date and days
running, and is the API included below custom Pro/Team pricing. Yes to both changes my
recommendation.

**Third path, always available: manual link drop.** A CSV or Slack command where the team
pastes a competitor ad URL. It goes through the identical pipeline. This is not a
consolation prize. It is what keeps the system alive the week an actor breaks, and it is
how the team's own eyes get into the loop.

**Recommended switch trigger:** if the Apify Meta actor's success rate drops below 80% for
two consecutive weeks, or Meta ships a change that breaks it, move to Foreplay. Because
everything sits behind one adapter interface, that is a new file, not a rewrite.

---

## 4. WHAT WE CAN AND CAN'T GET

### Confirmed available

* Every active US competitor Meta ad, with **start date, full copy, CTA, landing page and a downloadable MP4**.
* Days running, exactly, for every ad.
* US TikTok Top Ads with CTR and likes, plus per-second retention curves on the detail fetch.
* Organic UGC across TikTok, with free auto-captions, and YouTube Shorts via the free API.
* Which platforms an ad runs on (`publisherPlatform`), which is the spec's "survived two auctions" signal.

### Confirmed NOT available

* **Any competitor conversion data.** Nobody has this. Proxies only, as the spec says.
* **Spend, reach and impressions for US commercial ads.** All null. These populate only for political ads and EU/UK delivery. Confirmed both in Meta's own docs and in my live test.
* **Commercial US ads from the official Meta API.** Coverage is political ads worldwide, plus any ad type delivered to the UK or EU. Your spec's suspicion was right.
* **A TikTok Creative Center public API.** Web UI only. Scrapers exist.
* **Instagram organic discovery.** No API for content we do not own. Hashtag Search caps at 30 hashtags per rolling 7 days and cannot even return usernames.
* **A trustworthy variation count from any single field.** We derive it.

### Available but needs a decision

* **Video download was blocked in both my sandboxes.** The MP4 URLs are real and their
  own query strings even encode `duration_s: 63` and `asset_age_days: 64`. But
  `fbcdn.net` returned a proxy 403 from both the cloud container and your local VM, so I
  could not fetch a byte. This is almost certainly an egress allowlist in the sandboxes
  rather than anything Meta is doing. **Before Phase 3 we need one confirmed download on
  the machine that will actually run this.** If fbcdn stays blocked, the fallback is
  transcribing from the thumbnail plus ad copy, which is significantly worse, or routing
  downloads through the box that runs n8n.

---

## 5. THE TWO SIGNALS THE SPEC LEANS ON

Since we cannot see conversions, days running and variation count carry the whole Winner
Signal Score. Both need care.

### Days running: cheaper than it looks

`startDate` never changes once an ad exists. What changes is whether it is still active.
So we do **not** need to re-scrape every ad every day to keep days running accurate. We
need to re-scrape to learn that an ad **stopped**.

That splits the job in two and cuts the bill by about 80%:

* **Daily:** discover new ads only, using `onlyAdsNewerThan`. Cheap.
* **Weekly:** full sweep of all 18 competitors to catch ads that died and refresh active status.

Worst case an ad is marked active for six days after it stopped. For a signal whose
thresholds are "30+ days" and "60+ days", that is noise, not error. `VIDEO_SNAPSHOTS`
still gets a row every run so the history is unbroken.

### Variation count: derived, with a stated definition

`collationCount` is unusable, so we define it ourselves and write it down:

> A **variation group** is a set of ads from the same page whose normalized ad copy has a
> trigram Jaccard similarity above 0.75, or which share a non-null `collationId`.
> **Variation count** is the size of that group among currently active ads.

The Linguza case is the test fixture: five ad IDs, one title, five start dates, must
collapse to one group of five. That goes straight into the Phase 4 unit tests.

Second signal we get free from the same grouping: **relaunch detection**. A group that had
no active ads for a stretch and then has one again is the spec's "recently relaunched or
scaled" signal, worth 15%.

---

## 6. IMPLEMENTATION PLAN

### Phase 0: Plan
- [x] Inspect folder, read spec
- [x] Test the Meta path live against real US competitor ads
- [x] Test the TikTok path, compare actors and pricing
- [x] Confirm what the official Meta API does and does not return
- [x] Write `docs/PLAN.md` and `CLAUDE.md`
- [ ] **Your approval**

### Phase 1: Foundation
- [ ] Repo structure, `.env.example`, `.gitignore`, git init
- [ ] `config/product.yaml`, `competitors.yaml` with all 18 researched and filled, `scoring.yaml`, `llm.yaml`
- [ ] Pydantic model per table
- [ ] Repository interface, Sheets adapter, local JSONL adapter, in-memory adapter
- [ ] LLM wrapper: cheap and strong tiers, retries, timeouts, JSON schema validation, cache, cost log
- [ ] CLI skeleton, structured logging, pytest

**Done when:** tests pass and `python -m chr healthcheck` reaches Sheets.
**I will flag** any competitor whose handles I cannot verify with confidence rather than guessing. Parrot, Learna, Fluzy and Lingopanda are generic enough names that I expect at least one to need your eyes.

### Phase 2: Competitor ads, one source end to end
- [ ] `sources/meta_ads.py` via Apify, scoped to Praktika, Speak, Duolingo
- [ ] Normalize, dedup on `video_id`, snapshot every run
- [ ] Days running from `startDate`, variation grouping per section 5
- [ ] DCO template ads filtered out
- [ ] Daily-new plus weekly-full cadence

**Done when:** running twice creates no duplicates, days running updates, and I show you 10 rows.

### Phase 3: Hook extraction
- [ ] **First: confirm one real video download on the target machine**
- [ ] ffmpeg trim to first 3 seconds, transcribe both the clip and the full video
- [ ] `prompts/01_extract_hook.md`, `02_classify_ugc_format.md`, `03_analyze_why_it_works.md`
- [ ] Cheap filter before any spend: UGC style, and 7+ days running or strong views

**Done when:** 15 real ads analyzed, and **I show you 5 so you can judge quality before we build on it.** This is the real gate in the project.

### Phase 4: Winner scoring and patterns
- [ ] Winner Signal Score with the spec's six weights, pure Python
- [ ] Viral Score for organic: views per day, engagement rate, lift over that creator's normal
- [ ] Pattern grouping across competitors, matched across days not recreated
- [ ] Saturation

**Done when:** unit tests cover a 90 day ad with 8 variations against a 3 day ad with 1, and a hook used by 4 brands against 1. Plus the Linguza five-ads-one-concept fixture.

### Phase 5: Generate our hooks
- [ ] `06_generate_hooks`, `07_cat_and_ugc_versions`, `08_score_hooks`, `09_quality_gate`
- [ ] 5 hooks per strong pattern, UGC version and cat version
- [ ] Hook Score with the spec's six weights
- [ ] Quality gate: copied wording via real similarity checks, generic, no visual, false claims, unproducible, ignores product

**Done when:** one run gives scored hooks, rejections carry reasons, and I show you the top 5.

### Phase 6: Slack report
- [ ] Renderer in the spec's format, with links back to the original competitor videos
- [ ] Full report stored in `DAILY_REPORTS`, short version sent

**Done when:** it lands in a test Slack channel and reads well on a phone.

### Phase 7: All 18 competitors plus organic UGC
- [ ] Scale Meta to all 18
- [ ] TikTok Creative Center, TikTok organic, YouTube Shorts
- [ ] Manual link drop

**Done when:** a deliberately broken source shows in the run log and the report still sends.

### Phase 8: Our ad results loop
- [ ] `OUR_ADS` CSV import with the spec's fields
- [ ] Winner analysis storing hook type, pattern, format, pain point, emotion, cat role
- [ ] 70/30 proven versus new fed into generation

### Phase 9: Schedule and docs
- [ ] docker-compose with n8n, morning schedule on US Eastern
- [ ] Failure alerts carrying the run summary
- [ ] README, setup from zero

---

## 7. MONTHLY COST ESTIMATE

Assumptions: 18 competitors, roughly 40 active US ads each, so about **720 active ads**
tracked. About 25 genuinely new ads a day. About **40 videos a day** pass the cheap filter
into transcription and deep analysis. 5 patterns generated against per day.

### Data tools

**Meta ads**, `apify/facebook-ads-scraper` at $0.0058 an ad, using the split cadence from
section 5:

```
daily new ads:     25/day x 30            =    750 ads  x $0.0058 = $ 4.35
weekly full sweep: 720 x 4.3 weeks        =  3,096 ads  x $0.0058 = $17.96
                                                                    -------
                                                                    $22.31
```

For contrast, a naive daily full sweep would be 720 x 30 = 21,600 ads = **$125 a month**.
The split cadence is worth about $103 a month and costs us nothing in accuracy on a signal
measured in 30 and 60 day thresholds.

If that is still too much, `azzouzana/meta-facebook-instagram-ads-library` runs $0.0005 a
result, which would take the same volume to **$1.86**. It has 417 users against 35,000,
so I would rather start on the official actor and drop to the cheap one once we trust the
shape of the data.

**TikTok Creative Center**, `dltik/tiktok-creative-center` at $0.0035, weekly:

```
200 top ads/week x 4.3 = 860 ads x $0.0035           = $3.01
enrich the 50/week that pass the filter: 215 x $0.0035 = $0.75
                                                         -----
                                                         $3.76
```

**Organic UGC**, `apidojo/tiktok-scraper` at $0.0003 a post:

```
18 brand keywords x 30 posts/day x 30 days = 16,200 x $0.0003 = $4.86
```

**YouTube Shorts:** free, 10,000 quota units a day. `search.list` costs 100 of them, so 100
searches a day is the hard ceiling. Fine for 18 brand keywords.

### Transcription

Only videos past the cheap filter. ffmpeg trims the first 3 seconds locally, so we pay
once for the full audio and slice the hook out of the result for free.

```
40 videos/day x 30 = 1,200 videos, average 40 seconds = 800 minutes
gpt-4o-mini-transcribe at $0.003/min = $2.40
```

Whisper and gpt-4o-transcribe are both $0.006 a minute, so $4.80 if we want the better
model. Either is rounding error, so **use the accurate one**.

### LLM

Cheap tier at $0.20 in / $1.20 out per million. Strong tier at $4 / $20.

```
extract_hook + ugc_format + why_it_works   3 calls x 1,200 videos = 3,600 calls
  in 1,500 / out 500  ->  5.40M in, 1.80M out  ->  1.08 + 2.16   = $ 3.24
cluster_patterns (ambiguous only)          10/day = 300 calls, strong
  in 2,500 / out 150  ->  0.75M in, 0.05M out  ->  3.00 + 0.90   = $ 3.90
score_saturation                           20/day = 600 calls, cheap
  in 1,200 / out 300  ->  0.72M in, 0.18M out  ->  0.14 + 0.22   = $ 0.36
generate_hooks + cat_and_ugc_versions      5 patterns/day = 150, strong
  in 6,000 / out 3,300 -> 0.90M in, 0.50M out  ->  3.60 + 9.90   = $13.50
score_hooks + quality_gate                 25 hooks/day x2 = 1,500, cheap
  in 1,200 / out 400  ->  1.80M in, 0.60M out  ->  0.36 + 0.72   = $ 1.08
analyze_our_winners                        ~20/month, strong                = $ 0.52
daily_report                               30/month, strong
  in 6,000 / out 2,000 -> 0.18M in, 0.06M out  ->  0.72 + 1.20   = $ 1.92
                                                                    -------
                                                                    $24.52
plus 30% for retries, cache misses, prompt iteration                = $32
```

Generation is 55% of the LLM bill, because the spec asks for a full 15 to 30 second script
plus a UGC version and a cat version for every hook. That is the right call, it is just
where the money goes.

### Total

| Line | Monthly |
|---|---|
| Meta ads via Apify | $22 |
| TikTok Creative Center via Apify | $4 |
| Organic UGC via Apify | $5 |
| YouTube, Sheets, Slack | $0 |
| Transcription | $3 to $5 |
| LLM | $32 |
| **Total** | **about $66** |

**On the Foreplay path instead:** $99 API plus a $459 Agency seat to track 18 brands on
monthly billing, so roughly **$558 a month**, or nearer $250 on annual billing where brand
limits go unlimited. It buys a cleaner ToS position and someone else maintaining the
scrapers. It is 4 to 8 times the price.

Also worth saying plainly: **one shoot day costs more than a year of this.** The cost that
actually matters here is producing the wrong ad, not the API bill.

---

## 8. RISKS

**1. Video download is unproven.** I could not fetch a single MP4 from either sandbox
because both proxy-blocked `fbcdn.net`. Everything downstream of Phase 3 assumes we can.
**This is the first thing to settle**, and it is a five minute test on the real machine.

**2. Scraping Meta's Ad Library carries ToS risk.** The Ad Library is a public
transparency tool, which helps, but it is still scraping and the exposure sits with us,
not with Apify. Foreplay exists as the licensed alternative for exactly this reason. I am
not a lawyer and this is a decision to make deliberately.

**3. Days running is a proxy that can lie.** A brand with a big always-on budget can run a
mediocre ad for 90 days. A great ad can be pulled at day 20 for reasons that have nothing
to do with performance. Variation count is the check on this: 90 days **and** 8 variations
is a real signal, 90 days and 1 variation might just be a set-and-forget campaign.

**4. Actor breakage.** Meta changes its Ad Library markup regularly and scrapers break.
Mitigation is the adapter interface, the manual link drop as a live fallback, and an alert
when a source returns zero rows twice running.

**5. Hook quality is the actual product risk.** A pipeline that reliably produces five
boring hooks is a failed project. Phase 3 exists as a hard gate for this: you read five
outputs before we build scoring on top of them.

**6. The originality line is thin and it matters most here.** This system reads competitor
ads and writes our ads. That is a short distance from plagiarism if the quality gate is
weak. It needs real similarity checks against the competitor hook corpus, not a prompt
politely asking the model not to copy.

**7. Saturation cuts both ways.** Five brands running the same hook proves it works and
means we are late. The report has to say which, or the team will chase whatever is most
crowded.

**8. 18 competitors is a lot of surface.** Some are small apps whose Meta pages may be
hard to pin down, and a few of the names are generic enough to collide with unrelated
pages. I will flag every uncertain one in Phase 1 rather than quietly guessing.

**9. Google Sheets will slow down.** `VIDEO_SNAPSHOTS` grows fastest, roughly 720 rows a
day, about 21,000 a month. Sheets gets unhappy past 10,000 to 20,000 rows. The repository
interface exists so the Supabase move is one adapter, and I would plan it around Phase 7.

---

## 9. WHAT I NEED FROM YOU

1. **Approve the source recommendation:** Apify as primary, Foreplay as the documented backup, manual link drop always on. About $66 a month all in.
2. **Confirm the ~$66 monthly spend** or tell me the ceiling and I will design to it.
3. **One video download test** on whichever machine will run this, so Phase 3 is not built on an assumption.
4. Keys when we reach Phase 1: `APIFY_TOKEN`, `OPENAI_API_KEY`, `YOUTUBE_API_KEY`, Slack bot token, and a Google Sheet shared to a service account.
5. Tell me if you would rather pay for Foreplay and take the lower ToS risk. It is a reasonable call and it changes Phase 2, not the architecture.

---

## Sources

* [Meta Ad Library API access and limits](https://swipekit.app/articles/meta-ad-library-api)
* [Meta Ad Library API limitations 2026](https://adlibrary.com/posts/meta-ad-library-api-limitations)
* [Best ad intelligence tools 2026, three-tier framework](https://adlibrary.com/posts/best-ad-intelligence-tools-2026)
* [Ad spy tool pricing comparison 2026](https://adlibrary.com/guides/best-ad-spy-tools)
* [Foreplay API](https://foreplay.co/api)
* [Foreplay pricing 2026](https://superscale.ai/alternatives/foreplay/pricing)
* [OpenAI transcription pricing, September 2026](https://costgoat.com/pricing/openai-transcription)
* Live actor runs on 2026-09-10: `apify/facebook-ads-scraper`, `apidojo/tiktok-scraper`
