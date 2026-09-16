from __future__ import annotations

from ci.config import Settings, get_settings
from ci.database.base import BaseRepository, Repository, row_key
from ci.database.localjson import LocalJsonRepository
from ci.database.memory import InMemoryRepository

__all__ = [
    "BaseRepository", "Repository", "row_key",
    "InMemoryRepository", "LocalJsonRepository", "get_repository",
]


def get_repository(settings: Settings | None = None) -> Repository:
    s = settings or get_settings()
    backend = s.storage_backend.lower()
    if backend == "memory":
        return InMemoryRepository()
    if backend == "local":
        return LocalJsonRepository(s.local_data_dir)
    if backend == "sheets":
        from ci.database.sheets import SheetsRepository
        if not s.google_service_account_json or not s.google_sheet_id:
            raise RuntimeError(
                "sheets backend needs GOOGLE_SERVICE_ACCOUNT_JSON and GOOGLE_SHEET_ID"
            )
        return SheetsRepository(s.google_service_account_json, s.google_sheet_id)
    raise RuntimeError(f"unknown storage backend: {backend}")
