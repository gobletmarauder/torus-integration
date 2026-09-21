"""Internal FastAPI health and Access-protected operations endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from tis.api.access import AccessValidationError, AccessValidator
from tis.api.status import OpsStatus, StatusService
from tis.runtime import Runtime, build_runtime

RuntimeFactory = Callable[[], Runtime]


def create_app(runtime_factory: RuntimeFactory = build_runtime) -> FastAPI:
    """Create the internal API; process lifespan opens shared DB/HTTP resources."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime = runtime_factory()
        settings = runtime.settings
        if (
            settings.cloudflare_access_team_domain is None
            or settings.cloudflare_access_audience is None
        ):
            raise RuntimeError("Cloudflare Access settings are required for the API")
        await runtime.open()
        app.state.runtime = runtime
        app.state.access = AccessValidator(
            http=runtime.http,
            team_domain=settings.cloudflare_access_team_domain,
            audience=settings.cloudflare_access_audience.get_secret_value(),
        )
        app.state.status = StatusService(runtime.database, runtime.state, settings)
        try:
            yield
        finally:
            await runtime.close()

    app = FastAPI(
        title="Torus Integration Service",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.get("/healthz", include_in_schema=False)
    async def healthz(request: Request) -> JSONResponse:
        """Return success only when the service database is reachable."""
        runtime = cast(Runtime, request.app.state.runtime)
        try:
            await runtime.database.fetch_value("SELECT 1", ())
        except Exception:
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ok"})

    @app.get("/ops/status", response_model=OpsStatus, include_in_schema=False)
    async def ops_status(
        request: Request,
        assertion: str | None = Header(default=None, alias="Cf-Access-Jwt-Assertion"),
    ) -> OpsStatus:
        """Return non-personal aggregates after validating Cloudflare Access."""
        if assertion is None:
            raise HTTPException(status_code=401, detail="Access assertion required")
        validator = cast(AccessValidator, request.app.state.access)
        try:
            await validator.validate(assertion)
        except AccessValidationError as error:
            raise HTTPException(status_code=403, detail="Access assertion invalid") from error
        status = cast(StatusService, request.app.state.status)
        return await status.snapshot()

    return app


app = create_app()
