"""URL sanitising for links that come from third parties (marketplaces, affiliate APIs)."""
from urllib.parse import urlsplit

MAX_URL_LENGTH = 2048


class UnsafeUrlError(ValueError):
    """A URL that must not be stored or rendered as a link."""


def safe_http_url(value: str | None) -> str | None:
    """Return the URL if it is a plain http(s) URL, else ``None``.

    Blocks ``javascript:``, ``data:``, ``file:`` and similar schemes, which would become script
    execution if a provider-supplied value were rendered as a link, plus control characters,
    embedded credentials and over-long values.
    """
    if not value:
        return None
    url = value.strip()
    if len(url) > MAX_URL_LENGTH or any(ord(c) < 0x21 or ord(c) == 0x7F for c in url):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        return None
    return url


def require_http_url(value: str | None, what: str) -> str:
    cleaned = safe_http_url(value)
    if cleaned is None:
        raise UnsafeUrlError(f"{what} is not a valid http(s) URL")
    return cleaned
