"""Internal health and Access-protected status endpoint tests."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from tis.api.access import AccessValidationError
from tis.api.app import create_app
from tis.api.status import StatusService
from tis.config import Settings
from tis.http import ControlledClient


class Database:
    def __init__(self, *, healthy: bool = True) -> None:
        self.healthy = healthy

    async def fetch_value(self, query: str, parameters: Sequence[Any]) -> Any:
        if query.strip() == "SELECT 1" and not self.healthy:
            raise RuntimeError("synthetic unavailable")
        return 0 if "integration_log" in query else 1

    async def fetch_all(self, query: str, parameters: Sequence[Any]) -> list[Mapping[str, Any]]:
        return []

    async def fetch_one(self, query: str, parameters: Sequence[Any]) -> Mapping[str, Any] | None:
        return {"unsynced": 0, "aged": 0}


class State:
    async def kill_switch_on(self) -> bool:
        return False

    async def get(self, key: str) -> Any:
        return None


class Runtime:
    def __init__(self, *, healthy: bool = True) -> None:
        self.settings = Settings(
            database_dsn="postgresql://synthetic.invalid/db",
            cloudflare_access_team_domain="torusmesh.cloudflareaccess.com",
            cloudflare_access_audience="synthetic-audience",
            _env_file=None,
        )
        self.database = Database(healthy=healthy)
        self.state = State()
        self.http = ControlledClient()
        self.opened = False
        self.closed = False

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed = True
        await self.http.aclose()


class Access:
    def __init__(self, *, valid: bool = True) -> None:
        self.valid = valid

    async def validate(self, assertion: str) -> dict[str, str]:
        if not self.valid:
            raise AccessValidationError("synthetic denial")
        return {"sub": "synthetic"}


def test_healthz_reports_database_state_and_closes_runtime() -> None:
    runtime = Runtime()
    app = create_app(lambda: runtime)  # type: ignore[arg-type]
    with TestClient(app) as client:
        response = client.get("/healthz")
        assert runtime.opened
    assert response.status_code == 200 and response.json() == {"status": "ok"}
    assert runtime.closed

    unavailable = Runtime(healthy=False)
    with TestClient(create_app(lambda: unavailable)) as client:  # type: ignore[arg-type]
        response = client.get("/healthz")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_ops_status_requires_and_validates_access_without_personal_data() -> None:
    runtime = Runtime()
    app = create_app(lambda: runtime)  # type: ignore[arg-type]
    with TestClient(app) as client:
        assert client.get("/ops/status").status_code == 401
        app.state.access = Access(valid=False)
        denied = client.get("/ops/status", headers={"Cf-Access-Jwt-Assertion": "synthetic"})
        assert denied.status_code == 403
        app.state.access = Access()
        allowed = client.get("/ops/status", headers={"Cf-Access-Jwt-Assertion": "synthetic"})
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["dry_run"] is True and body["unsynced_leads"] == 0
    assert "email" not in str(body).lower()


def test_api_lifespan_requires_access_configuration() -> None:
    runtime = Runtime()
    runtime.settings = Settings(database_dsn="postgresql://synthetic.invalid/db", _env_file=None)
    app = create_app(lambda: runtime)  # type: ignore[arg-type]
    try:
        with TestClient(app):
            pass
    except RuntimeError as error:
        assert "Access settings" in str(error)
    else:
        raise AssertionError("missing Access settings did not fail closed")


class AggregateDatabase(Database):
    async def fetch_all(self, query: str, parameters: Sequence[Any]) -> list[Mapping[str, Any]]:
        if "integration_state" in query:
            return [
                {
                    "key": "last_run:lead_sync",
                    "value": {"at": datetime(2026, 1, 2, tzinfo=UTC).isoformat()},
                },
                {"key": "last_error:booking_sync", "value": {"at": "invalid"}},
            ]
        return [
            {
                "source": "betterstack",
                "action": "heartbeat",
                "status": "ok",
                "count": 2,
            }
        ]

    async def fetch_value(self, query: str, parameters: Sequence[Any]) -> Any:
        return 4

    async def fetch_one(self, query: str, parameters: Sequence[Any]) -> Mapping[str, Any] | None:
        return {"unsynced": 3, "aged": 1}


class AggregateState(State):
    async def kill_switch_on(self) -> bool:
        return True

    async def get(self, key: str) -> Any:
        if key == "last_backup_at":
            return {"at": datetime(2026, 1, 2, tzinfo=UTC).isoformat()}
        return None


async def test_status_service_returns_only_aggregates_and_budgets() -> None:
    settings = Settings(tis_digest="sha256:synthetic", _env_file=None)
    service = StatusService(AggregateDatabase(), AggregateState(), settings)  # type: ignore[arg-type]
    result = await service.snapshot()
    assert result.kill_switch and result.unsynced_leads == 3
    assert result.booking_errors_last_hour == 4
    assert result.jobs[0].name == "booking_sync"
    assert result.jobs[1].name == "lead_sync"
    assert result.writes_today[0].daily_budget == settings.betterstack_budget_per_day
    assert result.last_backup_at is not None and result.last_restore_test_at is None
