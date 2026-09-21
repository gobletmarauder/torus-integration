"""Local image invariant tests."""

import runpy
from collections.abc import Callable
from typing import Any, cast

MODULE = runpy.run_path("scripts/check_image.py")
MAX_IMAGE_BYTES = cast(int, MODULE["MAX_IMAGE_BYTES"])
violations = cast(Callable[[str, dict[str, Any]], list[str]], MODULE["violations"])


def metadata(*, size: int = 100, user: str = "10001:10001", health: bool = True) -> dict:
    return {
        "Size": size,
        "Config": {
            "User": user,
            "Healthcheck": {"Test": ["CMD", "python"]} if health else None,
        },
    }


def test_local_image_accepts_hardened_metadata() -> None:
    assert violations("tis:local", metadata()) == []
    assert violations("ghcr.io/example/tis@sha256:synthetic", metadata()) == []


def test_image_gate_reports_each_invariant() -> None:
    findings = violations(
        "tis:mutable",
        metadata(size=MAX_IMAGE_BYTES, user="0:0", health=False),
    )
    assert len(findings) == 4
    assert violations("tis:local", {}) == ["image configuration is missing"]
