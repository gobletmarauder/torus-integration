"""Cloudflare Access assertion validation tests."""

import base64
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from respx import MockResponse

import tis.http as http_module
from tis.api.access import AccessValidationError, AccessValidator
from tis.http import ControlledClient

DOMAIN = "torusmesh.cloudflareaccess.com"
ISSUER = "https" + f"://{DOMAIN}"
JWKS_URL = ISSUER + "/cdn-cgi/access/certs"
AUDIENCE = "synthetic-audience"


def _b64(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def keys() -> tuple[bytes, dict[str, str]]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    numbers = private.public_key().public_numbers()
    return pem, {
        "kid": "synthetic-kid",
        "kty": "RSA",
        "alg": "RS256",
        "use": "sig",
        "n": _b64(numbers.n),
        "e": _b64(numbers.e),
    }


def token(pem: bytes, **overrides: object) -> str:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "nbf": now - timedelta(seconds=1),
        "exp": now + timedelta(minutes=5),
        "sub": "synthetic-subject",
    }
    claims.update(overrides)
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": "synthetic-kid"})


async def test_valid_assertion_uses_cached_jwks(respx_mock: object) -> None:
    pem, jwk = keys()
    route = respx_mock.get(JWKS_URL).mock(  # type: ignore[attr-defined]
        return_value=MockResponse(200, json={"keys": [jwk]})
    )
    async with ControlledClient() as http:
        validator = AccessValidator(http=http, team_domain=DOMAIN, audience=AUDIENCE)
        first = await validator.validate(token(pem))
        second = await validator.validate(token(pem))
    assert first["sub"] == second["sub"] == "synthetic-subject"
    assert route.call_count == 1


async def test_wrong_audience_and_algorithm_fail_closed(respx_mock: object) -> None:
    pem, jwk = keys()
    respx_mock.get(JWKS_URL).mock(  # type: ignore[attr-defined]
        return_value=MockResponse(200, json={"keys": [jwk]})
    )
    async with ControlledClient() as http:
        validator = AccessValidator(http=http, team_domain=DOMAIN, audience=AUDIENCE)
        with pytest.raises(AccessValidationError, match="claims"):
            await validator.validate(token(pem, aud="wrong"))
        unsafe = jwt.encode(
            {"exp": datetime.now(UTC) + timedelta(minutes=1)},
            "synthetic-secret-with-safe-test-length",
            algorithm="HS256",
            headers={"kid": "synthetic-kid"},
        )
        with pytest.raises(AccessValidationError, match="algorithm"):
            await validator.validate(unsafe)


async def test_expiry_not_before_and_signature_fail_closed(respx_mock: object) -> None:
    pem, jwk = keys()
    other_pem, _ = keys()
    respx_mock.get(JWKS_URL).mock(  # type: ignore[attr-defined]
        return_value=MockResponse(200, json={"keys": [jwk]})
    )
    now = datetime.now(UTC)
    async with ControlledClient() as http:
        validator = AccessValidator(http=http, team_domain=DOMAIN, audience=AUDIENCE)
        with pytest.raises(AccessValidationError, match="claims"):
            await validator.validate(token(pem, exp=now - timedelta(minutes=1)))
        with pytest.raises(AccessValidationError, match="claims"):
            await validator.validate(token(pem, nbf=now + timedelta(minutes=2)))
        with pytest.raises(AccessValidationError, match="claims"):
            await validator.validate(token(other_pem))


async def test_unknown_key_refreshes_once_then_denies(respx_mock: object) -> None:
    pem, jwk = keys()
    route = respx_mock.get(JWKS_URL).mock(  # type: ignore[attr-defined]
        return_value=MockResponse(200, json={"keys": [{**jwk, "kid": "other"}]})
    )
    async with ControlledClient() as http:
        validator = AccessValidator(http=http, team_domain=DOMAIN, audience=AUDIENCE)
        with pytest.raises(AccessValidationError, match="unknown"):
            await validator.validate(token(pem))
    assert route.call_count == 2


async def test_malformed_assertion_and_jwks_are_typed(respx_mock: object) -> None:
    async with ControlledClient() as http:
        validator = AccessValidator(http=http, team_domain=DOMAIN, audience=AUDIENCE)
        with pytest.raises(AccessValidationError, match="header"):
            await validator.validate("not-a-token")
    pem, _ = keys()
    respx_mock.get(JWKS_URL).mock(return_value=MockResponse(200, json={"keys": []}))  # type: ignore[attr-defined]
    async with ControlledClient() as http:
        validator = AccessValidator(http=http, team_domain=DOMAIN, audience=AUDIENCE)
        with pytest.raises(AccessValidationError, match="signing keys"):
            await validator.validate(token(pem))


async def test_jwks_transport_failure_is_generic_access_denial(respx_mock: object) -> None:
    pem, _ = keys()
    respx_mock.get(JWKS_URL).mock(  # type: ignore[attr-defined]
        side_effect=http_module.httpx.ConnectError("synthetic")
    )

    async def no_sleep(_delay: float) -> None:
        return None

    async with ControlledClient(sleep=no_sleep) as http:
        validator = AccessValidator(http=http, team_domain=DOMAIN, audience=AUDIENCE)
        with pytest.raises(AccessValidationError, match="unavailable"):
            await validator.validate(token(pem))
