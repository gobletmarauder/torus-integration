"""The only permitted outbound HTTP client and its exact egress allowlist."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from tis.errors import EgressDenied, ExternalError
from tis.log import get_logger, redact

EGRESS_ALLOWLIST: frozenset[str] = frozenset(
    {
        "accounts.zoho.com",
        "uptime.betterstack.com",
        "us.i.posthog.com",
        "www.zohoapis.com",
    }
)
DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_REDIRECTS = 5
MAX_ATTEMPTS = 3
_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_SENSITIVE_QUERY_KEYS = frozenset({"token", "code", "refresh_token", "api_key"})
_LOG = get_logger("http")


def _safe_url(url: httpx.URL) -> str:
    parts = urlsplit(str(url))
    query = urlencode(
        [
            (key, "[REDACTED]" if key.lower() in _SENSITIVE_QUERY_KEYS else value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
        ]
    )
    safe_path = "/[REDACTED]" if parts.path not in {"", "/"} else parts.path
    return urlunsplit((parts.scheme, parts.netloc, safe_path, query, ""))


class ControlledClient:
    """Enforce allowlisted hosts, bounded redirects, retries, timeout, and safe logs."""

    def __init__(
        self,
        *,
        allowlist: frozenset[str] = EGRESS_ALLOWLIST,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._allowlist = allowlist
        self._sleep = sleep
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            transport=transport,
        )

    async def __aenter__(self) -> ControlledClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close pooled HTTP connections without issuing a request."""
        await self._client.aclose()

    def _check_url(self, url: str | httpx.URL) -> httpx.URL:
        parsed = httpx.URL(url)
        host = (parsed.host or "").lower().rstrip(".")
        if parsed.scheme != "https" or host not in self._allowlist:
            raise EgressDenied("outbound host is not allowlisted")
        return parsed

    async def request(
        self,
        method: str,
        url: str | httpx.URL,
        *,
        headers: Mapping[str, str] | None = None,
        json: Any = None,
        data: Mapping[str, str] | None = None,
        accepted_statuses: frozenset[int] = frozenset(),
    ) -> httpx.Response:
        """Send an allowlisted request; this performs outbound network I/O."""
        normalized_method = method.upper()
        current_url = self._check_url(url)
        redirects = 0
        while True:
            response = await self._request_with_retry(
                normalized_method,
                current_url,
                headers=headers,
                json=json,
                data=data,
            )
            if response.status_code not in _REDIRECT_STATUSES:
                if response.status_code >= 400 and response.status_code not in accepted_statuses:
                    raise ExternalError(f"external service returned HTTP {response.status_code}")
                return response
            location = response.headers.get("location")
            if not location or redirects >= MAX_REDIRECTS:
                raise ExternalError("external redirect limit or location failure")
            current_url = self._check_url(response.url.join(location))
            redirects += 1
            if response.status_code == 303:
                normalized_method, json, data = "GET", None, None

    async def _request_with_retry(
        self,
        method: str,
        url: httpx.URL,
        *,
        headers: Mapping[str, str] | None,
        json: Any,
        data: Mapping[str, str] | None,
    ) -> httpx.Response:
        attempts = MAX_ATTEMPTS if method in _IDEMPOTENT_METHODS else 1
        for attempt in range(attempts):
            try:
                _LOG.info(
                    "http_request",
                    extra={
                        "fields": {
                            "method": method,
                            "url": _safe_url(url),
                            "headers": redact(dict(headers or {})),
                        }
                    },
                )
                response = await self._client.request(
                    method, url, headers=headers, json=json, data=data
                )
            except httpx.HTTPError as error:
                if attempt + 1 == attempts:
                    raise ExternalError("external request failed") from error
            else:
                if response.status_code != 429 and response.status_code < 500:
                    return response
                if attempt + 1 == attempts:
                    return response
            await self._sleep(min(0.25 * (2**attempt), 1.0))
        raise ExternalError("external request failed")


def client(**kwargs: Any) -> ControlledClient:
    """Construct the controlled HTTP client without issuing a request."""
    return ControlledClient(**kwargs)
