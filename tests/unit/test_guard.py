"""Tests for the repository policy guard using synthetic temporary repositories."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tis import VERSION

GUARD = Path(__file__).parents[2] / "scripts" / "guard.py"
SAFE_WORKFLOW = """name: safe
on: [push]
permissions:
  contents: read
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
"""


def test_package_version_matches_bootstrap_release() -> None:
    assert VERSION == "0.0.0"


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a local command without a shell and capture its text output."""
    return subprocess.run(command, cwd=cwd, check=False, capture_output=True, text=True)


def write(root: Path, relative: str, content: str) -> None:
    """Write synthetic text below a temporary repository root."""
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def initialize_repository(root: Path) -> str:
    """Create a synthetic git repository and return its baseline commit."""
    write(root, "pyproject.toml", '[project]\nname = "fixture"\ndependencies = []\n')
    write(root, "docs/dependencies.md", "# Synthetic dependency register\n")
    commands = [
        ["git", "init", "-b", "main"],
        ["git", "config", "user.name", "Fixture Author"],
        ["git", "config", "user.email", "fixture@example.com"],
        ["git", "add", "."],
        ["git", "commit", "-m", "synthetic baseline"],
    ]
    for command in commands:
        result = run(command, root)
        assert result.returncode == 0, result.stderr
    result = run(["git", "rev-parse", "HEAD"], root)
    assert result.returncode == 0
    return result.stdout.strip()


def guard(root: Path, base: str) -> subprocess.CompletedProcess[str]:
    """Run the real guard against a synthetic root and explicit base."""
    return run([sys.executable, str(GUARD), "--root", str(root), "--base", base], root)


def test_safe_tree_passes(tmp_path: Path) -> None:
    base = initialize_repository(tmp_path)
    write(tmp_path, "src/tis/module.py", "def value() -> int:\n    return 1\n")

    result = guard(tmp_path, base)

    assert result.returncode == 0
    assert "guard: PASS" in result.stdout


@pytest.mark.parametrize(
    "module",
    [
        "requests",
        "urllib.request",
        "http.client",
        "aiohttp",
        "socket",
        "httpx",
        "urllib3",
        "websockets",
        "smtplib",
        "ftplib",
    ],
)
def test_forbidden_network_imports_fail(tmp_path: Path, module: str) -> None:
    base = initialize_repository(tmp_path)
    write(tmp_path, "src/tis/module.py", "im" + f"port {module}\n")

    result = guard(tmp_path, base)

    assert result.returncode == 1
    assert "NET001" in result.stdout


def test_http_module_is_the_only_httpx_import_exception(tmp_path: Path) -> None:
    base = initialize_repository(tmp_path)
    write(
        tmp_path,
        "src/tis/http.py",
        "im"
        + "port httpx\nEGRESS_ALLOWLIST = frozenset({'accounts.zoho.com', "
        + "'oauth2.googleapis.com', 'torusmesh.cloudflareaccess.com', "
        + "'uptime.betterstack.com', 'us.i.posthog.com', "
        + "'www.googleapis.com', 'www.zohoapis.com'})\n",
    )

    result = guard(tmp_path, base)

    assert result.returncode == 0


@pytest.mark.parametrize("module", ["requests", "urllib3", "websockets", "smtplib", "ftplib"])
def test_http_module_rejects_other_network_clients(tmp_path: Path, module: str) -> None:
    base = initialize_repository(tmp_path)
    write(tmp_path, "src/tis/http.py", "im" + f"port {module}\n")

    result = guard(tmp_path, base)

    assert result.returncode == 1
    assert "NET001" in result.stdout


def test_literal_false_is_the_only_allowed_shell_value(tmp_path: Path) -> None:
    base = initialize_repository(tmp_path)
    write(tmp_path, "src/tis/module.py", "import subprocess\nsubprocess.run([], shell=False)\n")

    result = guard(tmp_path, base)

    assert result.returncode == 0


