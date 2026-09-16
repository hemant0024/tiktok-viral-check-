# Why this video and not that one

The criteria the radar applies, in order.

Plain English versions for the team:
* Page: "Radar Selection Criteria" (Claude artifact)
* Sheet: "Radar Rules — plain English" (Google Drive), one row per rule

## How much it looks at

| | |
|---|---|
| Searches per run | 57, one per competitor name and nickname |
| Videos per search | 15 newest from the past week |
| **Per morning** | **855 max** |
| Re-check job | every 30 min, up to 60 videos |
| **Re-checks per day** | **2,880** |

Re-checking costs more than the morning sweep. Cost depends almost entirely on
which Apify actor runs:

| Actor | Per month, full volume | Works on a free Apify plan |
|---|---|---|
| `apidojo/tiktok-scraper` | **$34** | no, returns the no-results sentinel for everything |
| `clockworks/free-tiktok-scraper` | **$436** | yes |

apidojo is flat priced at $0.0003 per video with no add-on charges. clockworks
charges $0.003 plus $0.0013 each for the sorting, date and country filters a
keyword search needs, so $0.0069 a search and $0.003 a direct-URL poll.

The collector tries apidojo first and falls back to clockworks when it throttles,
recording which one ran. **Upgrading the Apify plan is worth roughly $400 a
month** and is the single biggest lever on the bill.

**Every number below lives in `config/scoring.yaml`, not in code.** If this file
and the config ever disagree, the config is right and this file is stale.

## The one idea

Not "which video has the most views" but "which video is getting far more
attention than it should for how old it is", early enough to act on.

A 2M-view video from three weeks ago is not a finding. The copies have already
shipped. An 18K-view video from four hours ago that is still climbing is the point.

## Four gates before anything is scored

Counts from the run on 2026-09-11.

| # | Gate | Rule | Result |
|---|---|---|---|
| 1 | Pulled | 57 keywords, `LATEST` sort, `PAST_WEEK`, US proxy, 15 each | 507 |
| 2 | Names the app | caption or hashtags mention a competitor, **whole word** | 52 (−455) |
| 3 | Not brand-owned | posts from a competitor's own account removed | 52 (−0) |
| 4 | Under two minutes | longer than `120s` dropped | 52 |

Sorting by newest rather than most-viewed is deliberate: sorting by views only
ever finds what has already happened.

Whole-word matching is why Malay `praktikal` no longer counts as Praktika.

A keyword that could not be checked is recorded as **not checked**, never as
zero. "We found nothing" and "we did not look" are different answers.

## The score, 0 to 100

| Component | Weight | What it is |
|---|---|---|
| Distribution waves | 22% | this hour's view rate vs last, `1.5x+` = a new audience |
| Pace for its age | 20% | views vs what a normal video does by this age |
| Acceleration | 18% | is the view rate itself speeding up (needs 3 snapshots) |
| Engagement quality | 15% | four ratios, own bands, see below |
| Creator lift | 15% | how far above this creator's own normal |
| Raw velocity | 5% | views per day, the laggiest signal on the list |
| Freshness | 5% | halves every `36h` |

**Unmeasurable components are removed, not scored as zero.** Acceleration needs
three snapshots, so on day one it is unknown. Treating unknown as zero meant 40%
of the score was dead weight and nothing could reach the top status until day
three. Weights are redistributed across whatever is measurable now.

## Engagement, four ratios

A like says "I enjoyed this". A share says "someone else needs to see this".

| Ratio | Weight | Normal | Elevated | Viral |
|---|---|---|---|---|
| shares / views | 35% | 0.5% | 1.0% | 3.0% |
| saves / views | 25% | 0.3% | 0.5% | 1.0% |
| comments / views | 20% | 0.2% | 0.5% | 1.0% |
| likes / views | 20% | 6% | 8% | 15% |

## Tier: views AND age

First condition satisfied, read top down.

- `EXPLODING` 200,000+ within 24h
- `BREAKING OUT` 50,000+ within 24h
- `INTERESTING` 10,000+ within 24h
- `WATCH` anything else within 24h
- `DAY TWO` anything else within 48h
- `TOO OLD` past 72h, not a takeoff candidate

`ALREADY VIRAL`: past 500,000 views and 48h old, score is multiplied by `0.25`.
Still shown as context, never leads the feed.

`JACKPOT`: under 50,000 followers, doing 5x their own normal, on at least 5,000
views, gets `1.25x`. A small account suddenly getting huge numbers is the
cleanest evidence the content did the work rather than the distribution. The
view floor matters: without it, a 24-follower account with 348 views counts as a
jackpot, because a tiny account beats its own tiny normal every day of the week.

## Status: direction, not size

| Status | Score | Also requires |
|---|---|---|
| EXPLODING | 70+ | still accelerating, under 96h |
| CLIMBING | 50+ | still accelerating |
| EARLY SIGNAL | 35+ | under 48h |
| COOLING | any | view rate falling |
| STEADY | any | everything else |

## What reaches the feed

Score 30+, at most 25 rows, at most 3 per creator and 6 per competitor, ad
variations collapsed to their strongest member. Everything scored goes to the
sheet regardless; the feed is the shortlist, the sheet is the record.

Score above 35 and younger than 72h joins the watchlist, re-polled every 30
minutes. Daily snapshots cannot see hourly waves, and waves are 22% of the score.

## What we cannot see, on purpose

**Watch time, completion rate, rewatch rate.** Creator-side analytics. No public
API or scraper returns them for a video you do not own. They appear nowhere in
the score. Any tool claiming to report a competitor's completion rate is guessing.

**Ad impressions and spend.** The Meta Ad Library publishes none for US
commercial ads. Ads are scored on days running and variation count instead, on a
separate scale that is never mixed with this one.

## When the feed looks wrong

- **A video you expected is missing** — usually gate 2, the caption never named
  the app. Check the keyword list before blaming the scoring.
- **Nothing from a competitor** — check whether their keywords were *not checked*
  rather than checked and empty. A throttled pull looks exactly like a quiet day.
