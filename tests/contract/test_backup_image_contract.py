"""Static contract for the digest-pinned, non-root backup image."""

from pathlib import Path


def test_backup_image_is_pinned_nonroot_and_checksum_verified() -> None:
    dockerfile = Path("deploy/backup/Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.count("postgres:17.6-bookworm@sha256:") == 2
    assert (
        "golang:1.26.8-bookworm@sha256:"
        "a688600ca24f8a4d3ca77f95b0dd40704a9fc787c826660eb7ba0b641b8b175d"
    ) in dockerfile
    assert "RCLONE_COMMIT=687d264b689b8c49a67e2e52a8a5e0caa01c04ce" in dockerfile
    assert "RCLONE_VERSION=v1.75.1" in dockerfile
    assert "GRPC_VERSION=v1.83.2" in dockerfile
    assert "go mod edit -replace=google.golang.org/grpc=" in dockerfile
    assert "GOPROXY=https" + "://proxy.golang.org" in dockerfile
    assert "GOSUMDB=sum.golang.org" in dockerfile
    assert "age-v1.3.2-linux-amd64.tar.gz" in dockerfile
    assert "cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10" in dockerfile
    assert dockerfile.count("sha256sum --check --status") == 1
    assert "USER 10001:10001" in dockerfile
    final = dockerfile[dockerfile.rindex("FROM postgres:") :]
    assert final.index("apt-get upgrade --yes") < final.index("USER 10001:10001")
    assert "/usr/bin/apt*" in final
    assert "/usr/bin/dpkg*" in final
    assert "/usr/local/bin/gosu" in final
    assert "curl" not in final
    assert "wget" not in final
    assert "gcc" not in final
    assert "COPY --from=rclone-builder /out/rclone" in final
