# Daily Creative Intelligence System: Product Spec

A consumer learning app where a cat is the main mascot. The product helps users learn and practice English through conversational experiences.

**Target market: United States.** All trend discovery, competitor research, hooks, cultural references, and ad concepts are built for US audiences first.

Build a production ready Daily Creative Intelligence System that discovers emerging social media creative trends, extracts the underlying hooks and creative mechanisms, adapts them into original ad concepts for the app, scores them, stores them, and sends a daily report.

The goal is NOT to scrape random viral videos. The goal is:

Detect emerging creative patterns → understand why they work → adapt the pattern to the product → generate original hooks → rank the best concepts → learn from our ad performance.

## 1. Core pipeline

1. Source data
2. Data normalization
3. Deduplication
4. Content / hook extraction
5. Creative DNA analysis
6. Trend detection
7. Trend velocity
8. Saturation analysis
9. Product relevance
10. Hook generation
11. Cat mascot adaptation
12. Scoring
13. Daily report
14. Ad performance
15. Winner analysis
16. Creative knowledge base
17. Feedback into future generation

## 2. Tech stack

Preferred unless there is a strong technical reason not to:

- n8n for workflow automation
- Google Sheets for the initial database
- OpenAI API for AI analysis and generation
- YouTube Data API for YouTube / Shorts data
- Official or approved TikTok data sources where available
- Meta Ad Library / approved Meta data access for competitor research
- Telegram or Slack for daily notifications
- Python only where useful for data processing
- Environment variables for all API keys and secrets

Do NOT hard code API keys. Create a `.env.example` with all required variables.

## 3. Data collection principle

Do not build the system around fragile scraping of TikTok, Instagram, or Meta consumer pages. Use official APIs, public or approved endpoints, Creative Center data, or compliant third party APIs where necessary.

A source must be replaceable without rebuilding the system. Use a modular source interface:

```
Source
├── TikTok
├── YouTube
├── Meta
├── Instagram
└── Other
```

Each source outputs the same normalized content schema.

## 4. Target categories

Monitor more than English learning content. The aim is to discover creative mechanisms, not just competitor ads.

Language learning, Education, AI apps, Consumer AI, Productivity, Self improvement, Career, Dating, Finance, Fitness, Entertainment, Mobile apps, Technology, Study, Lifestyle.

Market focus: collect US content first (country = US, US region codes on every API that supports them). Global content is allowed only as a secondary signal for spotting mechanisms before they reach the US, and must be tagged with its country.

Example: a hook trending in dating may be adaptable to language learning. A hook trending in finance may be adaptable to an AI learning app.

## 5. RAW_CONTENT table

content_id, date_found, platform, source, url, creator, title, description, views, likes, comments, shares, published_at, country, language, category, subcategory, raw_transcript, thumbnail_url

`country` defaults to US. Non US rows must have their real country set.

No duplicate records. Use a normalized content_id. If a source has no stable ID, generate a deterministic ID from the URL.

## 6. HOOKS table

hook_id, content_id, original_hook, first_3_second_description, visual_hook, spoken_hook, on_screen_text, hook_type, creative_format, emotional_trigger, curiosity_mechanism, problem, payoff, cta, target_audience, product_category

## 7. Creative DNA

For every piece of content, extract the underlying creative mechanism. Do NOT only classify by topic.

Bad:
```
Category: Productivity
```

Good:
```
Creative mechanism: Perceived insider information
Hook type: Confession
Emotion: Curiosity
Structure: Secret → reveal → demonstration
Visual: Creator whispers into camera
Transferability: High
```

Hooks, slang, humor, and cultural references must feel native to US social media. Avoid references that only land outside the US.

Hook categories (multiple allowed): Curiosity, Confession, Shock, POV, Reaction, Challenge, Transformation, Comparison, Contrarian, Problem, Demonstration, Story, Humor, Social Proof, Pattern Interrupt, Before/After, Question, Mistake, Secret, Controversy.

## 8. Trend detection

A trend is NOT simply high views. Calculate momentum per creative pattern:

```
Trend Score =
  30% Growth Velocity
  20% Cross Category Adoption
  20% Novelty
  15% Audience Relevance
  15% Product Applicability
```

Normalized 0 to 100.

Labels:
- 0 to 30 = Emerging
- 31 to 55 = Rising
- 56 to 75 = Saturating
- 76 to 100 = Exhausted

The label must be based on both momentum and saturation, not only the number. A high view trend used thousands of times should not automatically get a high opportunity score.

