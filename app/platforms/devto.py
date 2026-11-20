"""DEV Community integration (Forem API v1).

Docs: https://developers.forem.com/api/v1#tag/articles/operation/createArticle
Auth: API key from https://dev.to/settings/extensions ("DEV Community API Keys").
"""

from typing import List

import httpx

from app.platforms.base import BasePlatform, PlatformError, PublishedPost

DEVTO_API = "https://dev.to/api"
DEVTO_ACCEPT = "application/vnd.forem.api-v1+json"
MAX_TITLE_LENGTH = 80


def build_title(message: str, link: str) -> str:
    """Articles need a title: use the message text without the link, trimmed."""
    text = " ".join(message.replace(link, "").split()).strip(" -:|")
    if not text:
        return "New update"
    if len(text) <= MAX_TITLE_LENGTH:
        return text
    return text[: MAX_TITLE_LENGTH - 3].rsplit(" ", 1)[0] + "..."


class DevToPlatform(BasePlatform):
    key = "devto"
    name = "DEV Community"

    def missing_settings(self) -> List[str]:
        return [] if self.settings.devto_api_key else ["DEVTO_API_KEY"]

    async def publish(self, client: httpx.AsyncClient, message: str, link: str) -> PublishedPost:
        api_key = self.settings.devto_api_key
        data = self.parse_json(
            await client.post(
                f"{DEVTO_API}/articles",
                headers={
                    "api-key": api_key.get_secret_value() if api_key else "",
                    "Accept": DEVTO_ACCEPT,
                },
                json={
                    "article": {
                        "title": build_title(message, link),
                        "body_markdown": message,
                        "published": True,
                    }
                },
            ),
            "DEV Community post",
        )
        if not data.get("url") or not data.get("id"):
            raise PlatformError("DEV Community post failed: no article URL returned")
        return PublishedPost(url=data["url"], post_id=str(data["id"]))

    async def check_public_access(self, client: httpx.AsyncClient, post: PublishedPost) -> bool:
        # Only published articles are returned by the anonymous endpoint.
        response = await client.get(
            f"{DEVTO_API}/articles/{post.post_id}", headers={"Accept": DEVTO_ACCEPT}
        )
        return response.status_code == 200
