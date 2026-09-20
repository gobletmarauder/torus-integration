"""Manual Google JWT and controlled Calendar client tests."""

import asyncio
import base64
import json
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from respx import MockResponse

from tis.errors import ExternalError
from tis.http import ControlledClient
from tis.integrations.google_calendar import (
    CALENDAR_SCOPE,
    GoogleCalendarAuth,
    GoogleCalendarClient,
    SyncTokenGone,
)

TOKEN = "https" + "://oauth2.googleapis.com/token"
API = "https" + "://www.googleapis.com"
NOW = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)


def key_pair() -> tuple[str, rsa.RSAPrivateKey]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return pem, key


def auth(private_key: str) -> GoogleCalendarAuth:
    return GoogleCalendarAuth(
        service_account_email="calendar-reader@example.invalid",
        private_key=private_key,
        impersonated_user="calendar-owner@example.invalid",
        token_url=TOKEN,
        clock=lambda: NOW,
    )


def decode(segment: str) -> dict[str, object]:
    padded = segment + "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def test_assertion_has_exact_delegated_claims_and_valid_signature() -> None:
    pem, key = key_pair()
    assertion = auth(pem).assertion()
    header, claims, signature = assertion.split(".")
    assert decode(header) == {"alg": "RS256", "typ": "JWT"}
    assert decode(claims) == {
        "aud": TOKEN,
        "exp": int(NOW.timestamp()) + 3600,
        "iat": int(NOW.timestamp()),
        "iss": "calendar-reader@example.invalid",
        "scope": CALENDAR_SCOPE,
        "sub": "calendar-owner@example.invalid",
    }
    key.public_key().verify(
        base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)),
        f"{header}.{claims}".encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


async def test_token_exchange_is_cached_and_concurrency_safe(respx_mock: object) -> None:
    pem, _ = key_pair()
    route = respx_mock.post(TOKEN).mock(  # type: ignore[attr-defined]
        return_value=MockResponse(200, json={"access_token": "synthetic", "expires_in": 3600})
    )
    google = auth(pem)
    async with ControlledClient() as http:
        values = await asyncio.gather(google.token(http), google.token(http))
    assert values == ["synthetic", "synthetic"]
    assert route.call_count == 1


async def test_calendar_refreshes_once_and_reports_gone_token(respx_mock: object) -> None:
    pem, _ = key_pair()
    respx_mock.post(TOKEN).mock(  # type: ignore[attr-defined]
        return_value=MockResponse(200, json={"access_token": "synthetic", "expires_in": 3600})
    )
    events_pattern = r"https" + r"://www\.googleapis\.com/calendar/.*"
    events = respx_mock.get(url__regex=events_pattern).mock(  # type: ignore[attr-defined]
        side_effect=[MockResponse(401), MockResponse(410)]
    )
    client = GoogleCalendarClient(
        http=ControlledClient(), auth=auth(pem), api_url=API, calendar_id="calendar@example.invalid"
    )
    synthetic_cursor = "opaque"
    async with client._http:  # noqa: SLF001 - owns the test client
        with pytest.raises(SyncTokenGone):
            await client.events_page(sync_token=synthetic_cursor, page_token=None, time_min=None)
    assert events.call_count == 2


def test_invalid_private_key_is_typed() -> None:
    with pytest.raises(ExternalError, match="private key"):
        auth("not-a-key").assertion()
