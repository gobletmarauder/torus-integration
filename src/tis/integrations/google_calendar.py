"""Read-only Google Calendar authentication and incremental event retrieval."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlencode

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from tis.errors import ExternalError
from tis.http import ControlledClient

CALENDAR_SCOPE = "https" + "://www.googleapis.com/auth/calendar.events.readonly"
MAX_TOKEN_LIFETIME_SECONDS = 3600


class SyncTokenGone(ExternalError):
    """Google rejected an expired incremental synchronization token."""


class GooglePerson(BaseModel):
    """Validated attendee, organizer, or creator subset."""

    model_config = ConfigDict(extra="ignore")

    email: str | None = None
    display_name: str | None = Field(default=None, alias="displayName")
    self_: bool = Field(default=False, alias="self")
    organizer: bool = False
    response_status: str | None = Field(default=None, alias="responseStatus")


class GoogleEventTime(BaseModel):
    """Validated timed-event boundary."""

    model_config = ConfigDict(extra="ignore")

    date_time: datetime | None = Field(default=None, alias="dateTime")
    time_zone: str | None = Field(default=None, alias="timeZone")


class GoogleEvent(BaseModel):
    """Validated subset of a Google Calendar event."""

    model_config = ConfigDict(extra="ignore")

    id: str
    status: str = "confirmed"
    summary: str = ""
    description: str = ""
    sequence: int = 0
    updated: datetime | None = None
    start: GoogleEventTime | None = None
    end: GoogleEventTime | None = None
    attendees: list[GooglePerson] = Field(default_factory=list)
    creator: GooglePerson | None = None
    organizer: GooglePerson | None = None


class CalendarEventsResponse(BaseModel):
    """Validated Calendar events.list response envelope."""

    model_config = ConfigDict(extra="ignore")

    items: list[GoogleEvent] = Field(default_factory=list)
    next_page_token: str | None = Field(default=None, alias="nextPageToken")
    next_sync_token: str | None = Field(default=None, alias="nextSyncToken")


class GoogleTokenResponse(BaseModel):
    """Validated OAuth JWT-bearer token response."""

    model_config = ConfigDict(extra="ignore")

    access_token: SecretStr
    expires_in: int = Field(gt=300)


class GoogleCalendarAuth:
    """Create delegated RS256 assertions and cache access tokens in memory."""

    def __init__(
        self,
        *,
        service_account_email: str,
        private_key: str,
        impersonated_user: str,
        token_url: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._service_account_email = service_account_email
        self._private_key = private_key
        self._impersonated_user = impersonated_user
        self._token_url = token_url
        self._clock = clock
        self._cached: tuple[str, datetime] | None = None
        self._lock = asyncio.Lock()

    async def token(self, http: ControlledClient, *, force: bool = False) -> str:
        """Return a cached token or perform one allowlisted token exchange."""
        async with self._lock:
            now = self._utc_now()
            if not force and self._cached and self._cached[1] > now:
                return self._cached[0]
            assertion = self.assertion(now)
            response = await http.request(
                "POST",
                self._token_url,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
            )
            try:
                parsed = GoogleTokenResponse.model_validate(response.json())
            except (ValueError, ValidationError) as error:
                raise ExternalError("Google token response was invalid") from error
            value = parsed.access_token.get_secret_value()
            self._cached = (value, now + timedelta(seconds=parsed.expires_in - 300))
            return value

    def assertion(self, issued_at: datetime | None = None) -> str:
        """Build and sign one short-lived delegated JWT without network I/O."""
        now = (issued_at or self._utc_now()).astimezone(UTC)
        header = {"alg": "RS256", "typ": "JWT"}
        claims = {
            "iss": self._service_account_email,
            "sub": self._impersonated_user,
            "aud": self._token_url,
            "scope": CALENDAR_SCOPE,
            "iat": int(now.timestamp()),
            "exp": int(now.timestamp()) + MAX_TOKEN_LIFETIME_SECONDS,
        }
        signing_input = b".".join((_encode_json(header), _encode_json(claims)))
        try:
            normalized_key = self._private_key.replace("\\n", "\n")
            key = serialization.load_pem_private_key(normalized_key.encode(), password=None)
        except (TypeError, ValueError) as error:
            raise ExternalError("Google service-account private key was invalid") from error
        if not isinstance(key, rsa.RSAPrivateKey):
            raise ExternalError("Google service-account key must be RSA")
        signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        return f"{signing_input.decode()}.{_base64url(signature).decode()}"

    def _utc_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise ExternalError("Google authentication clock must be timezone-aware")
        return now.astimezone(UTC)


class GoogleCalendarClient:
    """Fetch Calendar v3 event pages through the controlled HTTP client."""

    def __init__(
        self,
        *,
        http: ControlledClient,
        auth: GoogleCalendarAuth,
        api_url: str,
        calendar_id: str,
    ) -> None:
        self._http = http
        self._auth = auth
        self._api_url = api_url.rstrip("/")
        self._calendar_id = calendar_id

    async def events_page(
        self,
        *,
        sync_token: str | None,
        page_token: str | None,
        time_min: datetime | None,
    ) -> CalendarEventsResponse:
        """Read one page; this performs only Google OAuth and Calendar GET requests."""
        token = await self._auth.token(self._http)
        refreshed = False
        while True:
            response = await self._http.request(
                "GET",
                self._events_url(
                    sync_token=sync_token,
                    page_token=page_token,
                    time_min=time_min,
                ),
                headers={"Authorization": f"Bearer {token}"},
                accepted_statuses=frozenset({401, 410}),
            )
            if response.status_code == 410:
                raise SyncTokenGone("Google Calendar sync token expired")
            if response.status_code == 401:
                if refreshed:
                    raise ExternalError("Google rejected the refreshed access token")
                token = await self._auth.token(self._http, force=True)
                refreshed = True
                continue
            try:
                return CalendarEventsResponse.model_validate(response.json())
            except (ValueError, ValidationError) as error:
                raise ExternalError("Google Calendar response was invalid") from error

    def _events_url(
        self,
        *,
        sync_token: str | None,
        page_token: str | None,
        time_min: datetime | None,
    ) -> str:
        query: dict[str, str | int] = {
            "maxResults": 250,
            "showDeleted": "true",
            "singleEvents": "true",
        }
        if sync_token:
            query["syncToken"] = sync_token
        elif time_min:
            query["timeMin"] = time_min.astimezone(UTC).isoformat().replace("+00:00", "Z")
            query["orderBy"] = "startTime"
        if page_token:
            query["pageToken"] = page_token
        calendar = quote(self._calendar_id, safe="")
        return f"{self._api_url}/calendar/v3/calendars/{calendar}/events?{urlencode(query)}"


def _base64url(value: bytes) -> bytes:
    return base64.urlsafe_b64encode(value).rstrip(b"=")


def _encode_json(value: dict[str, Any]) -> bytes:
    return _base64url(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())
