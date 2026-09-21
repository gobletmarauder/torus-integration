"""Cloudflare Access JWT validation with bounded JWKS caching."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from typing import Any

import jwt
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tis.errors import ExternalError
from tis.http import ControlledClient

JWKS_CACHE_SECONDS = 300.0
JWT_LEEWAY_SECONDS = 30


class AccessValidationError(ExternalError):
    """A Cloudflare Access assertion failed closed."""


class Jwk(BaseModel):
    """Validated RSA signing-key subset returned by Cloudflare Access."""

    model_config = ConfigDict(extra="ignore")

    kid: str
    kty: str
    alg: str = "RS256"
    use: str = "sig"
    n: str
    e: str


class Jwks(BaseModel):
    """Validated Cloudflare signing-key response."""

    model_config = ConfigDict(extra="ignore")

    keys: list[Jwk] = Field(min_length=1)


class AccessValidator:
    """Fetch, cache, and validate exact-team Cloudflare Access assertions."""

    def __init__(
        self,
        *,
        http: ControlledClient,
        team_domain: str,
        audience: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http
        self._team_domain = team_domain.lower().rstrip(".")
        self._audience = audience
        self._clock = clock
        self._cached: tuple[float, dict[str, Jwk]] | None = None
        self._lock = asyncio.Lock()

    async def validate(self, assertion: str) -> Mapping[str, Any]:
        """Validate one assertion, refreshing JWKS once for an unknown key id."""
        try:
            header = jwt.get_unverified_header(assertion)
        except jwt.PyJWTError as error:
            raise AccessValidationError("Access assertion header was invalid") from error
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise AccessValidationError("Access assertion algorithm or key id was invalid")
        kid = str(header["kid"])
        keys = await self._keys()
        key = keys.get(kid)
        if key is None:
            keys = await self._keys(force=True)
            key = keys.get(kid)
        if key is None:
            raise AccessValidationError("Access assertion signing key was unknown")
        try:
            signing_key = jwt.PyJWK.from_dict(key.model_dump()).key
            claims = jwt.decode(
                assertion,
                key=signing_key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                leeway=JWT_LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "iss", "aud"]},
            )
        except (jwt.PyJWTError, ValueError) as error:
            raise AccessValidationError("Access assertion claims were invalid") from error
        return claims

    @property
    def _issuer(self) -> str:
        return "https" + "://" + self._team_domain

    async def _keys(self, *, force: bool = False) -> dict[str, Jwk]:
        async with self._lock:
            now = self._clock()
            if not force and self._cached and now - self._cached[0] < JWKS_CACHE_SECONDS:
                return self._cached[1]
            try:
                response = await self._http.request("GET", f"{self._issuer}/cdn-cgi/access/certs")
            except ExternalError as error:
                raise AccessValidationError("Access signing keys were unavailable") from error
            try:
                document = Jwks.model_validate(response.json())
            except (ValueError, ValidationError) as error:
                raise AccessValidationError("Access signing keys were invalid") from error
            keys = {
                key.kid: key for key in document.keys if key.kty == "RSA" and key.alg == "RS256"
            }
            if not keys:
                raise AccessValidationError("Access signing keys contained no approved RSA key")
            self._cached = (now, keys)
            return keys
