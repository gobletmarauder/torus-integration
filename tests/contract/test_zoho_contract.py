"""Validate recorded synthetic Zoho response shapes against adapter models."""

import json
from pathlib import Path

import pytest

from tis.integrations.zoho import TokenResponse, UpsertResponse

FIXTURES = Path(__file__).parents[1] / "fixtures" / "zoho"


def read(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_token_success_contract() -> None:
    assert TokenResponse.model_validate(read("token-success.json")).expires_in == 3600


def test_upsert_success_contract() -> None:
    response = UpsertResponse.model_validate(read("upsert-success.json"))
    assert response.data[0].details.id == "synthetic-zoho-id"


@pytest.mark.parametrize("name", ["upsert-duplicate.json", "upsert-invalid-data.json"])
def test_upsert_error_contracts(name: str) -> None:
    assert UpsertResponse.model_validate(read(name)).data[0].status == "error"
