"""Publishes one message to every selected platform, independently and concurrently."""

import asyncio
import logging
from datetime import datetime
from typing import List, Sequence
from zoneinfo import ZoneInfo

import httpx

from app.config import Settings
from app.platforms.base import BasePlatform, PlatformError
from app.schemas import PlatformResult, PostingResponse, PostingSummary

logger = logging.getLogger(__name__)

USER_AGENT = "dxora-auto-posting/1.0"


class PostingService:
    def __init__(
        self,
        settings: Settings,
        platforms: Sequence[BasePlatform],
        client: httpx.AsyncClient,
    ) -> None:
        self.settings = settings
        self.platforms = list(platforms)
        self.client = client
        self.tz = ZoneInfo(settings.app_timezone)
        self._secrets = settings.secret_values()

    async def post_to_all(self, message: str, link: str) -> PostingResponse:
        """Post to all platforms at the same time; one failure never stops the others."""
        results: List[PlatformResult] = await asyncio.gather(
            *(self._post_to_platform(platform, message, link) for platform in self.platforms)
        )
        succeeded = sum(1 for r in results if r.status == "success")
        logger.info("Posting finished: %d/%d platforms succeeded", succeeded, len(results))
        return PostingResponse(
            success=succeeded > 0,
            results=results,
            summary=PostingSummary(
                total=len(results),
                succeeded=succeeded,
                failed=len(results) - succeeded,
                timezone=self.settings.app_timezone,
            ),
        )

    async def _post_to_platform(
        self, platform: BasePlatform, message: str, link: str
    ) -> PlatformResult:
        missing = platform.missing_settings()
        if missing:
            return self._failed(platform, f"Platform not configured: missing {', '.join(missing)}")

        timeout = self.settings.platform_timeout_seconds
        try:
            post = await asyncio.wait_for(platform.publish(self.client, message, link), timeout)
        except asyncio.TimeoutError:
            return self._failed(platform, f"Timed out after {timeout:g} seconds")
        except PlatformError as exc:
            return self._failed(platform, str(exc))
        except httpx.HTTPError as exc:
            return self._failed(platform, f"Network error: {type(exc).__name__}")
        except Exception:  # defensive: an unexpected bug in one integration
            logger.exception("Unexpected error while posting to %s", platform.name)
            return self._failed(platform, "Unexpected internal error")

        # Timestamp of the successful publish, in the configured timezone.
        posted_at = datetime.now(self.tz)
        public = await self._check_public(platform, post)
        logger.info("%s: posted %s (public=%s)", platform.name, post.url, public)
        return PlatformResult(
            platform=platform.name,
            status="success",
            posted_url=post.url,
            public_access=public,
            date=posted_at.strftime("%Y-%m-%d"),
            time=posted_at.strftime("%H:%M:%S"),
            error=None,
        )

    async def _check_public(self, platform: BasePlatform, post) -> bool:
        """Verify anonymous access; on any error report False rather than guessing."""
        try:
            return await asyncio.wait_for(
                platform.check_public_access(self.client, post),
                self.settings.platform_timeout_seconds,
            )
        except Exception as exc:
            logger.warning("%s: public access check failed (%s)", platform.name, type(exc).__name__)
            return False

    def _failed(self, platform: BasePlatform, error: str) -> PlatformResult:
        error = self._redact(error)
        logger.warning("%s: failed - %s", platform.name, error)
        return PlatformResult(
            platform=platform.name,
            status="failed",
            posted_url=None,
            public_access=False,
            date=None,
            time=None,
            error=error,
        )

    def _redact(self, text: str) -> str:
        """Make sure no credential ever appears in an error message or log line."""
        for secret in self._secrets:
            text = text.replace(secret, "***")
        return text
