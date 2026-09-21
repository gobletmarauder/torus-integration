"""Dependency assembly for scheduler and API processes."""

from __future__ import annotations

from dataclasses import dataclass

from tis.config import Settings, get_settings
from tis.db import PsycopgDatabase
from tis.guards import PostgresAuditStore, WriteContext
from tis.http import ControlledClient, client
from tis.integrations.google_calendar import GoogleCalendarAuth
from tis.integrations.zoho import ZohoAuth
from tis.jobs.booking_sync import BookingSyncContext
from tis.jobs.lead_sync import LeadSyncContext, PostgresLeadStore
from tis.mapping.booking_parser import load_booking_field_map
from tis.mapping.lead_to_zoho import load_field_map
from tis.state import StateStore


@dataclass
class Runtime:
    """Own shared process resources; opening and closing affect DB/HTTP pools."""

    settings: Settings
    database: PsycopgDatabase
    state: StateStore
    audit: PostgresAuditStore
    writes: WriteContext
    http: ControlledClient
    lead: LeadSyncContext | None
    booking: BookingSyncContext | None

    def new_writes(self) -> WriteContext:
        """Return fresh per-run counters over shared state and audit stores."""
        return _write_context(self.settings, self.state, self.audit)

    async def open(self) -> None:
        """Open the configured database pool."""
        await self.database.open()

    async def close(self) -> None:
        """Close HTTP and database pools without issuing requests."""
        await self.http.aclose()
        await self.database.close()


def build_runtime(settings: Settings | None = None) -> Runtime:
    """Assemble runtime dependencies without opening network connections."""
    configured = settings or get_settings()
    if not configured.database_dsn:
        raise RuntimeError("DATABASE_DSN is required for runtime processes")
    database = PsycopgDatabase(configured.database_dsn)
    state = StateStore(database)
    audit = PostgresAuditStore(database)
    writes = _write_context(configured, state, audit)
    http = client()
    zoho = _zoho_auth(configured)
    lead = _lead_context(configured, database, writes, http, zoho)
    booking = _booking_context(configured, state, writes, http, zoho)
    return Runtime(configured, database, state, audit, writes, http, lead, booking)


def _write_context(
    settings: Settings, state: StateStore, audit: PostgresAuditStore
) -> WriteContext:
    return WriteContext(
        dry_run=settings.dry_run,
        state=state,
        audit=audit,
        per_run_budgets={
            ("posthog", "capture"): settings.posthog_budget_per_run,
            ("betterstack", "heartbeat"): settings.betterstack_budget_per_run,
            ("zoho", "upsert_lead"): settings.zoho_create_budget_per_run,
            ("google_calendar", "sync_booking"): settings.zoho_booking_budget_per_run,
        },
        per_day_budgets={
            ("posthog", "capture"): settings.posthog_budget_per_day,
            ("betterstack", "heartbeat"): settings.betterstack_budget_per_day,
            ("zoho", "upsert_lead"): settings.zoho_create_budget_per_day,
            ("google_calendar", "sync_booking"): settings.zoho_booking_budget_per_day,
        },
    )


def _zoho_auth(settings: Settings) -> ZohoAuth | None:
    client_id = settings.zoho_client_id
    client_secret = settings.zoho_client_secret
    refresh_token = settings.zoho_refresh_token
    accounts_url = settings.zoho_accounts_url
    if client_id is None or client_secret is None or refresh_token is None or accounts_url is None:
        return None
    return ZohoAuth(
        client_id=client_id.get_secret_value(),
        client_secret=client_secret.get_secret_value(),
        refresh_token=refresh_token.get_secret_value(),
        accounts_url=str(accounts_url),
    )


def _lead_context(
    settings: Settings,
    database: PsycopgDatabase,
    writes: WriteContext,
    http: ControlledClient,
    zoho: ZohoAuth | None,
) -> LeadSyncContext | None:
    if not settings.lead_sync_enabled:
        return None
    if zoho is None or settings.zoho_api_url is None:
        raise RuntimeError("lead synchronization configuration is incomplete")
    return LeadSyncContext(
        writes=writes,
        store=PostgresLeadStore(database),
        http=http,
        auth=zoho,
        field_map=load_field_map(settings.zoho_lead_field_map_path),
        api_url=str(settings.zoho_api_url),
        api_version=settings.zoho_api_version,
    )


def _booking_context(
    settings: Settings,
    state: StateStore,
    writes: WriteContext,
    http: ControlledClient,
    zoho: ZohoAuth | None,
) -> BookingSyncContext | None:
    if not settings.booking_sync_enabled:
        return None
    api_url = settings.zoho_api_url
    service_email = settings.google_service_account_email
    private_key = settings.google_service_account_private_key
    impersonated_user = settings.google_impersonated_user
    calendar_id = settings.google_calendar_id
    token_url = settings.google_token_url
    calendar_url = settings.google_calendar_api_url
    if (
        zoho is None
        or api_url is None
        or service_email is None
        or private_key is None
        or impersonated_user is None
        or calendar_id is None
        or token_url is None
        or calendar_url is None
    ):
        raise RuntimeError("booking synchronization configuration is incomplete")
    google = GoogleCalendarAuth(
        service_account_email=service_email.get_secret_value(),
        private_key=private_key.get_secret_value(),
        impersonated_user=impersonated_user.get_secret_value(),
        token_url=str(token_url),
    )
    return BookingSyncContext(
        writes=writes,
        state=state,
        http=http,
        google_auth=google,
        zoho_auth=zoho,
        google_api_url=str(calendar_url),
        calendar_id=calendar_id.get_secret_value(),
        zoho_api_url=str(api_url),
        lead_fields=load_field_map(settings.zoho_lead_field_map_path),
        booking_fields=load_booking_field_map(settings.zoho_booking_field_map_path),
        lookback_days=settings.google_booking_lookback_days,
    )
