"""Fail-closed checks for the local M4 runtime image."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any

MAX_IMAGE_BYTES = 250 * 1024 * 1024


def inspect_image(image: str) -> dict[str, Any]:
    """Read local Docker image metadata without contacting a registry."""
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["docker", "image", "inspect", image],  # noqa: S607 - operator Docker executable
        check=True,
        capture_output=True,
        text=True,
        shell=False,
    )
    document = json.loads(result.stdout)
    if not isinstance(document, list) or len(document) != 1 or not isinstance(document[0], dict):
        raise ValueError("docker image inspect returned an unexpected document")
    return document[0]


def violations(image: str, metadata: dict[str, Any]) -> list[str]:
    """Return safe invariant labels for invalid image metadata."""
    findings: list[str] = []
    config = metadata.get("Config")
    if not isinstance(config, dict):
        return ["image configuration is missing"]
    if int(metadata.get("Size", MAX_IMAGE_BYTES + 1)) >= MAX_IMAGE_BYTES:
        findings.append("image is not smaller than 250 MB")
    if config.get("User") != "10001:10001":
        findings.append("image user is not 10001:10001")
    health = config.get("Healthcheck")
    if not isinstance(health, dict) or not health.get("Test"):
        findings.append("image healthcheck is missing")
    if image != "tis:local" and "@sha256:" not in image:
        findings.append("deployment image reference is not digest-pinned")
    return findings


def main() -> None:
    """Inspect one local image and exit non-zero on any hardening failure."""
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    args = parser.parse_args()
    try:
        metadata = inspect_image(args.image)
        findings = violations(args.image, metadata)
    except (OSError, subprocess.CalledProcessError, ValueError, json.JSONDecodeError) as error:
        sys.stderr.write(f"image-check: FAIL ({type(error).__name__})\n")
        raise SystemExit(1) from error
    for finding in findings:
        sys.stderr.write(f"image-check: FAIL ({finding})\n")
    if findings:
        raise SystemExit(1)
    size_mb = int(metadata["Size"]) / (1024 * 1024)
    sys.stdout.write(f"image-check: PASS ({size_mb:.1f} MB, uid 10001, healthcheck present)\n")


if __name__ == "__main__":
    main()
