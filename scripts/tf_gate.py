#!/usr/bin/env python3
"""Fail closed on unsafe Cloudflare Terraform plans without printing plan values."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ALLOWED_RESOURCES = frozenset(
    {
        "cloudflare_zero_trust_tunnel_cloudflared",
        "cloudflare_zero_trust_tunnel_cloudflared_config",
        "cloudflare_dns_record",
        "cloudflare_zero_trust_access_application",
        "cloudflare_zero_trust_access_policy",
        "cloudflare_turnstile_widget",
        "cloudflare_r2_bucket",
        "cloudflare_zone_setting",
        "cloudflare_ruleset",
        "cloudflare_workers_custom_domain",
    }
)
ALLOWED_DATA_SOURCES = frozenset({"cloudflare_zero_trust_tunnel_cloudflared_token"})
ACCOUNT_SCOPED_TYPES = frozenset(
    {
        "cloudflare_zero_trust_tunnel_cloudflared",
        "cloudflare_zero_trust_tunnel_cloudflared_config",
        "cloudflare_zero_trust_access_application",
        "cloudflare_zero_trust_access_policy",
        "cloudflare_turnstile_widget",
        "cloudflare_r2_bucket",
        "cloudflare_workers_custom_domain",
        "cloudflare_zero_trust_tunnel_cloudflared_token",
    }
)
ZONE_SCOPED_TYPES = frozenset(
    {
        "cloudflare_dns_record",
        "cloudflare_zone_setting",
        "cloudflare_ruleset",
        "cloudflare_workers_custom_domain",
    }
)
FORBIDDEN_DNS_TYPES = frozenset({"MX", "TXT", "NS", "CAA"})
MAX_CHANGES = 30
REMOVAL_ACTION = "del" + "ete"
TFVAR_PATTERN = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"([^"\r\n]*)"\s*$')


class GateError(ValueError):
    """A safe, value-free gate failure."""


def parse_tfvars(path: Path) -> dict[str, str]:
    """Read required scalar identifiers from a local tfvars file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise GateError("tfvars source is missing or unreadable") from error
    values = {
        match.group(1): match.group(2)
        for line in text.splitlines()
        if (match := TFVAR_PATTERN.match(line))
    }
    required = {"account_id", "zone_id", "zone_name", "admin_email"}
    if not required.issubset(values):
        raise GateError("tfvars source lacks required scalar inputs")
    return values


def load_plan(path: Path) -> dict[str, Any]:
    """Load a Terraform show JSON document."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GateError("plan JSON is missing, unreadable, or invalid") from error
    if not isinstance(value, dict) or not isinstance(value.get("resource_changes", []), list):
        raise GateError("plan JSON has an invalid resource_changes collection")
    return value


def normalized_dns_name(name: object, zone_name: str) -> str | None:
    """Normalize a known DNS name; return None when Terraform has not resolved it."""
    if not isinstance(name, str):
        return None
    normalized = name.rstrip(".").lower()
    zone = zone_name.rstrip(".").lower()
    if normalized == "@":
        return zone
    if normalized == "www":
        return f"www.{zone}"
    return normalized


def access_emails(after: dict[str, Any]) -> list[str] | None:
    """Extract only exact email selectors from a resolved Access policy."""
    include = after.get("include")
    if not isinstance(include, list):
        return None
    emails: list[str] = []
    for selector in include:
        if not isinstance(selector, dict) or set(selector) != {"email"}:
            return None
        email_selector = selector.get("email")
        if not isinstance(email_selector, dict) or set(email_selector) != {"email"}:
            return None
        email = email_selector.get("email")
        if not isinstance(email, str):
            return None
        emails.append(email)
    return emails


def changed_actions(change: dict[str, Any]) -> list[str]:
    """Return Terraform's action list, rejecting malformed records."""
    actions = change.get("change", {}).get("actions")
    if not isinstance(actions, list) or not all(isinstance(action, str) for action in actions):
        raise GateError("resource change has invalid actions")
    return actions


