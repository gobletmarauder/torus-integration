#!/usr/bin/env python3
"""Enforce repository safety policies without reading or emitting secret values."""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

FORBIDDEN_IMPORTS = (
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
)
PROTECTED_EXACT = {
    "AGENTS.md",
    ".sops.yaml",
    "scripts/guard.py",
    "scripts/verify_bundle.sh",
    "src/tis/http.py",
    "src/tis/guards.py",
}
PROTECTED_PREFIXES = (".github/", "deploy/", "infra/", "secrets/")
SCANNED_SUFFIXES = {".py", ".sh", ".yml", ".yaml", ".toml", ".tf", ".sql"}
SCANNED_NAMES = {"Dockerfile", "Makefile"}
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
}
ALLOWED_URL_HOSTS: frozenset[str] = frozenset(
    {
        "accounts.zoho.com",
        "oauth2.googleapis.com",
        "uptime.betterstack.com",
        "us.i.posthog.com",
        "www.googleapis.com",
        "www.zohoapis.com",
    }
)
URL_PATTERN = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)
ENCODED_PATTERN = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{201,}={0,2}(?![A-Za-z0-9+/])")
SQL_PATTERN = re.compile(
    r"\b(?:DROP|TRUNCATE|ALTER|GRANT|REVOKE|DELETE)\b\s+"
    r"(?:\b(?:TABLE|DATABASE|SCHEMA|ROLE|FROM|INTO|ON|USER|VIEW|SELECT|ALL)\b)?"
    r"|\bCREATE\s+ROLE\b",
    re.IGNORECASE,
)
ACTION_PATTERN = re.compile(r"^\s*(?:-\s*)?uses:\s*[^\s#]+@([^\s#]+)", re.MULTILINE)
FULL_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
WRITE_PERMISSION_PATTERN = re.compile(r"^\s*([a-z-]+):\s*write\s*$", re.MULTILINE)
TERRAFORM_DNS_BLOCK_PATTERN = re.compile(
    r'resource\s+"cloudflare_dns_record"\s+"[^"]+"\s*\{', re.MULTILINE
)
TERRAFORM_ATTRIBUTE_PATTERN = re.compile(r"^\s*(name|type)\s*=\s*([^#\r\n]+)", re.MULTILINE)
SAFE_DNS_NAME_EXPRESSIONS = frozenset({'"ops"', '"ssh"', "var.ops_hostname", "var.ssh_hostname"})


@dataclass(frozen=True, order=True)
class Finding:
    """A stable policy result that never contains source text."""

    path: str
    line: int
    rule: str
    message: str


class PythonPolicyVisitor(ast.NodeVisitor):
    """Find unsafe Python syntax using the parsed syntax tree."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.findings: list[Finding] = []
        self.pickle_load_aliases: set[str] = set()

    def add(self, node: ast.AST, rule: str, message: str) -> None:
        """Record a finding without including source contents."""
        self.findings.append(Finding(self.path, getattr(node, "lineno", 1), rule, message))

    def visit_Import(self, node: ast.Import) -> None:
        """Reject imports that bypass the single HTTP module."""
        for alias in node.names:
            self._check_import(node, alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Reject forbidden from-import forms and track pickle load aliases."""
        module = node.module or ""
        for alias in node.names:
            imported = f"{module}.{alias.name}" if module else alias.name
            self._check_import(node, imported)
            if module == "pickle" and alias.name == "loads":
                self.pickle_load_aliases.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Reject dynamic execution, unsafe subprocesses, deserialization, and prints."""
        if isinstance(node.func, ast.Name):
            if node.func.id in {"eval", "exec"}:
                self.add(node, "PY002", "dynamic execution is forbidden")
            if node.func.id == "__import__":
                self.add(node, "PY005", "dynamic imports are forbidden")
            if node.func.id in self.pickle_load_aliases:
                self.add(node, "PY004", "pickle deserialization is forbidden")
            if node.func.id == "print" and self.path.startswith("src/"):
                self.add(node, "LOG001", "print calls are forbidden under src/")
        if isinstance(node.func, ast.Attribute):
            if node.func.attr in {"eval", "exec"}:
                self.add(node, "PY002", "dynamic execution is forbidden")
            if (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "pickle"
                and node.func.attr == "loads"
            ):
                self.add(node, "PY004", "pickle deserialization is forbidden")
            if (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "importlib"
                and node.func.attr == "import_module"
            ):
                self.add(node, "PY005", "dynamic imports are forbidden")
        for keyword in node.keywords:
            if keyword.arg == "shell" and not (
                isinstance(keyword.value, ast.Constant) and keyword.value.value is False
            ):
                self.add(node, "PY003", "subprocess shell execution is forbidden")
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        """Inspect literal strings for URLs, encoded blobs, and destructive SQL."""
        if isinstance(node.value, str):
            self._check_literal(node, node.value)
        self.generic_visit(node)

    def _check_import(self, node: ast.AST, module: str) -> None:
        if self.path == "src/tis/http.py" and (module == "httpx" or module.startswith("httpx.")):
            return
        if any(module == item or module.startswith(f"{item}.") for item in FORBIDDEN_IMPORTS):
            self.add(node, "NET001", "network import is permitted only in src/tis/http.py")

    def _check_literal(self, node: ast.AST, value: str) -> None:
        if ENCODED_PATTERN.search(value):
            self.add(node, "ENC001", "encoded blob exceeds 200 characters")
        if SQL_PATTERN.search(value):
            self.add(node, "SQL001", "destructive SQL token is forbidden")
        for match in URL_PATTERN.finditer(value):
            host = (urlsplit(match.group(0)).hostname or "").lower()
            if host in ALLOWED_URL_HOSTS and self.path != "src/tis/http.py":
                self.add(
                    node, "NET003", "service URL literals are permitted only in src/tis/http.py"
                )
            elif host not in ALLOWED_URL_HOSTS:
                self.add(node, "NET002", "hardcoded URL host is not allowlisted")


def normalized(path: Path, root: Path) -> str:
    """Return a repository-relative POSIX path."""
    return path.relative_to(root).as_posix()


def should_scan(path: Path, root: Path) -> bool:
    """Return whether a file is executable source or configuration in guard scope."""
    relative = path.relative_to(root)
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    posix = relative.as_posix()
    if posix.startswith("docs/bundles/") or posix.startswith("tests/fixtures/"):
        return False
    if path.name == "uv.lock":
        return False
    return path.suffix in SCANNED_SUFFIXES or path.name in SCANNED_NAMES


def read_text(path: Path) -> str | None:
    """Read UTF-8 policy input, returning None for non-text or unreadable files."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def scan_python(path: Path, root: Path, text: str) -> list[Finding]:
    """Parse and inspect one Python file."""
    relative = normalized(path, root)
    try:
        tree = ast.parse(text, filename=relative)
    except SyntaxError as error:
        return [Finding(relative, error.lineno or 1, "PY001", "Python source does not parse")]
    visitor = PythonPolicyVisitor(relative)
    visitor.visit(tree)
    return visitor.findings


