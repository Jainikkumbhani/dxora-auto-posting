"""Discord integration (channel webhook).

Docs: https://discord.com/developers/docs/resources/webhook#execute-webhook
Auth: webhook URL from Server Settings > Integrations > Webhooks (treated as a secret).

Discord messages are only visible to members of the server, so this platform
always reports ``public_access = False`` - it demonstrates honest reporting.
"""

from typing import List

import httpx

from app.platforms.base import BasePlatform, PlatformError, PublishedPost


class DiscordPlatform(BasePlatform):
    key = "discord"
    name = "Discord"

    def missing_settings(self) -> List[str]:
        return [] if self.settings.discord_webhook_url else ["DISCORD_WEBHOOK_URL"]

    async def publish(self, client: httpx.AsyncClient, message: str, link: str) -> PublishedPost:
        webhook = self.settings.discord_webhook_url
        webhook_url = webhook.get_secret_value() if webhook else ""

        # The webhook object tells us which server (guild) the channel belongs to.
        info = self.parse_json(await client.get(webhook_url), "Discord webhook lookup")
        guild_id = info.get("guild_id")

        sent = self.parse_json(
            await client.post(
                webhook_url,
                params={"wait": "true"},  # return the created message
                # Never let the message ping @everyone / roles / users.
                json={"content": message, "allowed_mentions": {"parse": []}},
            ),
            "Discord post",
        )
        message_id, channel_id = sent.get("id"), sent.get("channel_id")
        if not (message_id and channel_id and guild_id):
            raise PlatformError("Discord post failed: incomplete message response")
        return PublishedPost(
            url=f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}",
            post_id=str(message_id),
        )

    async def check_public_access(self, client: httpx.AsyncClient, post: PublishedPost) -> bool:
        # Server messages require login + membership; never publicly readable.
        return False