def check_change(change: dict[str, Any], inputs: dict[str, str]) -> list[str]:
    """Validate one resource change and return redacted result lines."""
    address = change.get("address")
    resource_type = change.get("type")
    mode = change.get("mode", "managed")
    if not isinstance(address, str) or not isinstance(resource_type, str):
        raise GateError("resource change lacks stable metadata")

    actions = changed_actions(change)
    if REMOVAL_ACTION in actions:
        raise GateError(f"{resource_type} {address}: removal or replacement is forbidden")
    if mode == "data":
        if resource_type not in ALLOWED_DATA_SOURCES:
            raise GateError(f"{resource_type} {address}: data source type is not allowlisted")
    elif mode == "managed":
        if resource_type not in ALLOWED_RESOURCES:
            raise GateError(f"{resource_type} {address}: resource type is not allowlisted")
    else:
        raise GateError(f"{resource_type} {address}: resource mode is not allowlisted")

    after = change.get("change", {}).get("after")
    if after is None:
        after = {}
    if not isinstance(after, dict):
        raise GateError(f"{resource_type} {address}: resolved after-state is required")
    if resource_type in ACCOUNT_SCOPED_TYPES and after.get("account_id") != inputs["account_id"]:
        raise GateError(f"{resource_type} {address}: account_id differs from tfvars")
    if resource_type in ZONE_SCOPED_TYPES and after.get("zone_id") != inputs["zone_id"]:
        raise GateError(f"{resource_type} {address}: zone_id differs from tfvars")

    action_label = ",".join(actions)
    lines = [f"{resource_type}\t{address}\t{action_label}"]
    if resource_type == "cloudflare_dns_record":
        dns_type = after.get("type")
        name = normalized_dns_name(after.get("name"), inputs["zone_name"])
        if not isinstance(dns_type, str) or name is None:
            raise GateError(f"{resource_type} {address}: DNS name and type must be resolved")
        dns_type = dns_type.upper()
        zone = inputs["zone_name"].rstrip(".").lower()
        if dns_type in FORBIDDEN_DNS_TYPES:
            raise GateError(f"{resource_type} {address}: forbidden DNS type")
        if name in {zone, f"www.{zone}"}:
            raise GateError(f"{resource_type} {address}: apex or www DNS is forbidden")
        lines.append(f"DNS\t{address}\t{name}\t{dns_type}")
    if resource_type == "cloudflare_zero_trust_access_policy":
        emails = access_emails(after)
        if emails != [inputs["admin_email"]]:
            raise GateError(
                f"{resource_type} {address}: Access include is not the exact admin email"
            )
        lines.append(f"ACCESS\t{address}\tadmin_email_match=yes")
    return lines


def evaluate(plan: dict[str, Any], inputs: dict[str, str]) -> list[str]:
    """Validate all effective changes and return safe output lines."""
    changes = plan.get("resource_changes", [])
    effective = [
        change
        for change in changes
        if changed_actions(change) != ["no-op"]
        or isinstance(change.get("change", {}).get("importing"), dict)
    ]
    if len(effective) > MAX_CHANGES:
        raise GateError(f"plan exceeds the {MAX_CHANGES}-change limit")
    lines: list[str] = ["TYPE\tADDRESS\tACTION"]
    for change in effective:
        lines.extend(check_change(change, inputs))
    lines.append(f"tf-gate: PASS ({len(effective)} change(s))")
    return lines


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan_json", type=Path)
    parser.add_argument("--tfvars", type=Path, required=True, help="local reviewed tfvars source")
    return parser.parse_args()


def main() -> int:
    """Run the gate, emitting no arbitrary plan or tfvars values."""
    args = parse_args()
    try:
        inputs = parse_tfvars(args.tfvars)
        plan = load_plan(args.plan_json)
        for line in evaluate(plan, inputs):
            sys.stdout.write(f"{line}\n")
    except GateError as error:
        sys.stdout.write(f"tf-gate: FAIL ({error})\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
