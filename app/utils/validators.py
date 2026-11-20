"""Message and CTA-link validation helpers."""

import ipaddress
import re
from typing import List
from urllib.parse import urlsplit

MAX_MESSAGE_LENGTH = 200
MAX_URL_LENGTH = 2048

# Anything that looks like a link: explicit scheme or a bare "www." prefix.
_LINK_PATTERN = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
# Punctuation that commonly follows a link in a sentence but is not part of it.
_TRAILING_PUNCTUATION = ".,!?;:'\")]}"
# A single DNS label (RFC 1123), max 63 chars, no leading/trailing hyphen.
_LABEL_PATTERN = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$", re.IGNORECASE)
# TLD: alphabetic (2+ chars) or an IDN punycode TLD.
_TLD_PATTERN = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$", re.IGNORECASE)


class LinkValidationError(ValueError):
    """Raised when the CTA link inside a message is missing or invalid."""


def find_links(message: str) -> List[str]:
    """Return every link-like token in the message, trailing punctuation removed."""
    return [match.rstrip(_TRAILING_PUNCTUATION) for match in _LINK_PATTERN.findall(message)]


def validate_cta_url(url: str) -> str:
    """Validate a CTA URL and return it unchanged when valid.

    Rules: http/https only, a real public domain name (or public IP), no
    embedded credentials, no localhost / private network targets.
    """
    if len(url) > MAX_URL_LENGTH:
        raise LinkValidationError("CTA link is too long.")
    if url.lower().startswith("www."):
        raise LinkValidationError("CTA link must start with http:// or https://.")

    try:
        parts = urlsplit(url)
        port = parts.port  # raises ValueError for an invalid port
    except ValueError as exc:
        raise LinkValidationError("CTA link is not a valid URL.") from exc

    if parts.scheme.lower() not in ("http", "https"):
        raise LinkValidationError("CTA link must use http or https.")
    if parts.username or parts.password:
        raise LinkValidationError("CTA link must not contain a username or password.")
    if port is not None and not 0 < port < 65536:
        raise LinkValidationError("CTA link has an invalid port.")

    host = (parts.hostname or "").rstrip(".")
    if not host:
        raise LinkValidationError("CTA link must contain a domain name.")

    # Public IP literals are allowed; private / internal addresses are not.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if not ip.is_global:
            raise LinkValidationError("CTA link must not point to a private or internal address.")
        return url

    if host.lower() == "localhost" or host.lower().endswith((".localhost", ".local", ".internal")):
        raise LinkValidationError("CTA link must point to a public website.")

    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise LinkValidationError("CTA link has an invalid domain name.") from exc

    labels = ascii_host.split(".")
    if len(labels) < 2 or not _TLD_PATTERN.match(labels[-1]):
        raise LinkValidationError("CTA link must contain a valid domain, e.g. https://example.com.")
    if not all(_LABEL_PATTERN.match(label) for label in labels):
        raise LinkValidationError("CTA link has an invalid domain name.")
    return url


def extract_single_cta_link(message: str) -> str:
    """Ensure the message contains exactly one valid CTA link and return it."""
    links = find_links(message)
    if not links:
        raise LinkValidationError("Message must contain exactly one CTA link (found none).")
    if len(links) > 1:
        raise LinkValidationError(
            f"Message must contain exactly one CTA link (found {len(links)})."
        )
    return validate_cta_url(links[0])
