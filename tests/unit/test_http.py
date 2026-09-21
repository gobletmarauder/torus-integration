"""Controlled HTTP behavior tests."""

import pytest
from respx import MockResponse

import tis.http as http_module
from tis.errors import EgressDenied, ExternalError
from tis.http import DEFAULT_TIMEOUT_SECONDS, EGRESS_ALLOWLIST, ControlledClient, _safe_url

TEST_HOSTS = frozenset({"allowed.example"})


def url(host: str, path: str) -> str:
    return f"https://{host}{path}"


async def test_allowed_request_and_default_timeout(respx_mock: object) -> None:
    route = respx_mock.get(url("allowed.example", "/value")).mock(  # type: ignore[attr-defined]
        return_value=MockResponse(200)
    )
    async with ControlledClient(allowlist=TEST_HOSTS) as http:
        response = await http.request("GET", url("allowed.example", "/value"))
        timeout = http._client.timeout  # noqa: SLF001 - verifies the safety default
    assert response.status_code == 200
    assert timeout.read == DEFAULT_TIMEOUT_SECONDS
    assert route.called


async def test_denied_host_never_sends() -> None:
    async with ControlledClient(allowlist=TEST_HOSTS) as http:
        with pytest.raises(EgressDenied):
            await http.request("GET", url("denied.example", "/value"))


async def test_redirect_escape_is_rejected(respx_mock: object) -> None:
    route = respx_mock.get(url("allowed.example", "/start")).mock(  # type: ignore[attr-defined]
        return_value=MockResponse(302, headers={"location": url("denied.example", "/end")})
    )
    async with ControlledClient(allowlist=TEST_HOSTS) as http:
        with pytest.raises(EgressDenied):
            await http.request("GET", url("allowed.example", "/start"))
    assert route.call_count == 1


async def test_idempotent_request_retries_bounded_statuses(respx_mock: object) -> None:
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    route = respx_mock.get(url("allowed.example", "/retry")).mock(  # type: ignore[attr-defined]
        side_effect=[MockResponse(500), MockResponse(429), MockResponse(200)]
    )
    async with ControlledClient(allowlist=TEST_HOSTS, sleep=sleep) as http:
        response = await http.request("GET", url("allowed.example", "/retry"))
    assert response.status_code == 200
    assert route.call_count == 3
    assert sleeps == [0.25, 0.5]


async def test_unsafe_request_is_not_retried(respx_mock: object) -> None:
    route = respx_mock.post(url("allowed.example", "/write")).mock(  # type: ignore[attr-defined]
        return_value=MockResponse(500)
    )
    async with ControlledClient(allowlist=TEST_HOSTS) as http:
        with pytest.raises(ExternalError, match="HTTP 500"):
            await http.request("POST", url("allowed.example", "/write"), json={"message": "secret"})
    assert route.call_count == 1


async def test_form_body_and_explicit_error_status_are_returned_without_retry(
    respx_mock: object,
) -> None:
    route = respx_mock.post(url("allowed.example", "/form")).mock(  # type: ignore[attr-defined]
        return_value=MockResponse(400, json={"code": "synthetic"})
    )
    async with ControlledClient(allowlist=TEST_HOSTS) as http:
        response = await http.request(
            "POST",
            url("allowed.example", "/form"),
            data={"credential": "synthetic"},
            accepted_statuses=frozenset({400}),
        )
    assert response.status_code == 400
    assert route.call_count == 1


async def test_transport_failure_becomes_typed_error(respx_mock: object) -> None:
    route = respx_mock.get(url("allowed.example", "/fail")).mock(  # type: ignore[attr-defined]
        side_effect=http_module.httpx.ConnectError("synthetic")
    )
    async with ControlledClient(allowlist=TEST_HOSTS, sleep=_no_sleep) as http:
        with pytest.raises(ExternalError, match="external request failed"):
            await http.request("GET", url("allowed.example", "/fail"))
    assert route.call_count == 3


async def _no_sleep(_delay: float) -> None:
    return None


def test_google_hosts_are_exact_and_sensitive_query_values_are_redacted() -> None:
    assert {"oauth2.googleapis.com", "www.googleapis.com"} <= EGRESS_ALLOWLIST
    google_url = "https" + "://www.googleapis.com/calendar/v3/events"
    safe = _safe_url(http_module.httpx.URL(google_url + "?syncToken=opaque&pageToken=next&email=x"))
    assert "opaque" not in safe and "next" not in safe and "email=x" not in safe


def test_cloudflare_access_host_is_exact() -> None:
    assert "torusmesh.cloudflareaccess.com" in EGRESS_ALLOWLIST
    assert not any(host.startswith("*.") for host in EGRESS_ALLOWLIST)