@pytest.mark.parametrize(
    ("source", "rule"),
    [
        ("import subprocess\nsubprocess.run([], shell=" + "True)\n", "PY003"),
        (("ev" + "al") + "('1')\n", "PY002"),
        (("ex" + "ec") + "('x = 1')\n", "PY002"),
        ("import builtins\nbuiltins." + "eval('1')\n", "PY002"),
        ("import builtins\nbuiltins." + "exec('x = 1')\n", "PY002"),
        ("import importlib\nimportlib.import_" + "module('module')\n", "PY005"),
        (("__im" + "port__") + "('module')\n", "PY005"),
        ("import pickle\npickle." + "loads(b'x')\n", "PY004"),
        (("pri" + "nt") + "('x')\n", "LOG001"),
    ],
)
def test_unsafe_python_constructs_fail(tmp_path: Path, source: str, rule: str) -> None:
    base = initialize_repository(tmp_path)
    write(tmp_path, "src/tis/module.py", source)

    result = guard(tmp_path, base)

    assert result.returncode == 1
    assert rule in result.stdout


@pytest.mark.parametrize("value", ["True", "None", "1", "'yes'", "enabled"])
def test_non_false_shell_values_fail(tmp_path: Path, value: str) -> None:
    base = initialize_repository(tmp_path)
    prefix = "enabled = False\n" if value == "enabled" else ""
    write(
        tmp_path,
        "src/tis/module.py",
        prefix + "import subprocess\nsubprocess.run([], shell=" + value + ")\n",
    )

    result = guard(tmp_path, base)

    assert result.returncode == 1
    assert "PY003" in result.stdout


def test_long_encoded_blob_fails(tmp_path: Path) -> None:
    base = initialize_repository(tmp_path)
    write(tmp_path, "src/tis/module.py", "VALUE = '" + ("A" * 201) + "'\n")

    result = guard(tmp_path, base)

    assert result.returncode == 1
    assert "ENC001" in result.stdout


def test_hardcoded_url_fails(tmp_path: Path) -> None:
    base = initialize_repository(tmp_path)
    value = "https" + "://service.invalid/path"
    write(tmp_path, "src/tis/module.py", f"VALUE = {value!r}\n")

    result = guard(tmp_path, base)

    assert result.returncode == 1
    assert "NET002" in result.stdout


def test_service_url_literal_outside_http_module_fails(tmp_path: Path) -> None:
    base = initialize_repository(tmp_path)
    value = "https" + "://us.i.posthog.com/capture"
    write(tmp_path, "src/tis/module.py", f"VALUE = {value!r}\n")

    result = guard(tmp_path, base)

    assert result.returncode == 1
    assert "NET003" in result.stdout


def test_unapproved_access_team_host_fails(tmp_path: Path) -> None:
    base = initialize_repository(tmp_path)
    value = "https" + "://other-team.cloudflareaccess.com/cdn-cgi/access/certs"
    write(tmp_path, "src/tis/http.py", f"VALUE = {value!r}\n")

    result = guard(tmp_path, base)

    assert result.returncode == 1
    assert "NET002" in result.stdout


def test_runtime_and_guard_egress_allowlists_must_match(tmp_path: Path) -> None:
    base = initialize_repository(tmp_path)
    write(
        tmp_path,
        "src/tis/http.py",
        "EGRESS_ALLOWLIST: frozenset[str] = frozenset({'different.example'})\n",
    )

    result = guard(tmp_path, base)

    assert result.returncode == 1
    assert "NET004" in result.stdout


@pytest.mark.parametrize(
    "statement",
    [
        "DR" + "OP TABLE fixture",
        "TRUN" + "CATE TABLE fixture",
        "AL" + "TER TABLE fixture",
        "GRA" + "NT SELECT ON fixture",
        "RE" + "VOKE SELECT ON fixture",
        "CRE" + "ATE ROLE fixture",
        "DEL" + "ETE FROM fixture",
    ],
)
def test_destructive_sql_fails(tmp_path: Path, statement: str) -> None:
    base = initialize_repository(tmp_path)
    write(tmp_path, "src/tis/module.py", f"QUERY = {statement!r}\n")

    result = guard(tmp_path, base)

    assert result.returncode == 1
    assert "SQL001" in result.stdout


