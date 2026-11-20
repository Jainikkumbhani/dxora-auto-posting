"""Mastodon integration (REST API).

Docs: https://docs.joinmastodon.org/methods/statuses/#create
Auth: access token from Preferences > Development > New application (scope: write:statuses).
"""

import uuid
from typing import List

import httpx

from app.platforms.base import BasePlatform, PlatformError, PublishedPost


class MastodonPlatform(BasePlatform):
    key = "mastodon"
    name = "Mastodon"

    def missing_settings(self) -> List[str]:
        missing = []
        if not self.settings.mastodon_instance_url:
            missing.append("MASTODON_INSTANCE_URL")
        if not self.settings.mastodon_access_token:
            missing.append("MASTODON_ACCESS_TOKEN")
        return missing

    @property
    def _base_url(self) -> str:
        return (self.settings.mastodon_instance_url or "").rstrip("/")

    async def publish(self, client: httpx.AsyncClient, message: str, link: str) -> PublishedPost:
        token = self.settings.mastodon_access_token
        data = self.parse_json(
            await client.post(
                f"{self._base_url}/api/v1/statuses",
                headers={
                    "Authorization": f"Bearer {token.get_secret_value() if token else ''}",
                    # Prevents a duplicate post if the same request is ever re-sent.
                    "Idempotency-Key": str(uuid.uuid4()),
                },
                data={"status": message, "visibility": "public"},
            ),
            "Mastodon post",
        )
        if not data.get("url") or not data.get("id"):
            raise PlatformError("Mastodon post failed: no status URL returned")
        return PublishedPost(url=data["url"], post_id=str(data["id"]))

    async def check_public_access(self, client: httpx.AsyncClient, post: PublishedPost) -> bool:
        # Anonymous request; some instances disable unauthenticated API access,
        # in which case we honestly report False.
        response = await client.get(f"{self._base_url}/api/v1/statuses/{post.post_id}")
        if response.status_code != 200:
            return False
        return response.json().get("visibility") == "public"
