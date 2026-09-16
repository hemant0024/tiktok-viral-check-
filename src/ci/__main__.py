"""CLI. Every stage is a command that reads from storage and writes to storage.

n8n schedules and chains these. It holds no logic.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from ci import logging as ci_logging
from ci.config import get_settings
from ci.database import get_repository
from ci.llm.client import LlmClient
from ci.patterns.embed import get_embedder

app = typer.Typer(add_completion=False, help="Daily Creative Intelligence System")
collect_app = typer.Typer(help="Collect from a source")
analyze_app = typer.Typer(help="AI analysis")
patterns_app = typer.Typer(help="Patterns, trends, saturation")
import_app = typer.Typer(help="Imports")
app.add_typer(collect_app, name="collect")
app.add_typer(analyze_app, name="analyze")
app.add_typer(patterns_app, name="patterns")
app.add_typer(import_app, name="import")

ALL_SOURCES = ["competitor_ugc", "meta_ads", "tiktok", "youtube", "instagram"]


def _setup():
    settings = get_settings()
    ci_logging.configure(settings.log_level)
    return settings, get_repository(settings)


def _emit(payload: dict) -> None:
    typer.echo(json.dumps(payload, indent=2, default=str))


@app.command()
def healthcheck():
    """Confirm config loads, storage is reachable, and prompts parse."""
    from ci.stages import stage_healthcheck

    settings, repo = _setup()
    result = stage_healthcheck(repo, settings)
    _emit(result)
    raise typer.Exit(0 if result.get("ok") else 1)


@collect_app.command("youtube")
def collect_youtube():
    from ci.stages import stage_collect
    settings, repo = _setup()
    _emit(stage_collect(repo, settings, ["youtube"]))


@collect_app.command("tiktok")
def collect_tiktok():
    from ci.stages import stage_collect
    settings, repo = _setup()
    _emit(stage_collect(repo, settings, ["tiktok"]))


@collect_app.command("meta_ads")
def collect_meta_ads():
    from ci.stages import stage_collect
    settings, repo = _setup()
    _emit(stage_collect(repo, settings, ["meta_ads"]))


@collect_app.command("competitor_ugc")
def collect_competitor_ugc():
    """Organic creator videos that mention a competitor app."""
    from ci.stages import stage_collect
    settings, repo = _setup()
    _emit(stage_collect(repo, settings, ["competitor_ugc"]))


@collect_app.command("csv")
def collect_csv(path: str = typer.Option(..., "--path")):
    from ci.stages import stage_collect
    settings, repo = _setup()
    _emit(stage_collect(repo, settings, ["csv"], path=path))


@collect_app.command("all")
def collect_all():
    """Every enabled source. One failing source never ends the run."""
    from ci.stages import stage_collect
    settings, repo = _setup()
    _emit(stage_collect(repo, settings, ALL_SOURCES))


@analyze_app.command("dna")
def analyze_dna(limit: int = typer.Option(0, "--limit", help="0 means all candidates")):
    from ci.stages import stage_analyze
    settings, repo = _setup()
    _emit(stage_analyze(repo, settings, LlmClient(settings), limit or None))


@analyze_app.command("hooks")
def analyze_hooks(limit: int = typer.Option(0, "--limit")):
    """Hook classification runs alongside DNA extraction in one pass."""
    analyze_dna(limit)


@patterns_app.command("cluster")
def patterns_cluster():
    from ci.stages import stage_patterns_cluster
    settings, repo = _setup()
    _emit(stage_patterns_cluster(repo, settings, LlmClient(settings), get_embedder()))


@patterns_app.command("score")
def patterns_score():
    from ci.stages import stage_patterns_score
    settings, repo = _setup()
    _emit(stage_patterns_score(repo, settings, LlmClient(settings)))


@app.command()
def generate():
    from ci.stages import stage_generate
    settings, repo = _setup()
    _emit(stage_generate(repo, settings, LlmClient(settings), get_embedder()))


@app.command()
def radar(
    show: bool = typer.Option(True, "--show/--json", help="print the feed or emit json"),
    limit: int = typer.Option(0, "--limit", help="0 shows the whole feed"),
    kind: str = typer.Option("", "--kind", help="ads, ugc, or empty for both"),
):
    """Which competitor video is going viral, or about to. Costs nothing to run."""
    from ci.stages import stage_radar
    settings, repo = _setup()
    result = stage_radar(repo, settings, kind=kind or None)
    if show:
        from ci.report.radar_render import render_feed
        from ci.stages import today
        typer.echo(render_feed(today(), result["feed"], None, limit or None))
    else:
        _emit({"summary": result["summary"], "hot": result["hot"], "feed": result["feed"]})


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8000, "--port"),
):
    """Run the HTTP front door that n8n drives."""
    from ci.server import serve as _serve
    _serve(host, port)


@app.command()
def dashboard(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8787, "--port"),
):
    """Local dashboard: browse the radar, filter it, and tune the thresholds.

    Binds to localhost only by default. This one can rewrite config files, so it
    must never be the thing left listening on 0.0.0.0.
    """
    from ci.dashboard.server import serve as _serve
    _serve(host, port)


@app.command()
def trends():
    """How videos and competitors moved since yesterday. Needs 2+ days of history."""
    from ci.stages import stage_trends
    settings, repo = _setup()
    _emit(stage_trends(repo, settings))


@app.command()
def watch():
    """Re-poll videos that look like they are taking off. Run every 30 min.

    Daily snapshots cannot see hourly distribution waves, and waves are the
    strongest signal there is.
    """
    from ci.stages import stage_watch
    settings, repo = _setup()
    _emit(stage_watch(repo, settings))


@app.command("sheets-push")
def sheets_push(
    tables: str = typer.Option("", "--tables", help="comma separated, default every tab"),
    kind: str = typer.Option("", "--kind", help="ads, ugc, or empty for both plus trends"),
):
    """Push results into the shared Google Sheet. This is where every flow ends."""
    from ci.stages import stage_sheets_push
    settings, repo = _setup()
    wanted = [t.strip() for t in tables.split(",") if t.strip()] or None
    _emit(stage_sheets_push(repo, settings, kind=kind or None, tables=wanted))


@app.command("brief-input")
def brief_input(
    kind: str = typer.Option("ugc", "--kind", help="ads or ugc"),
    limit: int = typer.Option(12, "--limit"),
):
    """The compact payload the Claude node in n8n reads. Prints JSON."""
    from ci.stages import stage_brief_input
    settings, repo = _setup()
    _emit(stage_brief_input(repo, settings, kind=kind, limit=limit))


@app.command("save-brief")
def save_brief(
    path: str = typer.Option("", "--path", help="read the brief from a file"),
    text: str = typer.Option("", "--text", help="or pass it inline"),
    source: str = typer.Option("claude", "--source"),
):
    """Save Claude's written read of the day into the DAILY_BRIEF tab."""
    from ci.stages import stage_save_brief
    settings, repo = _setup()
    body = Path(path).read_text() if path else text
    if not body.strip() and not sys.stdin.isatty():
        body = sys.stdin.read()
    _emit(stage_save_brief(repo, settings, brief=body, source=source))


