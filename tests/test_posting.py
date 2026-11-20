"""Tests for the /posting API.

All third-party APIs are simulated with ``httpx.MockTransport`` - no real
network calls are made and no real credentials are needed.
"""

import asyncio
import json
from typing import Callable, Dict, List, Optional

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app, get_posting_service
from app.platforms import PLATFORM_CLASSES, get_platforms
from app.platforms.bluesky import build_link_facet
from app.platforms.devto import build_title
from app.services.posting_service import PostingService
from app.utils.validators import LinkValidationError, extract_single_cta_link

VALID_MESSAGE = (
    "Check out our latest business platform and grow your online visibility. https://example.com"
)

FAKE_CREDENTIALS = dict(
    bluesky_handle="tester.bsky.social",
    bluesky_app_password="bsky-app-pass-123",
    mastodon_instance_url="https://mastodon.example",
    mastodon_access_token="masto-token-123",
    telegram_bot_token="111:telegram-secret",
    telegram_channel_username="@dxora_test",
    github_token="ghp_secret123",
    devto_api_key="devto-key-123",
    discord_webhook_url="https://discord.com/api/webhooks/1/discord-secret",
)


def make_settings(**overrides) -> Settings:
    values = {**FAKE_CREDENTIALS, **overrides}
    return Settings(_env_file=None, **values)


# --------------------------------------------------------------------------
# Fake third-party APIs
# --------------------------------------------------------------------------
def fake_api(failures: Optional[Dict[str, httpx.Response]] = None) -> Callable:
    """Return a MockTransport handler that imitates every platform's API.

    ``failures`` maps a platform key to the response it should return instead.
    """
    failures = failures or {}
    calls: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        host, path = request.url.host, request.url.path

        # --- Bluesky
        if host == "bsky.social" and path.endswith("createSession"):
            return failures.get("bluesky") or httpx.Response(
                200, json={"did": "did:plc:abc", "handle": "tester.bsky.social", "accessJwt": "jwt"}
            )
        if host == "bsky.social" and path.endswith("createRecord"):
            return httpx.Response(
                200, json={"uri": "at://did:plc:abc/app.bsky.feed.post/3kpost", "cid": "c"}
            )
        if host == "public.api.bsky.app":
            return httpx.Response(200, json={"posts": [{"uri": "x"}]})

        # --- Mastodon
        if host == "mastodon.example" and request.method == "POST":
            return failures.get("mastodon") or httpx.Response(
                200, json={"id": "42", "url": "https://mastodon.example/@tester/42"}
            )
        if host == "mastodon.example" and request.method == "GET":
            assert "authorization" not in request.headers  # anonymous check
            return httpx.Response(200, json={"id": "42", "visibility": "public"})

        # --- Telegram
        if host == "api.telegram.org":
            return failures.get("telegram") or httpx.Response(
                200,
                json={"ok": True, "result": {"message_id": 7, "chat": {"username": "dxora_test"}}},
            )
        if host == "t.me":
            return httpx.Response(200, text='<div class="tgme_widget_message_text">hi</div>')

        # --- GitHub Gist
        if host == "api.github.com" and request.method == "POST":
            return failures.get("github_gist") or httpx.Response(
                201, json={"id": "abc123", "html_url": "https://gist.github.com/tester/abc123"}
            )
        if host == "api.github.com" and request.method == "GET":
            assert "authorization" not in request.headers
            return httpx.Response(200, json={"id": "abc123", "public": True})

        # --- DEV Community
        if host == "dev.to" and request.method == "POST":
            return failures.get("devto") or httpx.Response(
                201, json={"id": 99, "url": "https://dev.to/tester/check-out-99"}
            )
        if host == "dev.to" and request.method == "GET":
            return httpx.Response(200, json={"id": 99})

        # --- Discord
        if host == "discord.com" and request.method == "GET":
            return httpx.Response(200, json={"guild_id": "555", "channel_id": "666"})
        if host == "discord.com" and request.method == "POST":
            return failures.get("discord") or httpx.Response(
                200, json={"id": "777", "channel_id": "666"}
            )

        return httpx.Response(404, json={"message": "unexpected request in test"})

    handler.calls = calls  # type: ignore[attr-defined]
    return handler


@pytest.fixture
def make_client():
    """Build a TestClient whose PostingService talks to the fake APIs."""

    def _make(settings: Optional[Settings] = None, failures=None, handler=None) -> TestClient:
        settings = settings or make_settings()
        handler = handler or fake_api(failures)
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        service = PostingService(settings, get_platforms(settings), http_client)
        app.dependency_overrides[get_posting_service] = lambda: service
        client = TestClient(app)
        client.fake_handler = handler  # type: ignore[attr-defined]
        return client

    yield _make
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------
# Input validation
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "message, expected_error",
    [
        ("", "must not be empty"),
        ("     ", "must not be empty"),
        ("A" * 190 + " https://example.com", "must not exceed 200 characters"),
        ("No link in this message at all", "found none"),
        ("Two links https://a.com and https://b.com", "found 2"),
        ("Visit www.example.com today", "must start with http"),
        ("Visit https://localhost:8000 now", "public website"),
        ("Visit http://192.168.1.10/promo now", "private or internal"),
        ("Visit http://127.0.0.1 now", "private or internal"),
        ("Visit https://user:pass@example.com now", "username or password"),
        ("Visit https://example now", "valid domain"),
        ("Visit https://-bad-.com now", "invalid domain"),
        ("Visit https://example.com:99999 now", "not a valid URL"),
    ],
)
def test_invalid_messages_return_422(make_client, message, expected_error):
    response = make_client().post("/posting", json={"message": message})
    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "validation_error"
    assert expected_error in body["error"]["message"]