def test_dependency_change_requires_register_change(tmp_path: Path) -> None:
    base = initialize_repository(tmp_path)
    write(
        tmp_path,
        "pyproject.toml",
        '[project]\nname = "fixture"\ndependencies = ["synthetic==1.0"]\n',
    )

    missing_register = guard(tmp_path, base)
    assert missing_register.returncode == 1
    assert "DEP001" in missing_register.stdout

    write(tmp_path, "docs/dependencies.md", "# Synthetic dependency register\n- synthetic 1.0\n")
    documented = guard(tmp_path, base)
    assert documented.returncode == 0


def test_protected_changes_are_complete_reports_not_failures(tmp_path: Path) -> None:
    base = initialize_repository(tmp_path)
    write(tmp_path, ".sops.yaml", "creation_rules: []\n")
    write(tmp_path, ".github/workflows/ci.yml", SAFE_WORKFLOW)

    result = guard(tmp_path, base)

    assert result.returncode == 0
    assert "PROTECTED: .github/workflows/ci.yml" in result.stdout
    assert "PROTECTED: .sops.yaml" in result.stdout


def test_mutable_action_reference_fails(tmp_path: Path) -> None:
    base = initialize_repository(tmp_path)
    workflow = SAFE_WORKFLOW.replace("a" * 40, "v4")
    write(tmp_path, ".github/workflows/ci.yml", workflow)

    result = guard(tmp_path, base)

    assert result.returncode == 1
    assert "CI002" in result.stdout


def test_pull_request_target_fails(tmp_path: Path) -> None:
    base = initialize_repository(tmp_path)
    workflow = SAFE_WORKFLOW + "pull_request_target:\n"
    write(tmp_path, ".github/workflows/ci.yml", workflow)

    result = guard(tmp_path, base)

    assert result.returncode == 1
    assert "CI001" in result.stdout


def test_broad_workflow_permission_fails(tmp_path: Path) -> None:
    base = initialize_repository(tmp_path)
    workflow = SAFE_WORKFLOW.replace("contents: read", "contents: write")
    write(tmp_path, ".github/workflows/ci.yml", workflow)

    result = guard(tmp_path, base)

    assert result.returncode == 1
    assert "CI003" in result.stdout
    assert "CI004" in result.stdout


@pytest.mark.parametrize(
    "name_expression", ["var.ops_hostname", "var.ssh_hostname", '"ops"', '"ssh"']
)
def test_safe_terraform_dns_records_pass(tmp_path: Path, name_expression: str) -> None:
    base = initialize_repository(tmp_path)
    write(
        tmp_path,
        "infra/cloudflare/dns.tf",
        'resource "cloudflare_dns_record" "ops" {\n'
        f"  name = {name_expression}\n"
        '  type = "CNAME"\n'
        '  content = "https' + '://internal-origin.invalid"\n'
        "}\n",
    )

    result = guard(tmp_path, base)

    assert result.returncode == 0


@pytest.mark.parametrize("dns_type", ["MX", "TXT", "NS", "CAA"])
def test_forbidden_terraform_dns_types_fail(tmp_path: Path, dns_type: str) -> None:
    base = initialize_repository(tmp_path)
    write(
        tmp_path,
        "infra/cloudflare/dns.tf",
        'resource "cloudflare_dns_record" "planted" {\n'
        "  name = var.ops_hostname\n"
        f'  type = "{dns_type}"\n'
        "}\n",
    )

    result = guard(tmp_path, base)

    assert result.returncode == 1
    assert "TFDNS001" in result.stdout


@pytest.mark.parametrize(
    "name_expression",
    ['"@"', '"www"', '"example.com"', '"www.example.com"', "var.unreviewed_hostname"],
)
def test_forbidden_or_unprovable_terraform_dns_names_fail(
    tmp_path: Path, name_expression: str
) -> None:
    base = initialize_repository(tmp_path)
    write(
        tmp_path,
        "infra/cloudflare/dns.tf",
        'resource "cloudflare_dns_record" "planted" {\n'
        f"  name = {name_expression}\n"
        '  type = "CNAME"\n'
        "}\n",
    )

    result = guard(tmp_path, base)

    assert result.returncode == 1
    assert "TFDNS002" in result.stdout
