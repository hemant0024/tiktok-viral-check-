from __future__ import annotations

from ci.config import Settings, get_settings
from ci.notifications.slack import SlackNotifier
from ci.notifications.telegram import TelegramNotifier

__all__ = ["SlackNotifier", "TelegramNotifier", "get_notifier"]


def get_notifier(name: str, settings: Settings | None = None):
    s = settings or get_settings()
    if name == "slack":
        return SlackNotifier(s.slack_bot_token or "", s.slack_channel)
    if name == "telegram":
        return TelegramNotifier(s.telegram_bot_token or "", s.telegram_chat_id or "")
    raise RuntimeError(f"unknown notifier: {name}")