def test_missing_message_field_returns_422(make_client):
    response = make_client().post("/posting", json={})
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "message"


def test_wrong_type_and_bad_json_return_422(make_client):
    client = make_client()
    assert client.post("/posting", json={"message": 123}).status_code == 422
    bad = client.post("/posting", content="not-json", headers={"Content-Type": "application/json"})
    assert bad.status_code == 422


def test_message_of_exactly_200_chars_is_accepted(make_client):
    link = " https://example.com"
    message = "A" * (200 - len(link)) + link
    assert len(message) == 200
    assert make_client().post("/posting", json={"message": message}).status_code == 200


@pytest.mark.parametrize(
    "message, expected",
    [
        ("Read more: https://example.com/page?x=1.", "https://example.com/page?x=1"),
        ("(see https://example.com)", "https://example.com"),
        ("Visit HTTPS://Example.COM/Path now", "HTTPS://Example.COM/Path"),
        ("Visit https://münchen.de now", "https://münchen.de"),
        ("Public IP http://8.8.8.8/x works", "http://8.8.8.8/x"),
    ],
)
def test_cta_link_extraction(message, expected):
    assert extract_single_cta_link(message) == expected


def test_link_validation_error_is_value_error():
    with pytest.raises(LinkValidationError):
        extract_single_cta_link("ftp://example.com is not http")


# --------------------------------------------------------------------------
# Posting behaviour
# --------------------------------------------------------------------------
def test_successful_posting_to_all_platforms(make_client):
    response = make_client().post("/posting", json={"message": VALID_MESSAGE})
    assert response.status_code == 200
    body = response.json()

    assert body["success"] is True
    assert body["summary"] == {"total": 6, "succeeded": 6, "failed": 0, "timezone": "Asia/Kolkata"}
    by_platform = {r["platform"]: r for r in body["results"]}
    assert by_platform["Bluesky"]["posted_url"] == (
        "https://bsky.app/profile/tester.bsky.social/post/3kpost"
    )
    assert by_platform["Mastodon"]["posted_url"] == "https://mastodon.example/@tester/42"
    assert by_platform["Telegram"]["posted_url"] == "https://t.me/dxora_test/7"
    assert by_platform["GitHub Gist"]["posted_url"] == "https://gist.github.com/tester/abc123"
    assert by_platform["DEV Community"]["posted_url"] == "https://dev.to/tester/check-out-99"
    assert by_platform["Discord"]["posted_url"] == "https://discord.com/channels/555/666/777"

    for result in body["results"]:
        assert set(result) == {
            "platform",
            "status",
            "posted_url",
            "public_access",
            "date",
            "time",
            "error",
        }
        assert result["status"] == "success"
        assert result["error"] is None
        assert len(result["date"]) == 10 and len(result["time"]) == 8
        # Discord server messages are never public; all others are verified public.
        assert result["public_access"] is (result["platform"] != "Discord")


def test_one_platform_failure_does_not_stop_others(make_client):
    client = make_client(
        failures={
            "mastodon": httpx.Response(401, json={"error": "The access token is invalid"}),
            "devto": httpx.Response(500, text="boom"),
        }
    )
    body = client.post("/posting", json={"message": VALID_MESSAGE}).json()
    by_platform = {r["platform"]: r for r in body["results"]}

    assert body["success"] is True
    assert body["summary"]["succeeded"] == 4 and body["summary"]["failed"] == 2
    mastodon = by_platform["Mastodon"]
    assert mastodon == {
        "platform": "Mastodon",
        "status": "failed",
        "posted_url": None,
        "public_access": False,
        "date": None,
        "time": None,
        "error": (
            "Mastodon post failed: HTTP 401 - Authentication failed: The access token is invalid"
        ),
    }
    assert "HTTP 500" in by_platform["DEV Community"]["error"]
    assert by_platform["Bluesky"]["status"] == "success"


def test_unconfigured_platform_is_reported_not_called(make_client):
    settings = make_settings(github_token=None)
    client = make_client(settings=settings)
    body = client.post("/posting", json={"message": VALID_MESSAGE}).json()
    gist = next(r for r in body["results"] if r["platform"] == "GitHub Gist")
    assert gist["status"] == "failed"
    assert gist["error"] == "Platform not configured: missing GITHUB_TOKEN"
    assert not any(req.url.host == "api.github.com" for req in client.fake_handler.calls)


