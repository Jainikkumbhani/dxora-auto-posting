"""Telegram integration (Bot API, posting to a public channel).

Docs: https://core.telegram.org/bots/api#sendmessage
Auth: bot token from @BotFather; the bot must be an admin of the public channel.
"""

from typing import List

import httpx

from app.platforms.base import BasePlatform, PlatformError, PublishedPost


class TelegramPlatform(BasePlatform):
    key = "telegram"
    name = "Telegram"

    def missing_settings(self) -> List[str]:
        missing = []
        if not self.settings.telegram_bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.settings.telegram_channel_username:
            missing.append("TELEGRAM_CHANNEL_USERNAME")
        return missing

    @property
    def _channel(self) -> str:
        channel = (self.settings.telegram_channel_username or "").strip()
        return channel if channel.startswith("@") else f"@{channel}"

    async def publish(self, client: httpx.AsyncClient, message: str, link: str) -> PublishedPost:
        token = self.settings.telegram_bot_token
        response = await client.post(
            f"https://api.telegram.org/bot{token.get_secret_value() if token else ''}/sendMessage",
            json={"chat_id": self._channel, "text": message},
        )
        data = self.parse_json(response, "Telegram post")
        if not data.get("ok"):
            raise PlatformError(f"Telegram post failed: {data.get('description', 'unknown error')}")

        result = data.get("result") or {}
        message_id = result.get("message_id")
        username = (result.get("chat") or {}).get("username")
        if not message_id or not username:
            raise PlatformError("Telegram post failed: channel has no public username")
        return PublishedPost(url=f"https://t.me/{username}/{message_id}", post_id=str(message_id))

    async def check_public_access(self, client: httpx.AsyncClient, post: PublishedPost) -> bool:
        # The public embed widget renders the message text only for public posts.
        response = await client.get(post.url, params={"embed": "1"})
        return response.status_code == 200 and "tgme_widget_message_text" in response.text
