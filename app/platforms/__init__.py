"""Platform registry - the application selects platforms internally."""

from typing import Dict, List, Type

from app.config import Settings
from app.platforms.base import BasePlatform
from app.platforms.bluesky import BlueskyPlatform
from app.platforms.devto import DevToPlatform
from app.platforms.discord import DiscordPlatform
from app.platforms.github_gist import GitHubGistPlatform
from app.platforms.mastodon import MastodonPlatform
from app.platforms.telegram import TelegramPlatform

PLATFORM_CLASSES: Dict[str, Type[BasePlatform]] = {
    cls.key: cls
    for cls in (
        BlueskyPlatform,
        MastodonPlatform,
        TelegramPlatform,
        GitHubGistPlatform,
        DevToPlatform,
        DiscordPlatform,
    )
}


def get_platforms(settings: Settings) -> List[BasePlatform]:
    """Instantiate the platforms to post to.

    ENABLED_PLATFORMS (comma separated keys) narrows the list; when it is empty
    every registered platform is used. Unknown keys are rejected at startup.
    """
    keys = settings.enabled_platform_keys or list(PLATFORM_CLASSES)
    unknown = [key for key in keys if key not in PLATFORM_CLASSES]
    if unknown:
        raise ValueError(
            f"Unknown platform(s) in ENABLED_PLATFORMS: {', '.join(unknown)}. "
            f"Valid keys: {', '.join(PLATFORM_CLASSES)}"
        )
    return [PLATFORM_CLASSES[key](settings) for key in keys]