def test_all_platforms_failing_returns_success_false(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    body = make_client(handler=handler).post("/posting", json={"message": VALID_MESSAGE}).json()
    assert body["success"] is False
    assert all(r["status"] == "failed" for r in body["results"])
    assert all(r["error"] == "Network error: ConnectError" for r in body["results"])


def test_platform_timeout_is_reported(make_client):
    async def slow_handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, json={})

    settings = make_settings(platform_timeout_seconds=0.05, enabled_platforms="mastodon")
    body = (
        make_client(settings=settings, handler=slow_handler)
        .post("/posting", json={"message": VALID_MESSAGE})
        .json()
    )
    assert body["results"][0]["error"] == "Timed out after 0.05 seconds"


def test_secrets_never_leak_into_errors(make_client):
    secret = FAKE_CREDENTIALS["telegram_bot_token"]
    failures = {
        "telegram": httpx.Response(400, json={"ok": False, "description": f"bad token {secret}"})
    }
    response = make_client(failures=failures).post("/posting", json={"message": VALID_MESSAGE})
    assert secret not in response.text
    telegram = next(r for r in response.json()["results"] if r["platform"] == "Telegram")
    assert "***" in telegram["error"]


def test_public_access_check_failure_reports_false(make_client):
    base = fake_api()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "public.api.bsky.app":
            return httpx.Response(503)
        return base(request)

    settings = make_settings(enabled_platforms="bluesky")
    result = (
        make_client(settings=settings, handler=handler)
        .post("/posting", json={"message": VALID_MESSAGE})
        .json()["results"][0]
    )
    assert result["status"] == "success"
    assert result["public_access"] is False


def test_requests_sent_to_platforms_are_correct(make_client):
    client = make_client()
    client.post("/posting", json={"message": VALID_MESSAGE})
    calls = client.fake_handler.calls

    record = next(c for c in calls if c.url.path.endswith("createRecord"))
    payload = json.loads(record.content)["record"]
    assert payload["text"] == VALID_MESSAGE
    assert payload["facets"][0]["features"][0]["uri"] == "https://example.com"

    gist = next(c for c in calls if c.url.host == "api.github.com" and c.method == "POST")
    assert json.loads(gist.content)["public"] is True
    assert gist.headers["authorization"] == "Bearer ghp_secret123"

    discord = next(c for c in calls if c.url.host == "discord.com" and c.method == "POST")
    assert json.loads(discord.content)["allowed_mentions"] == {"parse": []}

    telegram = next(c for c in calls if c.url.host == "api.telegram.org")
    assert json.loads(telegram.content)["chat_id"] == "@dxora_test"


# --------------------------------------------------------------------------
# Helpers and configuration
# --------------------------------------------------------------------------
def test_bluesky_facet_uses_utf8_byte_offsets():
    text = "Café ☕ https://example.com"
    facet = build_link_facet(text, "https://example.com")
    encoded = text.encode("utf-8")
    start, end = facet["index"]["byteStart"], facet["index"]["byteEnd"]
    assert encoded[start:end].decode() == "https://example.com"


def test_devto_title_excludes_link():
    assert build_title(VALID_MESSAGE, "https://example.com") == (
        "Check out our latest business platform and grow your online visibility."
    )
    assert build_title("https://example.com", "https://example.com") == "New update"
    assert len(build_title("word " * 40 + "https://x.com", "https://x.com")) <= 80


def test_enabled_platforms_filter_and_unknown_key():
    assert [p.key for p in get_platforms(make_settings(enabled_platforms="bluesky, devto"))] == [
        "bluesky",
        "devto",
    ]
    assert len(get_platforms(make_settings())) == len(PLATFORM_CLASSES) == 6
    with pytest.raises(ValueError):
        get_platforms(make_settings(enabled_platforms="myspace"))


def test_instance_urls_are_normalized():
    settings = make_settings(mastodon_instance_url="mastodon.social/", bluesky_service_url="")
    assert settings.mastodon_instance_url == "https://mastodon.social"
    assert settings.bluesky_service_url == "https://bsky.social"
    assert make_settings(mastodon_instance_url="  ").mastodon_instance_url is None
    with pytest.raises(ValueError):
        make_settings(mastodon_instance_url="http://insecure.example")


def test_unknown_route_and_wrong_method_use_json_errors(make_client):
    client = make_client()
    not_found = client.get("/nope")
    assert not_found.status_code == 404
    assert not_found.json() == {
        "success": False,
        "error": {"code": "not_found", "message": "Not Found", "details": None},
    }
    wrong_method = client.get("/posting")
    assert wrong_method.status_code == 405
    assert wrong_method.json()["error"]["code"] == "method_not_allowed"


def test_health_and_platforms_endpoints(make_client):
    client = make_client(settings=make_settings(devto_api_key=None))
    assert client.get("/health").json() == {"status": "ok"}
    platforms = client.get("/platforms").json()["platforms"]
    devto = next(p for p in platforms if p["key"] == "devto")
    assert devto["configured"] is False
    assert "secret" not in json.dumps(platforms)
