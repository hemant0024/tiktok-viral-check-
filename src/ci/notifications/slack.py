from __future__ import annotations

import httpx


class SlackNotifier:
    name = "slack"

    def __init__(self, token: str, channel: str) -> None:
        self.token = token
        self.channel = channel

    def available(self) -> bool:
        return bool(self.token and self.channel)

    def send(self, text: str, title: str = "") -> dict:
        if not self.available():
            raise RuntimeError("SLACK_BOT_TOKEN and SLACK_CHANNEL are required")
        resp = httpx.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"channel": self.channel, "text": f"```\n{text}\n```",
                  "unfurl_links": False, "unfurl_media": False},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"slack error: {data.get('error')}")
        return data
