"""Performance feedback loop. Spec sections 19, 20, 21.

winner = true is not an insight. The insight is the combination that produced it,
stored as a reusable pattern the next generation run can actually use.
"""
from __future__ import annotations

import csv
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ci.config import Settings, get_settings
from ci.llm.client import LlmClient
from ci.llm.prompts import load_prompt
from ci.logging import get_logger, log_event
from ci.models import TestResult, Winner

log = get_logger(__name__)

CSV_ALIASES = {
    "3_sec_view_rate": "three_sec_view_rate",
    "25_percent_view_rate": "twentyfive_percent_view_rate",
    "50_percent_view_rate": "fifty_percent_view_rate",
    "95_percent_view_rate": "ninetyfive_percent_view_rate",
    "spend_usd": "spend",
}

# Winner rules. Configurable rather than hardcoded, per the phase brief.
DEFAULT_RULES = {
    "min_spend": 100.0,
    "min_impressions": 10000,
    "roas_at_least": 1.5,
    "cac_at_most": 0.0,          # 0 disables the CAC test
    "three_sec_rate_at_least": 0.25,
    "require": "any",            # any | all
}


def _num(value: Any, cast=float) -> Any:
    try:
        text = str(value).replace(",", "").replace("$", "").replace("%", "").strip()
        return cast(text or 0)
    except (TypeError, ValueError):
        return cast(0)


def load_test_results(path: str | Path) -> list[TestResult]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"csv not found: {path}")
    rows: list[TestResult] = []
    with path.open(newline="") as fh:
        for raw in csv.DictReader(fh):
            clean: dict[str, Any] = {}
            for key, value in raw.items():
                k = (key or "").strip().lower().replace(" ", "_").replace("%", "percent")
                clean[CSV_ALIASES.get(k, k)] = value
            rows.append(TestResult(
                creative_id=str(clean.get("creative_id", "")).strip(),
                hook_id=str(clean.get("hook_id", "")).strip(),
                trend_id=str(clean.get("trend_id", "")).strip(),
                date_launched=str(clean.get("date_launched", "")).strip(),
                spend=_num(clean.get("spend")),
                impressions=_num(clean.get("impressions"), int),
                views=_num(clean.get("views"), int),
                three_sec_view_rate=_num(clean.get("three_sec_view_rate")),
                twentyfive_percent_view_rate=_num(clean.get("twentyfive_percent_view_rate")),
                fifty_percent_view_rate=_num(clean.get("fifty_percent_view_rate")),
                ninetyfive_percent_view_rate=_num(clean.get("ninetyfive_percent_view_rate")),
                ctr=_num(clean.get("ctr")),
                cpc=_num(clean.get("cpc")),
                installs=_num(clean.get("installs"), int),
                install_rate=_num(clean.get("install_rate")),
                purchases=_num(clean.get("purchases"), int),
                conversion_rate=_num(clean.get("conversion_rate")),
                cac=_num(clean.get("cac")),
                roas=_num(clean.get("roas")),
            ))
    return rows


def mark_winners(results: list[TestResult], rules: dict[str, Any] | None = None) -> list[TestResult]:
    cfg = {**DEFAULT_RULES, **(rules or {})}
    for row in results:
        # Not enough spend or impressions means we do not know yet, which is not
        # the same as losing. Never promote noise to a winner.
        if row.spend < float(cfg["min_spend"]) or row.impressions < int(cfg["min_impressions"]):
            row.winner = False
            continue
        tests = []
        if float(cfg.get("roas_at_least", 0)) > 0:
            tests.append(row.roas >= float(cfg["roas_at_least"]))
        if float(cfg.get("cac_at_most", 0)) > 0:
            tests.append(0 < row.cac <= float(cfg["cac_at_most"]))
        if float(cfg.get("three_sec_rate_at_least", 0)) > 0:
            tests.append(row.three_sec_view_rate >= float(cfg["three_sec_rate_at_least"]))
        row.winner = all(tests) if cfg.get("require") == "all" else any(tests)
    return results


class WinnerAnalyzer:
    def __init__(self, client: LlmClient, settings: Settings | None = None) -> None:
        self.client = client
        self.settings = settings or get_settings()
        self.prompt = load_prompt("analyze_winners")

    def analyse(self, result: TestResult, creative: dict[str, Any],
                baseline: list[dict[str, Any]]) -> Winner:
        data = self.client.run_prompt(
            self.prompt, stage="analyze_winners",
            cache_content=f"{result.creative_id}|{self.prompt.version}",
            creative=creative, performance=result.model_dump(),
            baseline=baseline[:10],
        ).data
        log_event(log, logging.INFO, "winner analysed",
                  creative_id=result.creative_id, pattern=data.get("reusable_pattern", "")[:60])
        return Winner(
            winner_id=f"win_{uuid.uuid4().hex[:10]}",
            creative_id=result.creative_id,
            date_analyzed=datetime.now(timezone.utc).date().isoformat(),
            winning_hook_type=data.get("winning_hook_type", []),
            winning_emotion=data.get("winning_emotion", ""),
            winning_visual=data.get("winning_visual", ""),
            winning_structure=data.get("winning_structure", ""),
            winning_problem=data.get("winning_problem", ""),
            winning_payoff=data.get("winning_payoff", ""),
            winning_cta=data.get("winning_cta", ""),
            winning_audience=data.get("winning_audience", ""),
            reusable_pattern=data.get("reusable_pattern", ""),
            roas=result.roas,
            cac=result.cac,
        )
