"""Common interface that every platform integration implements."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class PlatformError(Exception):
    """A platform rejected the request or returned something unexpected."""


@dataclass
class PublishedPost:
    """What a platform returns after a successful publish."""

    url: str
    post_id: str
    extra: Dict[str, Any] = field(default_factory=dict)


class BasePlatform(ABC):
    """Base class for a third-party posting platform.

    Subclasses implement ``publish`` (create the post through the official API)
    and ``check_public_access`` (verify, *without* credentials, that anyone can
    read the post). The posting service handles timing, timeouts and errors.
    """

    #: Stable identifier used in ENABLED_PLATFORMS.
    key: str = ""
    #: Human readable name returned in the API response.
    name: str = ""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @abstractmethod
    def missing_settings(self) -> List[str]:
        """Names of required environment variables that are not set."""

    def is_configured(self) -> bool:
        return not self.missing_settings()

    @abstractmethod
    async def publish(self, client: httpx.AsyncClient, message: str, link: str) -> PublishedPost:
        """Publish ``message`` and return the public URL of the new post."""

    @abstractmethod
    async def check_public_access(self, client: httpx.AsyncClient, post: PublishedPost) -> bool:
        """Return True if the post can be read anonymously."""

    # --- helpers -----------------------------------------------------------
    @staticmethod
    def parse_json(response: httpx.Response, action: str) -> Dict[str, Any]:
        """Return the JSON body of a successful response or raise PlatformError.

        Builds the error message ourselves instead of ``raise_for_status`` so the
        request URL (which can contain a token, e.g. Telegram) never leaks.
        """
        if response.status_code >= 400:
            raise PlatformError(
                f"{action} failed: HTTP {response.status_code} - {_short_error(response)}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise PlatformError(f"{action} failed: response was not valid JSON") from exc
        if not isinstance(data, dict):
            raise PlatformError(f"{action} failed: unexpected response format")
        return data


def _short_error(response: httpx.Response) -> str:
    """Extract a concise, human-readable error message from an API response."""
    if response.status_code in (401, 403):
        prefix = "Authentication failed" if response.status_code == 401 else "Permission denied"
    elif response.status_code == 429:
        prefix = "Rate limited"
    else:
        prefix = response.reason_phrase or "Error"

    detail: Optional[str] = None
    try:
        body = response.json()
        if isinstance(body, dict):
            for key in ("error_description", "message", "description", "error"):
                value = body.get(key)
                if isinstance(value, str) and value:
                    detail = value
                    break
    except ValueError:
        pass
    text = f"{prefix}: {detail}" if detail else prefix
    return text[:300]