def scan_text(path: Path, root: Path, text: str) -> list[Finding]:
    """Inspect non-Python source and workflow integrity rules."""
    relative = normalized(path, root)
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if ENCODED_PATTERN.search(line):
            findings.append(
                Finding(relative, line_number, "ENC001", "encoded blob exceeds 200 characters")
            )
        if path.suffix == ".sql" and SQL_PATTERN.search(line):
            findings.append(
                Finding(relative, line_number, "SQL001", "destructive SQL token is forbidden")
            )
        for match in () if path.suffix == ".tf" else URL_PATTERN.finditer(line):
            host = (urlsplit(match.group(0)).hostname or "").lower()
            if host in ALLOWED_URL_HOSTS and relative != "src/tis/http.py":
                findings.append(
                    Finding(
                        relative,
                        line_number,
                        "NET003",
                        "service URL literals are permitted only in src/tis/http.py",
                    )
                )
            elif host not in ALLOWED_URL_HOSTS:
                findings.append(
                    Finding(
                        relative, line_number, "NET002", "hardcoded URL host is not allowlisted"
                    )
                )
    if relative.startswith(".github/workflows/"):
        findings.extend(scan_workflow(relative, text))
    if path.suffix == ".tf":
        findings.extend(scan_terraform_dns(relative, text))
    return findings


def terraform_blocks(text: str) -> list[tuple[int, str]]:
    """Return balanced Cloudflare DNS blocks and their starting lines."""
    blocks: list[tuple[int, str]] = []
    for match in TERRAFORM_DNS_BLOCK_PATTERN.finditer(text):
        depth = 1
        index = match.end()
        while index < len(text) and depth:
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
            index += 1
        if depth == 0:
            blocks.append((text.count("\n", 0, match.start()) + 1, text[match.end() : index - 1]))
        else:
            blocks.append((text.count("\n", 0, match.start()) + 1, ""))
    return blocks


def scan_terraform_dns(path: str, text: str) -> list[Finding]:
    """Allow only provably safe ops/SSH CNAME Terraform DNS resources."""
    findings: list[Finding] = []
    for line_number, block in terraform_blocks(text):
        attributes = {
            match.group(1): match.group(2).strip()
            for match in TERRAFORM_ATTRIBUTE_PATTERN.finditer(block)
        }
        dns_type = attributes.get("type")
        name = attributes.get("name")
        if dns_type != '"CNAME"':
            findings.append(
                Finding(
                    path, line_number, "TFDNS001", "DNS type is forbidden or cannot be proven safe"
                )
            )
        if name not in SAFE_DNS_NAME_EXPRESSIONS:
            findings.append(
                Finding(
                    path, line_number, "TFDNS002", "DNS name is forbidden or cannot be proven safe"
                )
            )
    return findings


