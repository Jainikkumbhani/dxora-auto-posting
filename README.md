# Automated Multi-Platform Posting API

A FastAPI service that publishes a short message (max 200 characters, exactly one CTA link)
to **6 third-party platforms** through their **official APIs**, posting to all of them
concurrently and reporting a result for each platform.

| | |
|---|---|
| Endpoint | `POST http://localhost:4000/posting` |
| API docs (Swagger) | `http://localhost:4000/docs` |
| Stack | Python 3.10+ (tested on 3.12), FastAPI, Uvicorn, Pydantic v2, HTTPX |
| Platforms | Bluesky, Mastodon, Telegram, GitHub Gist, DEV Community, Discord |

---

## 1. Features

- **One endpoint** - `POST /posting` with body `{"message": "..."}`.
- **Input validation** (HTTP 422 with a clear reason):
  - message must not be empty and must not exceed **200 characters**;
  - message must contain **exactly one** CTA link (0 or 2+ links are rejected);
  - the link must be a valid `http(s)` URL with a real domain - no `localhost`, private/internal
    IPs, embedded credentials, or invalid ports.
- **Platform selection is internal** - the client never chooses platforms; the app posts to
  every platform in its registry (optionally narrowed by the `ENABLED_PLATFORMS` env variable).
- **Independent, concurrent posting** - all platforms run in parallel with `asyncio.gather`.
  Each has its own timeout and error handling, so **one failure never stops the others**.
- **Honest `public_access`** - after posting, the app re-reads each post **anonymously (no
  credentials)** through a public endpoint. It is `true` only if that check succeeds.
- **Real timestamps** - `date` / `time` are taken at the moment the platform confirmed the post
  (timezone configurable, default `Asia/Kolkata`).
- **Security** - credentials only from environment variables (`SecretStr`), secrets redacted from
  every error message, HTTPX request logging silenced (Telegram URLs contain the bot token),
  Discord `@everyone`/role pings disabled, no automatic retries of non-idempotent posts.
- **Dependencies** - exact versions pinned in `requirements.txt` and scanned with `pip-audit`:
  no known vulnerabilities (2026-11-20).

---

## 2. Platform research

Selection criteria: an **official, documented, free** API; text posting allowed for personal
accounts without app review; a stable public URL for the created post; and a way to verify
public access anonymously.

