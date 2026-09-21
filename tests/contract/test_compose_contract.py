"""Static production Compose hardening contract."""

from pathlib import Path


def test_compose_has_four_digest_pinned_services_and_no_host_ports() -> None:
    compose = Path("deploy/compose.yaml").read_text(encoding="utf-8")
    for service in ("tis-scheduler", "tis-api", "cloudflared", "torus-backup"):
        assert f"  {service}:" in compose
    assert compose.count("image:") == 4
    assert compose.count("@${") == 4
    assert "ports:" not in compose
    assert "privileged:" not in compose
    assert "network_mode: host" not in compose
    assert "/var/run/docker.sock" not in compose


def test_compose_applies_required_hardening_and_internal_api_only() -> None:
    compose = Path("deploy/compose.yaml").read_text(encoding="utf-8")
    assert "read_only: true" in compose
    assert 'cap_drop: ["ALL"]' in compose
    assert 'security_opt: ["no-new-privileges:true"]' in compose
    assert "restart: unless-stopped" in compose
    assert 'user: "10001:10001"' in compose
    assert 'expose: ["8080"]' in compose
    assert "internal: true" in compose
    assert "/opt/torus/state:/host-state:ro" in compose
    assert 'profiles: ["backup"]' in compose
    assert "torus-cloudflared.yml:/etc/cloudflared/torus-cloudflared.yml:ro" in compose
    assert "/var/run/docker.sock" not in compose
