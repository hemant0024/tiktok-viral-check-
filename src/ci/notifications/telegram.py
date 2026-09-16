from __future__ import annotations

import httpx


class TelegramNotifier:
    name = "telegram"

    def __init__(self, token: str, chat_id: str) -> None:
        self.token = token
        self.chat_id = chat_id

    def available(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str, title: str = "") -> dict:
        if not self.available():
            raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
        resp = httpx.post(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            json={"chat_id": self.chat_id, "text": f"<pre>{text}</pre>", "parse_mode": "HTML"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
