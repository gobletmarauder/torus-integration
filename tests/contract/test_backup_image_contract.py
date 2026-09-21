"""Static contract for the digest-pinned, non-root backup image."""

from pathlib import Path


def test_backup_image_is_pinned_nonroot_and_checksum_verified() -> None:
    dockerfile = Path("deploy/backup/Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.count("postgres:17.6-bookworm@sha256:") == 2
    assert "rclone-v1.75.1-linux-amd64.zip" in dockerfile
    assert "age-v1.2.1-linux-amd64.tar.gz" in dockerfile
    assert dockerfile.count("sha256sum --check --status") == 2
    assert "USER 10001:10001" in dockerfile
    final = dockerfile[dockerfile.rindex("FROM postgres:") :]
    assert final.index("RUN rm -rf /var/lib/apt/lists/") < final.index("USER 10001:10001")
    assert "/usr/bin/apt*" in final
    assert "/usr/bin/dpkg*" in final
    assert "curl" not in final
    assert "wget" not in final
    assert "gcc" not in final
