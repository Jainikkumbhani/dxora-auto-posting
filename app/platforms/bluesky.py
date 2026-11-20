"""Bluesky integration (AT Protocol XRPC API).

Docs: https://docs.bsky.app/docs/advanced-guides/posts
Auth: account handle + App Password (Settings > Privacy and security > App passwords).
"""

from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx

from app.platforms.base import BasePlatform, PlatformError, PublishedPost

PUBLIC_APPVIEW = "https://public.api.bsky.app"


def build_link_facet(text: str, link: str) -> Dict[str, Any]:
    """Bluesky does not auto-link URLs; a "facet" with UTF-8 byte offsets is required."""
    char_start = text.index(link)
    byte_start = len(text[:char_start].encode("utf-8"))
    byte_end = byte_start + len(link.encode("utf-8"))
    return {
        "index": {"byteStart": byte_start, "byteEnd": byte_end},
        "features": [{"$type": "app.bsky.richtext.facet#link", "uri": link}],
    }


class BlueskyPlatform(BasePlatform):
    key = "bluesky"
    name = "Bluesky"

    def missing_settings(self) -> List[str]:
        missing = []
        if not self.settings.bluesky_handle:
            missing.append("BLUESKY_HANDLE")
        if not self.settings.bluesky_app_password:
            missing.append("BLUESKY_APP_PASSWORD")
        return missing

    async def publish(self, client: httpx.AsyncClient, message: str, link: str) -> PublishedPost:
        service = self.settings.bluesky_service_url.rstrip("/")
        password = self.settings.bluesky_app_password
        session = self.parse_json(
            await client.post(
                f"{service}/xrpc/com.atproto.server.createSession",
                json={
                    "identifier": self.settings.bluesky_handle,
                    "password": password.get_secret_value() if password else "",
                },
            ),
            "Bluesky login",
        )
        did, handle, token = session.get("did"), session.get("handle"), session.get("accessJwt")
        if not (did and handle and token):
            raise PlatformError("Bluesky login failed: incomplete session response")

        record = {
            "$type": "app.bsky.feed.post",
            "text": message,
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "facets": [build_link_facet(message, link)],
        }
        created = self.parse_json(
            await client.post(
                f"{service}/xrpc/com.atproto.repo.createRecord",
                headers={"Authorization": f"Bearer {token}"},
                json={"repo": did, "collection": "app.bsky.feed.post", "record": record},
            ),
            "Bluesky post",
        )
        uri = created.get("uri")  # at://did/app.bsky.feed.post/<rkey>
        if not uri:
            raise PlatformError("Bluesky post failed: no record URI returned")
        rkey = uri.rsplit("/", 1)[-1]
        return PublishedPost(
            url=f"https://bsky.app/profile/{handle}/post/{rkey}",
            post_id=rkey,
            extra={"uri": uri},
        )

    async def check_public_access(self, client: httpx.AsyncClient, post: PublishedPost) -> bool:
        # Public AppView, no credentials sent.
        response = await client.get(
            f"{PUBLIC_APPVIEW}/xrpc/app.bsky.feed.getPosts", params={"uris": post.extra["uri"]}
        )
        if response.status_code != 200:
            return False
        return bool(response.json().get("posts"))
