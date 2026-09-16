"""Google Sheets adapter. Adapter #1 per spec section 22.

Sheets is slow and rate limited (roughly 60 reads and 60 writes per minute), so
every method reads or writes a whole tab at once rather than cell by cell.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

from ci.database.base import BaseRepository
from ci.models import TABLES

_COMPLEX = (list, dict)


def _encode(value: Any) -> Any:
    if isinstance(value, _COMPLEX):
        return json.dumps(value, default=str)
    if value is None:
        return ""
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in "[{":
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


class SheetsRepository(BaseRepository):
    name = "sheets"

    def __init__(self, service_account_json: str, sheet_id: str) -> None:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(service_account_json, scopes=scopes)
        self._client = gspread.authorize(creds)
        self._sheet = self._client.open_by_key(sheet_id)
        self._ws_cache: dict[str, Any] = {}

    def _ws(self, table: str):
        if table in self._ws_cache:
            return self._ws_cache[table]
        try:
            ws = self._sheet.worksheet(table)
        except Exception:
            model = TABLES[table]
            headers = list(model.model_fields.keys())
            ws = self._sheet.add_worksheet(title=table, rows=1000, cols=max(len(headers), 10))
            ws.update([headers], "A1")
        self._ws_cache[table] = ws
        return ws

    def read(self, table: str) -> list[dict[str, Any]]:
        records = self._ws(table).get_all_records()
        return [{k: _decode(v) for k, v in r.items()} for r in records]

    def _headers(self, table: str) -> list[str]:
        return list(TABLES[table].model_fields.keys())

    def _write_all(self, table: str, rows: list[dict[str, Any]]) -> None:
        headers = self._headers(table)
        body = [[_encode(r.get(h, "")) for h in headers] for r in rows]
        ws = self._ws(table)
        ws.clear()
        ws.update([headers] + body, "A1")

    def upsert(self, table: str, rows: Iterable[dict[str, Any]]) -> int:
        merged, written = self._merge(table, self.read(table), rows)
        self._write_all(table, merged)
        return written

    def append(self, table: str, rows: Iterable[dict[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        headers = self._headers(table)
        body = [[_encode(r.get(h, "")) for h in headers] for r in rows]
        self._ws(table).append_rows(body, value_input_option="RAW")
        return len(rows)

    # ---- arbitrary tabs, for reporting views that are not model-backed ----
    def _ws_named(self, tab: str, headers: list[str]):
        try:
            return self._sheet.worksheet(tab)
        except Exception:
            ws = self._sheet.add_worksheet(title=tab, rows=2000, cols=max(len(headers), 10))
            ws.update([headers], "A1")
            return ws

    @staticmethod
    def _headers_from(rows: list[dict[str, Any]]) -> list[str]:
        seen: list[str] = []
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.append(key)
        return seen

    def replace_tab(self, tab: str, rows: list[dict[str, Any]]) -> int:
        headers = self._headers_from(rows)
        ws = self._ws_named(tab, headers)
        ws.clear()
        ws.update([headers] + [[_encode(r.get(h, "")) for h in headers] for r in rows], "A1")
        return len(rows)

    def upsert_tab(self, tab: str, rows: list[dict[str, Any]],
                   key_fields: tuple[str, ...] = ("date", "content_id")) -> int:
        """Merge into an existing tab without losing what is already there."""
        headers = self._headers_from(rows)
        ws = self._ws_named(tab, headers)
        try:
            existing = ws.get_all_records()
        except Exception:
            existing = []
        keys = [k for k in key_fields if k in headers] or headers[:1]

        def key_of(row: dict) -> str:
            return "|".join(str(row.get(k, "")) for k in keys)

        merged = {key_of(r): r for r in existing}
        for row in rows:
            merged[key_of(row)] = row
        out = list(merged.values())
        headers = self._headers_from(out)
        ws.clear()
        ws.update([headers] + [[_encode(r.get(h, "")) for h in headers] for r in out], "A1")
        return len(out)

    def healthcheck(self) -> dict[str, Any]:
        try:
            titles = [ws.title for ws in self._sheet.worksheets()]
            missing = [t for t in TABLES if t not in titles]
            return {"backend": "sheets", "ok": True, "tabs": len(titles), "missing_tabs": missing}
        except Exception as exc:
            return {"backend": "sheets", "ok": False, "error": str(exc)}
