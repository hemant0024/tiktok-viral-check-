# Getting this actually running

Two moving parts. The **ci service** is the Python: it talks to Apify, scores
videos, writes the Google Sheet, posts to Slack. **n8n** only decides when to call
it. n8n holds no logic and no secrets.

The one thing that decides everything else is where those two sit relative to
each other.

## The problem, stated plainly

n8n Cloud (`hemant24.app.n8n.cloud`) runs on n8n's servers. It cannot reach
anything on a laptop. `http://ci:8000` is a name that only exists inside a docker
network on one machine, so from n8n Cloud it does not resolve at all.

n8n Cloud also blocks `$env` outright. An expression like `$env.SLACK_BOT_TOKEN`
does not error there, it silently becomes empty, which is worse.

So: either n8n moves to where the service is, or the service gets a real address.

## Option A — everything on one machine

Free, and the fastest way to see it work end to end. Your machine has to be awake
at 6am or that day is simply skipped.

```bash
cp .env.example .env         # then fill it in, see below
docker compose up -d         # starts ci + a local n8n on :5678
```

Open `http://localhost:5678`, import `workflows/n8n/ugc.json` and `ads.json` into
**two separate blank workflows**, and set each **Config** node's `baseUrl` to
`http://ci:8000`. Delete the cloud copies so nothing runs twice.

## Option B — service on a host with a name, n8n stays in the cloud

A few dollars a month, and it runs whether or not your laptop is open. For a job
whose whole point is knowing something at 6am, this is the honest answer.

1. Any small VPS. 1GB of memory is plenty.
2. Point a DNS A record at it, e.g. `radar.yourdomain.com`.
3. Copy the repo up, fill in `.env`, including:

   ```
   CI_DOMAIN=radar.yourdomain.com
   CI_ACME_EMAIL=you@yourdomain.com
   CI_API_TOKEN=<a long random string>
   ```

4. Start it:

   ```bash
   docker compose -f deploy/docker-compose.public.yml up -d
   ```

   Caddy fetches the HTTPS certificate itself and renews it. The ci service is
   never published directly; Caddy is the only thing listening.

5. Check it: `curl https://radar.yourdomain.com/health` should list 24 stages.

6. In n8n, open each workflow and set the **Config** node's `baseUrl` to
   `https://radar.yourdomain.com`. That is the only URL in either workflow.

### CI_API_TOKEN is not optional here

With no token set, the service accepts **only private addresses** and refuses
everything else. That is deliberate: these endpoints start Apify runs that cost
real money, so a public deployment without a token fails closed rather than
billing quietly. A public deploy with no token will answer nothing.

In n8n, create one credential and both workflows pick it up:

- Type: **Custom Auth**
- Name: **CI service token**
- Value: `{"headers":{"Authorization":"Bearer YOUR_CI_API_TOKEN"}}`

## What n8n needs, and what it does not

It does **not** need an Anthropic API key. The Claude node runs on your instance's
gateway credits, already attached.

It does **not** need a Slack token. The ci service holds that and does the posting,
so no secret sits in a workflow.

It **does** need the one Custom Auth credential above, and the `baseUrl` in each
Config node.

## Failure alerts

Every node continues on error so a half-failed collection still gets scored and
written. That means nothing marks the run as failed on its own, so the last node
in each flow checks every stage and throws if any of them broke. n8n marks the
execution failed and its own alerting takes it from there.

If you want failures in Slack rather than email, add an **Error Trigger** workflow
in n8n and set it as the error workflow on both.

## Before the first real run

1. **Apify, on a paid plan.** This is the hard blocker, not a nice to have.
   Verified 2026-09-11 on the free plan:
   * The free month's $5 credit runs out after roughly 600 videos. Ours went in
     one morning of testing.
   * `apidojo/tiktok-scraper`, the cheap actor at $0.0003 per video, returns
     `{"noResults": true}` for **every** call on a free plan, search and direct
     URL alike. It is effectively paid-only.
   * `clockworks/free-tiktok-scraper` works on free but costs $0.0069 a search.

   So on a paid plan the whole system runs at about **$34/month**. On free it
   runs at $436/month until the credit is gone, and then not at all. The plan
   upgrade pays for itself roughly twelve times over.
2. `GOOGLE_SERVICE_ACCOUNT_JSON`, and the sheet shared with that service account
   address as **Editor**, or every write returns 403.
3. `SLACK_BOT_TOKEN` and `SLACK_CHANNEL`.
4. `python -m ci healthcheck` and read `missing_env`.

`OPENAI_API_KEY` is only for the hook analysis and generation stages. The radar,
the trends, the sheet and the Claude brief all run without it.
