"""Offline tests for milestone-specific verification-bundle helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "verify_bundle.sh"
WINDOWS_GIT_BASH = Path("C:/Program Files/Git/bin/bash.exe")
BASH = str(WINDOWS_GIT_BASH) if WINDOWS_GIT_BASH.exists() else shutil.which("bash")


def bash(script: str, *arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Source the bundle script and run an offline helper."""
    assert BASH is not None
    return subprocess.run(
        [BASH, "-c", f'source "$1"; {script}', "bundle-test", SCRIPT.as_posix(), *arguments],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": os.environ["PATH"]},
    )


def git(root: Path, *arguments: str) -> str:
    """Run a local-only git command in a synthetic repository."""
    result = subprocess.run(
        ["git", *arguments], cwd=root, check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def initialize_repository(root: Path) -> str:
    """Create a synthetic two-commit-capable repository."""
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Fixture Author")
    git(root, "config", "user.email", "fixture@example.com")
    (root / "baseline.txt").write_text("baseline\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "baseline")
    return git(root, "rev-parse", "HEAD")


@pytest.mark.skipif(BASH is None, reason="bash is required by the repository")
def test_extracts_only_selected_plan_tasks_and_verdict(tmp_path: Path) -> None:
    progress = tmp_path / "PROGRESS.md"
    plan = tmp_path / "plan.md"
    progress.write_text(
        "### M8 G0 plan (2026-01-01)\n"
        "Scope: M8.1, M8.2. Synthetic.\n"
        "Files to create/modify: `inside.txt`.\n\n"
        "### M9 G0 plan (2026-01-02)\n"
        "Scope: M9.3. Selected.\n"
        "Files to create/modify: `selected.txt`.\n\n"
        "**M9 G3 verdict**\nPASS at selected head.\n\n"
        "---\n",
        encoding="utf-8",
    )

    result = bash(
        'extract_g0_plan "$2" M9 "$3" && extract_task_ids "$3" && extract_previous_verdict "$2" M9',
        progress.as_posix(),
        plan.as_posix(),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines() == ["M9.3", "PASS at selected head."]
    assert "selected.txt" in plan.read_text(encoding="utf-8")
    assert "inside.txt" not in plan.read_text(encoding="utf-8")


@pytest.mark.skipif(BASH is None, reason="bash is required by the repository")
def test_scope_membership_uses_only_extracted_plan(tmp_path: Path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text("Files: `planned.txt`.\n", encoding="utf-8")

    result = bash(
        'path_is_in_plan "$2" planned.txt; planned=$?; '
        'path_is_in_plan "$2" elsewhere.txt || elsewhere=$?; '
        'printf "%s %s\\n" "$planned" "$elsewhere"',
        plan.as_posix(),
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "0 1"


@pytest.mark.skipif(BASH is None, reason="bash is required by the repository")
def test_missing_notes_fails_before_external_commands(tmp_path: Path) -> None:
    initialize_repository(tmp_path)

    result = subprocess.run(
        [BASH, SCRIPT.as_posix(), "M9"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": os.environ["PATH"]},
    )

    assert result.returncode == 1
    assert "missing required notes file docs/pr-notes/M9.md" in result.stderr


@pytest.mark.skipif(BASH is None, reason="bash is required by the repository")
def test_present_notes_and_configured_image_flow_through_fake_tools(tmp_path: Path) -> None:
    base = initialize_repository(tmp_path)
    git(tmp_path, "checkout", "-b", "feature")
    (tmp_path / "docs" / "pr-notes").mkdir(parents=True)
    (tmp_path / "docs" / "bundles").mkdir(parents=True)
    (tmp_path / "docs" / "pr-notes" / "M9.md").write_text(
        "### Security notes\nSynthetic only.\n", encoding="utf-8"
    )
    (tmp_path / "PROGRESS.md").write_text(
        "### M9 G0 plan (2026-01-01)\n"
        "Scope: M9.1. Synthetic.\n"
        "Files to create/modify: `PROGRESS.md`, `docs/pr-notes/M9.md`.\n\n---\n",
        encoding="utf-8",
    )
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "bundle inputs")
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    (fake_bin / "uv").write_text("#!/usr/bin/env bash\necho 'fake uv PASS'\n", encoding="utf-8")
    (fake_bin / "docker").write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1 $2" == \'image inspect\' ]]; then echo "inspected $3"; fi\n'
        "if [[ \"$1\" == 'save' ]]; then while [[ $# -gt 0 ]]; do "
        'if [[ "$1" == \'--output\' ]]; then shift; : > "$1"; fi; shift; done; fi\n',
        encoding="utf-8",
    )
    for shim in (fake_bin / "uv", fake_bin / "docker"):
        shim.chmod(0o755)

    result = subprocess.run(
        [
            BASH,
            "-c",
            'shim_dir="$1"; if command -v cygpath >/dev/null 2>&1; then '
            'shim_dir="$(cygpath -u "$shim_dir")"; fi; '
            'export PATH="$shim_dir:$PATH" IMAGE="fixture:image"; bash "$2" M9',
            "bundle-test",
            fake_bin.as_posix(),
            SCRIPT.as_posix(),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "verify-bundle: PASS" in result.stdout
    bundle = next((tmp_path / "docs" / "bundles").glob("M9-*.md"))
    rendered = bundle.read_text(encoding="utf-8")
    assert "Synthetic only." in rendered
    assert "inspected fixture:image" in rendered
    assert base in rendered


@pytest.mark.skipif(BASH is None, reason="bash is required by the repository")
def test_changed_file_diff_is_capped_with_marker(tmp_path: Path) -> None:
    base = initialize_repository(tmp_path)
    changed = tmp_path / "large.txt"
    changed.write_text("".join(f"line {number}\n" for number in range(450)), encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "large change")
    head = git(tmp_path, "rev-parse", "HEAD")
    output = tmp_path / "diff.md"
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    result = bash(
        'append_reviewable_diffs "$2" "$3" "$4" "$5"',
        base,
        head,
        output.as_posix(),
        scratch.as_posix(),
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    rendered = output.read_text(encoding="utf-8")
    assert "### `large.txt`" in rendered
    assert "[TRUNCATED: 400 of" in rendered


@pytest.mark.skipif(BASH is None, reason="bash is required by the repository")
def test_large_bundle_parts_end_on_line_boundaries(tmp_path: Path) -> None:
    source = tmp_path / "bundle.md"
    source.write_text("".join(("x" * 100) + "\n" for _ in range(500)), encoding="utf-8")
    output_base = (tmp_path / "M9-deadbeef").as_posix()

    result = bash(
        'parts=(); split_bundle_on_lines "$2" "$3" parts; printf "%s\\n" "${parts[@]}"',
        source.as_posix(),
        output_base,
    )

    assert result.returncode == 0, result.stderr
    parts = [Path(line) for line in result.stdout.splitlines()]
    assert len(parts) > 1
    assert all(path.read_bytes().endswith(b"\n") for path in parts)


def test_bundle_configuration_is_milestone_neutral_and_nonduplicative() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert 'image="${IMAGE:-tis:local}"' in script
    assert "tis:m0-local" not in script
    assert "Installed license list" not in script
    assert "':!docs/**' ':!*.md' ':!**/*.md'" in script
    assert 'cat "$notes_file"' in script