def scan_workflow(path: str, text: str) -> list[Finding]:
    """Require safe triggers, immutable actions, and least-privilege permissions."""
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if re.match(r"^\s*pull_request_target\s*:", line):
            findings.append(Finding(path, line_number, "CI001", "pull_request_target is forbidden"))
    for match in ACTION_PATTERN.finditer(text):
        if not FULL_SHA_PATTERN.fullmatch(match.group(1)):
            line_number = text.count("\n", 0, match.start()) + 1
            findings.append(
                Finding(path, line_number, "CI002", "action must use a full commit SHA")
            )
    for match in WRITE_PERMISSION_PATTERN.finditer(text):
        permission = match.group(1)
        allowed = path == ".github/workflows/release.yml" and permission == "packages"
        if not allowed:
            line_number = text.count("\n", 0, match.start()) + 1
            findings.append(Finding(path, line_number, "CI003", "workflow permission is too broad"))
    if not re.search(r"^permissions:\s*\n\s+contents:\s*read\s*$", text, re.MULTILINE):
        findings.append(Finding(path, 1, "CI004", "workflow must default to contents: read"))
    return findings


def run_git(root: Path, arguments: list[str]) -> tuple[int, str]:
    """Run a read-only git query and return its status and stdout."""
    result = subprocess.run(  # noqa: S603 -- fixed argv, never a shell
        ["git", "-C", str(root), *arguments],  # noqa: S607 -- trusted executable
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout


def discover_base(root: Path) -> str | None:
    """Find a stable default comparison base without contacting a remote."""
    for candidate in ("origin/main", "main", "HEAD^"):
        status, _ = run_git(root, ["rev-parse", "--verify", "--quiet", candidate])
        if status == 0:
            return candidate
    return None


def changed_files(root: Path, base: str | None) -> list[str]:
    """List tracked changes since base plus untracked files."""
    changed: set[str] = set()
    if base:
        status, output = run_git(root, ["diff", "--name-only", base, "--"])
        if status == 0:
            changed.update(line.strip() for line in output.splitlines() if line.strip())
    status, output = run_git(root, ["ls-files", "--others", "--exclude-standard"])
    if status == 0:
        changed.update(line.strip() for line in output.splitlines() if line.strip())
    return sorted(changed)


def is_protected(path: str) -> bool:
    """Return whether a repository path is protected by AGENTS.md."""
    return path in PROTECTED_EXACT or path.startswith(PROTECTED_PREFIXES)


def scan_repository(root: Path, base: str | None) -> tuple[list[Finding], list[str]]:
    """Scan the repository and return failing findings plus protected change reports."""
    findings: list[Finding] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if not should_scan(path, root):
            continue
        text = read_text(path)
        if text is None:
            continue
        if path.suffix == ".py":
            findings.extend(scan_python(path, root, text))
        else:
            findings.extend(scan_text(path, root, text))

    changed = changed_files(root, base)
    dependency_files = {"pyproject.toml", "uv.lock"}
    if dependency_files.intersection(changed) and "docs/dependencies.md" not in changed:
        findings.append(
            Finding(
                "pyproject.toml",
                1,
                "DEP001",
                "dependency changes require a docs/dependencies.md change",
            )
        )
    protected = sorted(path for path in changed if is_protected(path))
    runtime_http = root / "src" / "tis" / "http.py"
    if runtime_http.is_file():
        runtime_hosts = read_runtime_allowlist(runtime_http)
        if runtime_hosts != ALLOWED_URL_HOSTS:
            findings.append(
                Finding(
                    "src/tis/http.py",
                    1,
                    "NET004",
                    "runtime and guard egress allowlists differ",
                )
            )
    return sorted(set(findings)), protected


def read_runtime_allowlist(path: Path) -> frozenset[str] | None:
    """Read only the literal EGRESS_ALLOWLIST assignment from the protected HTTP module."""
    text = read_text(path)
    if text is None:
        return None
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(
            isinstance(target, ast.Name) and target.id == "EGRESS_ALLOWLIST" for target in targets
        ):
            continue
        value = node.value
        if not isinstance(value, ast.Call) or not value.args:
            return None
        literal = value.args[0]
        if not isinstance(literal, (ast.Set, ast.List, ast.Tuple)):
            return None
        hosts = {
            element.value
            for element in literal.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        }
        return frozenset(hosts)
    return None


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--base", help="git revision used for dependency/protected-path checks")
    return parser.parse_args()


def main() -> int:
    """Run all policies and emit only stable metadata, never source contents."""
    args = parse_args()
    root = args.root.resolve()
    base = args.base or discover_base(root)
    findings, protected = scan_repository(root, base)
    for path in protected:
        sys.stdout.write(f"PROTECTED: {path}\n")
    for finding in findings:
        sys.stdout.write(f"FAIL {finding.rule} {finding.path}:{finding.line} {finding.message}\n")
    if findings:
        sys.stdout.write(f"guard: FAIL ({len(findings)} finding(s))\n")
        return 1
    sys.stdout.write(f"guard: PASS ({len(protected)} protected change(s) reported)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