@app.command("notify-radar")
def notify_radar(channel: str = typer.Argument("slack")):
    """Send the radar feed to Slack or Telegram."""
    from ci.stages import stage_notify_radar
    settings, repo = _setup()
    _emit(stage_notify_radar(repo, settings, channel))


@app.command()
def report(show: bool = typer.Option(False, "--show", help="print the message itself")):
    from ci.stages import stage_report
    settings, repo = _setup()
    result = stage_report(repo, settings)
    if show:
        typer.echo(result["concise"])
    else:
        _emit({k: v for k, v in result.items() if k != "concise"})


@app.command()
def notify(channel: str = typer.Argument("slack")):
    from ci.stages import stage_notify
    settings, repo = _setup()
    _emit(stage_notify(repo, settings, channel))


@import_app.command("ads")
def import_ads(path: str = typer.Option(..., "--path")):
    from ci.stages import stage_import_ads
    settings, repo = _setup()
    _emit(stage_import_ads(repo, settings, LlmClient(settings), path))


@app.command()
def pipeline(
    notify_channel: str = typer.Option("", "--notify", help="slack, telegram, or empty to skip"),
    sources: str = typer.Option("", "--sources", help="comma separated, default all enabled"),
):
    """The whole morning run. Every stage is isolated, so one failure does not stop the rest."""
    from ci.stages import (
        stage_collect, stage_analyze, stage_patterns_cluster,
        stage_patterns_score, stage_generate, stage_report, stage_notify, stage_radar,
        stage_sheets_push, stage_trends,
    )

    settings, repo = _setup()
    client = LlmClient(settings)
    embedder = get_embedder()
    chosen = [s.strip() for s in sources.split(",") if s.strip()] or ALL_SOURCES
    steps = [
        ("collect", lambda: stage_collect(repo, settings, chosen)),
        ("analyze", lambda: stage_analyze(repo, settings, client)),
        ("patterns:cluster", lambda: stage_patterns_cluster(repo, settings, client, embedder)),
        ("patterns:score", lambda: stage_patterns_score(repo, settings, client)),
        ("generate", lambda: stage_generate(repo, settings, client, embedder)),
        ("radar", lambda: stage_radar(repo, settings)),
        ("trends", lambda: stage_trends(repo, settings)),
        ("sheets", lambda: stage_sheets_push(repo, settings)),
        ("report", lambda: stage_report(repo, settings)),
    ]
    if notify_channel:
        steps.append((f"notify:{notify_channel}", lambda: stage_notify(repo, settings, notify_channel)))

    results, failed = {}, []
    for name, step in steps:
        try:
            out = step()
            results[name] = out.get("summary", {}).get("counts", out)
        except Exception as exc:  # noqa: BLE001 - a stage failing must not hide the rest
            failed.append({"stage": name, "error": f"{type(exc).__name__}: {exc}"})
            results[name] = {"error": str(exc)}
    _emit({"stages": results, "failed": failed, "llm": client.stats()})
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    app()
