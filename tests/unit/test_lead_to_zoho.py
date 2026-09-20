"""Lead-to-Zoho mapping tests with synthetic values only."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from tis.mapping.lead_to_zoho import LeadRow, load_field_map, map_lead

FIELD_MAP = Path(__file__).parents[2] / "config" / "zoho_lead_fields.toml"
LEAD_ID = UUID("00000000-0000-4000-8000-000000000001")


def lead(**updates: object) -> LeadRow:
    values: dict[str, object] = {
        "id": LEAD_ID,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "name": "Ada Example",
        "email": "ada@example.com",
        "company": "Example Co",
        "headcount_band": "51-200",
        "systems_named": "Synthetic CRM",
        "calculator_annual_estimate": Decimal("12000.50"),
        "utm_source": "synthetic",
        "page_path": "/synthetic",
    }
    values.update(updates)
    return LeadRow.model_validate(values)


def test_mapping_uses_only_configured_api_names() -> None:
    mapping = load_field_map(FIELD_MAP)
    mapped = map_lead(lead(), mapping)
    assert mapped.duplicate_field == "supabase_lead_id"
    assert mapped.fields["First_Name"] == "Ada"
    assert mapped.fields["Last_Name"] == "Example"
    assert mapped.fields["Company"] == "Example Co"
    assert mapped.fields["Lead_Source"] == "Website"
    assert "Headcount band: 51-200" in str(mapped.fields["Description"])
    assert "UTM source: synthetic" in str(mapped.fields["Description"])


def test_single_name_and_company_fallback() -> None:
    mapped = map_lead(lead(name="Cher", company=""), load_field_map(FIELD_MAP))
    assert "First_Name" not in mapped.fields
    assert mapped.fields["Last_Name"] == "Cher"
    assert mapped.fields["Company"] == "example.com"


def test_unknown_source_fields_are_not_copied() -> None:
    row = LeadRow.model_validate({**lead().model_dump(), "private_note": "must-not-leave"})
    assert "must-not-leave" not in str(map_lead(row, load_field_map(FIELD_MAP)).fields)


def test_duplicate_api_names_are_rejected(tmp_path: Path) -> None:
    mapping = tmp_path / "map.toml"
    mapping.write_text(
        "[fields]\n"
        'supabase_lead_id="Same"\nfirst_name="Same"\nlast_name="Last_Name"\n'
        'email="Email"\ncompany="Company"\ndescription="Description"\n'
        'lead_source="Lead_Source"\n[values]\nlead_source="Website"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unique"):
        load_field_map(mapping)