## 9. Growth velocity

Where data allows: views_per_day, likes_per_day, comments_per_day, shares_per_day, engagement_rate, growth_rate.

Prefer recent growth over absolute totals. Video A with 10M views over 6 months is less interesting than Video B with 500K views in 2 days. Scoring must recognize this.

## 10. Cross category detection

Group similar creative mechanisms across categories (e.g. Dating, Beauty, Finance, Productivity, Education). If the same structure appears across multiple categories in a short period, raise its cross category score. This is a stronger signal than a trend confined to one niche.

## 11. Saturation detection

Signals: number of recent occurrences, number of brands using it, number of competitors using it, age of trend, repetition of exact wording, repetition of visual execution, repetition of audio, number of categories using it.

Output `saturation_score` from 0 to 100.

## 12. Competitor analysis

Monitor learning competitors and adjacent consumer AI products that advertise in the US, e.g. Duolingo, Praktika, Loora, Speak, ELSA Speak, Airlearn, Pingo, Stimuler. The competitor list must live in config so it can be edited without code changes.

Do not copy their creative. Extract: hook, emotional trigger, visual structure, product promise, CTA, creative mechanism. Transform into original concepts.

## 13. Product profile

Configurable file, never hard coded in the codebase. Example:

```yaml
market:
  country: "US"
  language: "en-US"
  timezone: "America/New_York"
  date_format: "MMMM D, YYYY"
  currency: "USD"

product:
  category: "English learning app"
  positioning:
    - conversational English
    - practical speaking
    - confidence
    - AI-powered practice

mascot:
  type: "cat"
  role: "main character"
  personality:
    - expressive
    - funny
    - encouraging
    - curious
    - slightly chaotic but lovable

audience:
  primary:
    - young adults
    - English learners
    - people who understand English but struggle to speak
```

## 14. Trend to product adaptation

For every high opportunity pattern, generate 5 original hooks. Each contains: Hook, First frame visual, First 3 second action, Spoken dialogue, On screen text, Creative mechanism, Product reveal, Payoff, CTA, Cat execution.

Example. Trend mechanism: Confession + Secret + Whisper.

```
Hook: "I probably shouldn't tell you this..."
Visual: Cat looks around suspiciously.
Dialogue: "I probably shouldn't tell you this, but you don't need to memorize thousands of English words to start speaking."
Product: AI conversation appears.
CTA: "Try a conversation."
```

Output must be original. Never copy the source video's exact wording.

## 15. Cat mascot requirement

The cat should not be pasted into every concept. Use it as part of the creative mechanism.

Roles: cat reacts, cat teaches, cat makes a mistake, cat gets embarrassed, cat challenges the user, cat misunderstands something, cat demonstrates the product, cat breaks the fourth wall, cat acts as the learner, cat acts as the teacher, cat reacts to user pronunciation, cat celebrates progress.

Generate different visual treatments.

## 16. Hook quality score

```
Hook Score =
  25% Attention Potential
  20% Curiosity
  15% Novelty
  15% Product Relevance
  10% Audience Relevance
  10% Visual Potential
   5% Production Simplicity
```

Score 0 to 100. Also provide: strengths, weaknesses, risk, recommended_test.

## 17. Daily output

**DAILY CREATIVE RADAR** (date)

**Top 10 emerging creative patterns.** For each: Rank, Trend, Trend Score, Growth, Saturation, Categories, Creative Mechanism, Why It Matters.

**Top 20 hooks.** For each: Hook, Hook Type, Creative Mechanism, Product Adaptation, Cat Version, Hook Score, Recommended Visual.

**Top 5 ads to produce today.** For each: Concept Name, Hook, Visual, Script, Product Reveal, Cat Role, CTA, Why We Should Test It, Expected Risk, Priority.

## 18. Daily report format

Send to Telegram or Slack. Keep it concise. Example:

```
🚨 DAILY CREATIVE RADAR
September 10, 2026

🔥 #1 CONFESSION

Trend Score: 91
Saturation: Low
Cross-category: 6

Mechanism:
Insider information

Hook:
"I probably shouldn't tell you why you still can't speak English."

Cat execution:
Cat checks whether anyone is watching before revealing the app.

⭐⭐⭐⭐⭐ PRODUCE
```

Do not dump raw data. The report must answer: what should I make today?

## 19. TEST_RESULTS table (historical ad performance)

