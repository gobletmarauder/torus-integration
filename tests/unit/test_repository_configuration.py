"""Tests for repository workflow configuration that must remain reviewable offline."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
FULL_SHA_ACTION = re.compile(r"uses:\s+[^\s@]+@([0-9a-f]{40})(?:\s|$)")
ANY_ACTION = re.compile(r"uses:\s+[^\s@]+@([^\s#]+)")


def read(relative: str) -> str:
    """Read repository configuration as UTF-8 text."""
    return (ROOT / relative).read_text(encoding="utf-8")


def test_ci_detects_terraform_only_after_checkout() -> None:
    workflow = read(".github/workflows/ci.yml")
    checkout = workflow.index("name: Check out repository", workflow.index("terraform:"))
    detection = workflow.index("name: Detect Terraform configuration", checkout)

    assert "hashFiles(" not in workflow
    assert checkout < detection
    assert workflow.count("if: steps.terraform.outputs.present == 'true'") == 3


def test_every_action_reference_is_pinned_to_a_full_sha() -> None:
    workflows = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    )
    references = ANY_ACTION.findall(workflows)

    assert references
    assert len(FULL_SHA_ACTION.findall(workflows)) == len(references)


def test_release_privileges_and_exact_image_handoff() -> None:
    workflow = read(".github/workflows/release.yml")
    build = workflow[workflow.index("build-and-scan:") : workflow.index("  publish:")]
    publish = workflow[workflow.index("  publish:") :]

    assert "packages: write" not in build
    assert "contents: read" in build
    assert publish.count("packages: write") == 1
    assert "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c" in publish
    assert "docker load --input tis-release-image.tar" in publish
    assert "docker push" in publish
    assert "docker build" not in publish
    assert "docker/build-push-action" not in workflow


def test_make_exports_milestone_neutral_image_to_bundle_script() -> None:
    makefile = read("Makefile")

    assert "IMAGE ?= tis:local\nexport IMAGE" in makefile
    assert 'IMAGE="$(IMAGE)"' not in makefile
