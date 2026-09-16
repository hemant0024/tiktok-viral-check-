# Viral radar

`python -m ci radar`

## The question

Not "which competitor video has the most views". That is history.

**"Which competitor video is taking off right now, while I can still study it before
everyone else copies it."**

## Views relative to age, never views

| Example | Verdict |
|---|---|
| 2M views, 3 weeks old | ALREADY VIRAL. Downranked hard. The copies have started. |
| 800K views, 2 days old | ALREADY VIRAL. We are late. |
| 18K views, 4 hours old, climbing | Live candidate |
| 7K views, 1 hour old, big engagement | Live candidate |

Already-viral videos are **penalised to a quarter of their score**, not promoted. They
still appear, as context, at the bottom.

The expected-views curve is what "normal" looks like at each age:

```
1h -> 5K    3h -> 20K    6h -> 60K    12h -> 150K    24h -> 300K    48h -> 500K
```

`vs_expected` is how far above that curve a video is sitting.

## Tiers, from views AND age together

```
EXPLODING     200K+ views,  under 24h
BREAKING OUT   50K+ views,  under 24h
INTERESTING    10K+ views,  under 24h
WATCH         under 10K,    under 24h
DAY TWO                     under 48h
ALREADY VIRAL 500K+ and older than 48h   -> penalised
TOO OLD       older than 72h
```

## The biggest tell: distribution waves

```
1,000 -> 2,500 -> 7,000 -> 22,000 -> 70,000 per hour     4 waves, VIRAL
20,000 -> 22,000 -> 24,000 -> 25,000 per hour            0 waves, FLAT
```

The second has more views for the first three hours and is going nowhere. TikTok is
finding progressively larger audiences for the first one and they keep responding.

A wave is an hour where the view rate is at least **1.5x** the hour before.
Phases: PRE-VIRAL (1 wave), BREAKING OUT (2), VIRAL (3+), PEAKED (ratio fell below 1).

**Waves need hourly readings, which is why `ci watch` exists.** It re-polls anything
scoring above 35 and under 72 hours old every 30 minutes. A once-a-day snapshot cannot
see an hourly wave.

## Engagement bands

| Metric | Normal | Viral | Weight |
|---|---|---|---|
| **shares / views** | <0.5% | 3%+ | **0.35** |
| saves / views | <0.3% | 1%+ | 0.25 |
| comments / views | <0.2% | 1%+ | 0.20 |
| likes / views | <6% | 15%+ | 0.20 |

**Shares carry the most weight on purpose.** A like says "I enjoyed this". A share says
"someone else needs to see this". For finding an ad concept worth rebuilding, that
difference is the whole game.

There is a gate on it: a video with a normal-band share rate **and** no waves gets a 0.7x
penalty, however fast its views are climbing. Getting watched is not the same as spreading.
In testing, a 91K-view video with a 0.22% share rate correctly ranked below an 18K-view
video with 1.78%.

## The jackpot

A small account suddenly doing huge numbers. Under 50K followers, 5x+ its own normal,
**and at least 5,000 views**, gets a 1.25x bonus. A big creator getting big numbers is
just Tuesday.

The view floor was added on 15 Sep. Without it the lift test alone flagged 24 of the 52
videos collected on 11 Sep, including 348 views from a 24-follower account. With no
creator history, lift falls back to views over followers, so any tiny account clears 5x
on an ordinary day and the badge stopped carrying information. 5,000 is half the
INTERESTING bar; it keeps 4 of those 24. The floor is tunable in the dashboard.

## What we cannot see, and will not fake

**Watch time, completion rate and rewatch rate are creator-side analytics.** No public
API or scraper returns them for a video you do not own. They are excellent signals and
they are simply not available, so they are absent rather than estimated.

The one exception: TikTok **ads** via Creative Center enrichment do expose a per-second
retention curve. That is on the roadmap for the ads side.

## Ads are scored completely differently

The Meta Ad Library publishes no views, likes or spend for US commercial ads. So ads get
`winner_signal` instead: days running, variation count, relaunch, platforms, hook reuse.

Scoring ads on views put a Linguza ad running 99 days with 5 variations at the bottom of
the feed. Money spent over time is the signal for ads.

## Collection is recency-first

Sorting by most-viewed only ever finds what already happened. The passes run
`DATE_POSTED` over YESTERDAY and THIS_WEEK first, with a small most-liked pass kept only
as context for what good looks like in the niche.

## Commands

```bash
python -m ci collect competitor_ugc   # UGC mentioning any of the 18 competitors
python -m ci collect meta_ads         # their US ads
python -m ci radar                    # the feed
python -m ci watch                    # re-poll candidates, run every 30 min
python -m ci notify-radar slack
python -m ci sheets-push              # into "Competitor Viral Radar" in Drive
```

## Tuning

`config/scoring.yaml`, sections `radar`, `viral_signals`, `takeoff`, `winner_signal`.
Floors are set LOW deliberately. Raising them makes the feed quieter and later, which is
the opposite of the point.