| # | Platform | Official API used | Auth | Posted URL | Public access check (anonymous) |
|---|---|---|---|---|---|
| 1 | **Bluesky** | AT Protocol `com.atproto.repo.createRecord` ([docs](https://docs.bsky.app/docs/advanced-guides/posts)) | Handle + App Password | `bsky.app/profile/<handle>/post/<id>` | `public.api.bsky.app` `getPosts` |
| 2 | **Mastodon** | `POST /api/v1/statuses` ([docs](https://docs.joinmastodon.org/methods/statuses/#create)) | Bearer access token | status `url` from response | `GET /api/v1/statuses/:id` → `visibility == public` |
| 3 | **Telegram** | Bot API `sendMessage` to a public channel ([docs](https://core.telegram.org/bots/api#sendmessage)) | Bot token | `t.me/<channel>/<message_id>` | public embed widget `t.me/...?embed=1` |
| 4 | **GitHub Gist** | `POST /gists` with `public: true` ([docs](https://docs.github.com/en/rest/gists/gists#create-a-gist)) | Fine-grained PAT | gist `html_url` | `GET /gists/:id` without token → `public == true` |
| 5 | **DEV Community** | Forem API v1 `POST /api/articles` ([docs](https://developers.forem.com/api/v1#tag/articles/operation/createArticle)) | API key | article `url` | `GET /api/articles/:id` without key |
| 6 | **Discord** | Execute Webhook `?wait=true` ([docs](https://discord.com/developers/docs/resources/webhook#execute-webhook)) | Webhook URL | `discord.com/channels/<guild>/<channel>/<msg>` | Always `false` - server messages need login + membership |

### Platform-specific details handled

- **Bluesky** does not auto-link URLs; the app adds a *link facet* with **UTF-8 byte offsets**
  so the CTA link is clickable (tested with multi-byte characters).
- **Mastodon** - an `Idempotency-Key` header prevents duplicate posts if a request is re-sent.
- **Telegram** - only public channels have a public URL; a private chat returns a clear error.
- **DEV Community** articles need a title - it is generated from the message text without the link.
- **Discord** is intentionally included to show honest reporting of `public_access: false`.

### Platforms considered but not used

| Platform | Reason |
|---|---|
| X (Twitter) | Write access on the API is a paid / usage-billed tier. |
| LinkedIn | Requires a LinkedIn app, a 3-legged OAuth flow, and tokens that expire; not suitable for a server-side demo. |
| Facebook / Instagram | Require a Meta app, Page/Business account and long-lived tokens; Instagram cannot publish text-only posts. |
| Reddit | API access requires approval, and cross-posting the same promotional link is treated as spam. |
| Medium | Stopped issuing new API integration tokens. |
| "LLM platforms" | The brief mentions them, but mainstream LLM providers (OpenAI, Gemini, Anthropic) have no public posting/publishing API, so there is nothing to publish to. |

> Note: platform API policies change often. The links above point to the official
> documentation that the integrations were written against.

---

## 3. Project structure

```text
dxora-auto-posting/
├── app/
│   ├── main.py                 # FastAPI app, routes, error handlers, logging
│   ├── config.py               # Settings from environment variables (.env)
│   ├── schemas.py              # Pydantic request/response models + validation
│   ├── platforms/
│   │   ├── __init__.py         # Platform registry (internal platform selection)
│   │   ├── base.py             # BasePlatform interface + shared error handling
│   │   ├── bluesky.py
│   │   ├── mastodon.py
│   │   ├── telegram.py
│   │   ├── github_gist.py
│   │   ├── devto.py
│   │   └── discord.py
│   ├── services/
│   │   └── posting_service.py  # Concurrent posting, timeouts, result building
│   └── utils/
│       └── validators.py       # Message + CTA link validation
├── tests/
│   └── test_posting.py         # 36 tests, all platform APIs mocked
├── docs/screenshots/           # Screenshots of the running API
├── .env.example
├── requirements.txt
└── README.md
```

Adding a new platform = one new file that subclasses `BasePlatform` (`missing_settings`,
`publish`, `check_public_access`) plus one line in `app/platforms/__init__.py`.

---

## 4. Setup and run

```bash
git clone <your-repo-url>
cd dxora-auto-posting

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # then fill in your own credentials

uvicorn app.main:app --host 0.0.0.0 --port 4000
```

Open **http://localhost:4000/docs** to try the API from the browser.
`GET /platforms` shows which platforms are configured (never the credential values).

### Getting credentials

| Platform | Steps |
|---|---|
| Bluesky | Create an account → Settings → Privacy and security → **App passwords** → Add. Set `BLUESKY_HANDLE` and `BLUESKY_APP_PASSWORD`. |
| Mastodon | Create an account (e.g. mastodon.social) → Preferences → Development → **New application**, scope `write:statuses` → copy *Your access token*. Set `MASTODON_INSTANCE_URL` and `MASTODON_ACCESS_TOKEN`. |
| Telegram | Message **@BotFather** → `/newbot` → copy token. Create a **public** channel with a username, add the bot as **admin**. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_USERNAME`. |
| GitHub Gist | GitHub → Settings → Developer settings → **Fine-grained tokens** → Account permissions → *Gists: Read and write*. Set `GITHUB_TOKEN`. |
| DEV Community | https://dev.to/settings/extensions → **DEV Community API Keys** → Generate. Set `DEVTO_API_KEY`. |
| Discord | Your server → channel settings → Integrations → **Webhooks** → New Webhook → Copy URL. Set `DISCORD_WEBHOOK_URL`. |

Any platform without credentials is still reported in the response as
`failed` with `"Platform not configured: missing ..."` - the others continue normally.

---

## 5. API usage

### Request

```bash
curl -X POST http://localhost:4000/posting \
  -H "Content-Type: application/json" \
  -d '{"message": "Check out our latest business platform and grow your online visibility. https://example.com"}'
```

### Response fields (per platform)

| Field | Description |
|---|---|
| `platform` | Platform name |
| `status` | `success` / `failed` |
| `posted_url` | URL of the published post (`null` on failure) |
| `public_access` | `true` only if the post was verified readable without credentials |
| `date` | Posting date `YYYY-MM-DD` (`null` on failure) |
| `time` | Posting time `HH:MM:SS` (`null` on failure) |
| `error` | Error details, `null` on success |

Top level: `success` is `true` when **at least one** platform succeeded. A `summary` object
(`total`, `succeeded`, `failed`, `timezone`) is added for convenience.

### Validation error example (HTTP 422) - real output

```json
{
  "success": false,
  "error": {
    "code": "validation_error",
    "message": "Message must contain exactly one CTA link (found 2).",
    "details": [
      { "field": "message", "message": "Message must contain exactly one CTA link (found 2)." }
    ]
  }
}
```

### Validation rules and messages

| Input | Result |
|---|---|
| Empty / whitespace | `Message must not be empty.` |
| More than 200 characters | `Message must not exceed 200 characters (got N).` |
| No link | `Message must contain exactly one CTA link (found none).` |
| Two or more links | `Message must contain exactly one CTA link (found N).` |
| `www.example.com` (no scheme) | `CTA link must start with http:// or https://.` |
| `http://localhost`, `http://192.168.x.x` | `CTA link must point to a public website.` / `...private or internal address.` |
| `https://user:pass@site.com` | `CTA link must not contain a username or password.` |
| `https://example` | `CTA link must contain a valid domain, e.g. https://example.com.` |

### Partial failure example (from the test suite, APIs mocked)

```json
{
  "platform": "Mastodon",
  "status": "failed",
  "posted_url": null,
  "public_access": false,
  "date": null,
  "time": null,
  "error": "Mastodon post failed: HTTP 401 - Authentication failed: The access token is invalid"
}
```

---

## 6. Tests

```bash
pip install pytest
pytest -q
```

36 tests. No network access and no real credentials needed - every platform API is simulated
with `httpx.MockTransport`. Covered:

- all validation rules (length limit incl. exactly 200 chars, 0/2 links, bad / private URLs,
  wrong types, malformed JSON, missing field);
- successful posting to all 6 platforms and the exact response shape;
- one/several platforms failing (401, 500) while others succeed;
- unconfigured platform is reported and never called;
- all platforms failing → `success: false`; network errors; per-platform timeout;
- public-access check failing → `public_access: false`;
- secrets never appear in responses (redaction);
- correct payloads (Bluesky facet byte offsets, public gist, Discord mentions disabled);
- instance URL normalisation; JSON error format for unknown routes (404) and wrong methods (405).

### Screenshots

| Swagger UI | Validation error (2 links) |
|---|---|
| ![docs](docs/screenshots/01-swagger-docs.png) | ![422](docs/screenshots/03-validation-two-links.png) |

---

## 7. Design decisions and assumptions

- **Top-level `success`** = at least one platform succeeded; HTTP status is `200` whenever the
  request was valid, because per-platform outcomes are reported in `results`.
- **Character count** uses Python `len()` (Unicode code points) after trimming whitespace.
- **CTA link detection** counts `http://`, `https://` and `www.` tokens; trailing sentence
  punctuation (`.`, `,`, `)` ...) is not treated as part of the link.
- **No automatic retries** - creating a post is not idempotent; retrying could publish twice.
- **`public_access` is verified, never assumed** - if the anonymous check fails or times out
  the value is `false`.
- **Date/time** are recorded when the platform confirms the post, in `APP_TIMEZONE`.
- Use test accounts/channels and a non-spam message when trying the API: posting identical
  promotional links to many sites can violate platform rules.
