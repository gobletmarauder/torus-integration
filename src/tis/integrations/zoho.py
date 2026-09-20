"""Guarded Zoho OAuth caching and CRM Lead upsert."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from tis.errors import ExternalError
from tis.guards import WriteContext, external_write
from tis.http import ControlledClient
from tis.mapping.lead_to_zoho import MappedLead

_ZOHO_STATUSES = frozenset({400, 401, 429, 500, 502, 503, 504})


class ZohoDataError(ExternalError):
    """Zoho rejected a mapped lead as invalid or conflicting."""


class TokenResponse(BaseModel):
    """Validated subset of an OAuth refresh response."""

    model_config = ConfigDict(extra="ignore")

    access_token: SecretStr
    expires_in: int = Field(gt=300)


class UpsertDetails(BaseModel):
    """Validated subset of Zoho result details."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None


class UpsertItem(BaseModel):
    """Validated single-record Zoho upsert result."""

    model_config = ConfigDict(extra="ignore")

    status: str
    code: str
    details: UpsertDetails = Field(default_factory=UpsertDetails)


class UpsertResponse(BaseModel):
    """Validated Zoho upsert response envelope."""

    model_config = ConfigDict(extra="ignore")

    data: list[UpsertItem]


class ZohoAuth:
    """Cache one access token in memory and refresh it five minutes early."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        accounts_url: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._accounts_url = accounts_url.rstrip("/")
        self._clock = clock
        self._cached: tuple[str, float] | None = None
        self._lock = asyncio.Lock()

    async def token(self, http: ControlledClient, *, force: bool = False) -> str:
        """Return a cached token or perform one OAuth refresh request."""
        async with self._lock:
            if not force and self._cached and self._cached[1] > self._clock():
                return self._cached[0]
            response = await http.request(
                "POST",
                f"{self._accounts_url}/oauth/v2/token",
                data={
                    "refresh_token": self._refresh_token,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "refresh_token",
                },
            )
            try:
                token = TokenResponse.model_validate(response.json())
            except (ValueError, ValidationError) as error:
                raise ExternalError("Zoho token response was invalid") from error
            value = token.access_token.get_secret_value()
            self._cached = (value, self._clock() + token.expires_in - 300)
            return value


def _lead_key(lead: MappedLead, *_args: Any, **_kwargs: Any) -> str:
    return str(lead.supabase_lead_id)


@external_write(source="zoho", action="upsert_lead", key=_lead_key)
async def upsert_lead(
    context: WriteContext,
    lead: MappedLead,
    http: ControlledClient,
    auth: ZohoAuth,
    *,
    api_url: str,
    api_version: str = "v8",
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> str:
    """Upsert one Zoho Lead; this performs one guarded external business write."""
    token = await auth.token(http)
    refreshed = False
    for attempt in range(3):
        response = await http.request(
            "POST",
            f"{api_url.rstrip('/')}/crm/{api_version}/Leads/upsert",
            headers={"Authorization": f"Zoho-oauthtoken {token}"},
            json={
                "data": [lead.fields],
                "duplicate_check_fields": [lead.duplicate_field],
                "trigger": ["workflow"],
            },
            accepted_statuses=_ZOHO_STATUSES,
        )
        code = _response_code(response)
        if response.status_code == 401 or code in {"INVALID_TOKEN", "INVALID_OAUTHTOKEN"}:
            if refreshed:
                raise ExternalError("Zoho rejected the refreshed access token")
            token = await auth.token(http, force=True)
            refreshed = True
            continue
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == 2:
                raise ExternalError("Zoho retry budget exhausted")
            await sleep(_retry_delay(response.headers.get("retry-after"), attempt))
            continue
        return _parse_upsert(response.json())
    raise ExternalError("Zoho upsert failed")


def _response_code(response: Any) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    if isinstance(body, dict):
        if isinstance(body.get("code"), str):
            return str(body["code"])
        data = body.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return str(data[0].get("code", ""))
    return ""


def _parse_upsert(body: Any) -> str:
    try:
        parsed = UpsertResponse.model_validate(body)
    except ValidationError as error:
        raise ExternalError("Zoho upsert response was invalid") from error
    if len(parsed.data) != 1:
        raise ExternalError("Zoho upsert response had an unexpected record count")
    item = parsed.data[0]
    if item.status != "success" or not item.details.id:
        if item.code in {"INVALID_DATA", "DUPLICATE_DATA", "MANDATORY_NOT_FOUND"}:
            raise ZohoDataError("Zoho rejected the mapped lead")
        raise ExternalError("Zoho upsert returned an error")
    return item.details.id


def _retry_delay(value: str | None, attempt: int) -> float:
    if value and value.isdigit():
        return float(min(int(value), 5))
    return float(min(0.25 * (2**attempt), 1.0))
