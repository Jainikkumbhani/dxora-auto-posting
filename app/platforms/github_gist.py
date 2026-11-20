"""GitHub Gist integration (REST API).

Docs: https://docs.github.com/en/rest/gists/gists#create-a-gist
Auth: fine-grained personal access token with "Gists: Read and write" permission.
"""

from typing import List

import httpx

from app.platforms.base import BasePlatform, PlatformError, PublishedPost

GITHUB_API = "https://api.github.com"
GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


class GitHubGistPlatform(BasePlatform):
    key = "github_gist"
    name = "GitHub Gist"

    def missing_settings(self) -> List[str]:
        return [] if self.settings.github_token else ["GITHUB_TOKEN"]

    async def publish(self, client: httpx.AsyncClient, message: str, link: str) -> PublishedPost:
        token = self.settings.github_token
        data = self.parse_json(
            await client.post(
                f"{GITHUB_API}/gists",
                headers={
                    **GITHUB_HEADERS,
                    "Authorization": f"Bearer {token.get_secret_value() if token else ''}",
                },
                json={
                    "description": message,
                    "public": True,
                    "files": {"post.md": {"content": f"{message}\n"}},
                },
            ),
            "GitHub Gist post",
        )
        if not data.get("html_url") or not data.get("id"):
            raise PlatformError("GitHub Gist post failed: no gist URL returned")
        return PublishedPost(url=data["html_url"], post_id=str(data["id"]))

    async def check_public_access(self, client: httpx.AsyncClient, post: PublishedPost) -> bool:
        # Anonymous request (no token) must succeed and report a public gist.
        response = await client.get(f"{GITHUB_API}/gists/{post.post_id}", headers=GITHUB_HEADERS)
        return response.status_code == 200 and response.json().get("public") is True