creative_id, hook_id, trend_id, date_launched, spend (USD), impressions, views, 3_sec_view_rate, 25_percent_view_rate, 50_percent_view_rate, 95_percent_view_rate, ctr, cpc, installs, install_rate, purchases, conversion_rate, cac, roas, winner

CSV import first. Later compatible with ad platform APIs.

## 20. Winner analysis

When an ad wins, analyze its creative DNA. Do NOT just store `winner = true`.

Extract: winning_hook_type, winning_emotion, winning_visual, winning_structure, winning_problem, winning_payoff, winning_cta, winning_audience.

Example: Reaction + Embarrassment + English pronunciation + Cat reaction = high performing creative. Store as a reusable creative pattern.

## 21. Creative learning loop

When generating hooks, feed the AI: current trend + historical winners + historical losers + product positioning + audience.

Avoid blindly repeating winners. Exploit what works and explore new trends: about 70% proven mechanisms, 30% experimental.

## 22. Database design

Google Sheets initially, with tabs: RAW_CONTENT, HOOKS, CREATIVE_PATTERNS, TRENDS, ADAPTATIONS, TEST_RESULTS, WINNERS, DAILY_REPORTS.

Database layer must be modular so it can move to PostgreSQL, Supabase, Airtable, or BigQuery without rewriting the intelligence layer.

## 23. n8n workflow

Schedule Trigger (morning, timezone from `market.timezone`) → Fetch TikTok → Fetch YouTube → Fetch Meta → Fetch Competitors → Normalize → Deduplicate → Filter → Extract transcripts / text → AI: Creative DNA → AI: Pattern clustering → Trend scoring → Saturation scoring → Product adaptation → Hook scoring → Save database → Generate daily report → Telegram / Slack

Each stage independently testable.

## 24. AI prompt architecture

No single giant prompt. Separate prompts, each in its own file:

01_extract_creative_dna, 02_classify_hook, 03_cluster_patterns, 04_detect_trends, 05_score_saturation, 06_adapt_to_product, 07_generate_hooks, 08_generate_cat_execution, 09_score_hooks, 10_analyze_winners, 11_generate_daily_report

## 25. Error handling

Every external API call needs: retry, timeout, error logging, rate limit handling, fallback, structured error messages.

If TikTok fails, continue with YouTube + Meta. Never fail the whole workflow. If the AI API fails: retry, log, continue with remaining content.

## 26. Cost control

Do not send every video to the most expensive model.

100 raw videos → cheap filtering → 50 candidates → AI analysis → 20 strongest patterns → detailed AI analysis → 10 trends → generate hooks

Cheaper models for classification, stronger model for final creative reasoning. Cache repeated content. Never analyze the same URL twice unless content changed.

## 27. Quality control

Validate before the final report. Reject concepts with: copied wording, low product relevance, weak hook, no clear visual, impossible production, too generic, trend already saturated, unsafe or misleading claim.

Prefer: original, simple, visual, fast, specific, product relevant, emotionally clear.

## 28. No prediction claims

Never say "This hook WILL go viral." Use: High opportunity, Medium opportunity, Experimental, Low opportunity. The system identifies promising signals, it does not guarantee virality.

## 29. Project structure

```
creative-intelligence/
├── README.md
├── .env.example
├── docker-compose.yml
├── config/
│   └── product.yaml
├── prompts/
│   ├── extract_creative_dna.md
│   ├── classify_hook.md
│   ├── cluster_patterns.md
│   ├── detect_trends.md
│   ├── score_saturation.md
│   ├── generate_hooks.md
│   ├── cat_adaptation.md
│   ├── score_hooks.md
│   ├── analyze_winners.md
│   └── daily_report.md
├── src/
│   ├── collectors/
│   ├── processors/
│   ├── analyzers/
│   ├── scoring/
│   ├── generators/
│   ├── database/
│   └── notifications/
├── workflows/
│   └── n8n/
├── tests/
└── docs/
```

## 30. Success criteria

The first working version succeeds when every morning it can:

1. Collect fresh social creative signals
2. Normalize them
3. Remove duplicates
4. Extract hooks
5. Identify creative mechanisms
6. Detect emerging patterns
7. Estimate saturation
8. Generate original learning app hooks
9. Generate cat mascot executions
10. Score them
11. Save everything
12. Send a concise daily report

It must be useful to a growth and creative team, not merely technically impressive.

The question it answers every day:

**"What are the 5 most interesting creative ideas we should test today, and why?"**
