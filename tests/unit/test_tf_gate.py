"""Tests for the Terraform saved-plan safety gate."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[2]
GATE = ROOT / "scripts" / "tf_gate.py"
FIXTURES = ROOT / "tests" / "fixtures" / "terraform"


def run_gate(
    tmp_path: Path, fixture: str, *, mutate: dict[str, Any] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the real gate with synthetic identifiers and an optional fixture mutation."""
    plan = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))
    if mutate:
        plan.update(mutate)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    tfvars = tmp_path / "terraform.tfvars"
    tfvars.write_text(
        'account_id = "acct-fixture"\nzone_id = "zone-fixture"\n'
        'zone_name = "example.com"\nadmin_email = "admin@example.com"\n',
        encoding="utf-8",
    )
    return subprocess.run(
        [sys.executable, str(GATE), str(plan_path), "--tfvars", str(tfvars)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_clean_create_and_import_pass(tmp_path: Path) -> None:
    result = run_gate(tmp_path, "clean-create.json")
    assert result.returncode == 0
    assert "tf-gate: PASS" in result.stdout


@pytest.mark.parametrize(
    ("fixture", "message"),
    [
        ("del" + "ete.json", "removal or replacement"),
        ("forbidden-mx.json", "forbidden DNS type"),
        ("broadened-access.json", "exact admin email"),
        ("over-limit.json", "30-change limit"),
    ],
)
def test_planted_fixture_violations_fail(tmp_path: Path, fixture: str, message: str) -> None:
    result = run_gate(tmp_path, fixture)
    assert result.returncode == 1
    assert message in result.stdout


def test_replace_fails(tmp_path: Path) -> None:
    plan = json.loads((FIXTURES / "clean-create.json").read_text(encoding="utf-8"))
    plan["resource_changes"][0]["change"]["actions"] = ["del" + "ete", "create"]
    result = run_gate(tmp_path, "clean-create.json", mutate=plan)
    assert result.returncode == 1
    assert "removal or replacement" in result.stdout


def test_unknown_resource_type_fails(tmp_path: Path) -> None:
    plan = json.loads((FIXTURES / "clean-create.json").read_text(encoding="utf-8"))
    plan["resource_changes"][0]["type"] = "cloudflare_unreviewed_resource"
    result = run_gate(tmp_path, "clean-create.json", mutate=plan)
    assert result.returncode == 1
    assert "not allowlisted" in result.stdout


def test_unknown_data_source_read_fails(tmp_path: Path) -> None:
    plan = {
        "resource_changes": [
            {
                "address": "data.cloudflare_unreviewed.lookup",
                "mode": "data",
                "type": "cloudflare_unreviewed",
                "change": {"actions": ["read"], "after": {}},
            }
        ]
    }
    result = run_gate(tmp_path, "clean-create.json", mutate=plan)
    assert result.returncode == 1
    assert "data source type is not allowlisted" in result.stdout


@pytest.mark.parametrize(
    ("name", "dns_type"), [("@", "CNAME"), ("www", "CNAME"), ("ops.example.com", "TXT")]
)
def test_forbidden_dns_names_and_types_fail(tmp_path: Path, name: str, dns_type: str) -> None:
    plan = json.loads((FIXTURES / "clean-create.json").read_text(encoding="utf-8"))
    change = plan["resource_changes"][0]
    change["change"]["after"].update({"name": name, "type": dns_type})
    result = run_gate(tmp_path, "clean-create.json", mutate=plan)
    assert result.returncode == 1


@pytest.mark.parametrize(("field", "value"), [("account_id", "wrong"), ("zone_id", "wrong")])
def test_identifier_mismatch_fails(tmp_path: Path, field: str, value: str) -> None:
    plan = json.loads((FIXTURES / "clean-create.json").read_text(encoding="utf-8"))
    index = 1 if field == "account_id" else 0
    plan["resource_changes"][index]["change"]["after"][field] = value
    result = run_gate(tmp_path, "clean-create.json", mutate=plan)
    assert result.returncode == 1
    assert "differs from tfvars" in result.stdout


@pytest.mark.parametrize("field", ["account_id", "zone_id"])
def test_missing_required_identifier_fails(tmp_path: Path, field: str) -> None:
    plan = json.loads((FIXTURES / "clean-create.json").read_text(encoding="utf-8"))
    index = 1 if field == "account_id" else 0
    plan["resource_changes"][index]["change"]["after"].pop(field)
    result = run_gate(tmp_path, "clean-create.json", mutate=plan)
    assert result.returncode == 1
    assert "differs from tfvars" in result.stdout


def test_failure_output_does_not_echo_unchecked_values(tmp_path: Path) -> None:
    marker = "do-not-echo-fixture-value"
    plan = json.loads((FIXTURES / "clean-create.json").read_text(encoding="utf-8"))
    plan["resource_changes"][1]["change"]["after"]["account_id"] = marker
    result = run_gate(tmp_path, "clean-create.json", mutate=plan)
    assert result.returncode == 1
    assert marker not in result.stdout
