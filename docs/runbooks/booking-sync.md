# Booking sync runbook

## Safe enablement

1. Confirm the Google service account has domain-wide delegation for the Calendar Events read-only scope only.
2. Put all credentials and identifiers in the SOPS-managed runtime environment. Do not put them in repository files or command output.
3. Keep `DRY_RUN=true`, enable booking sync, and inspect only redacted counters and `integration_log` status rows.
4. Confirm intended writes appear as `skipped` with source `google_calendar` and action `sync_booking`; dry run must produce no Zoho HTTP.
5. Use the normal reviewed deployment process before any live run.

## Failures

- `SyncTokenGone`: the job performs one bounded seven-day recovery. A second 410 fails and leaves the cursor unchanged.
- Google authentication failure: verify delegation, impersonated user, clock synchronization, and key rotation without printing credential values.
- Zoho invalid token or throttling: the adapter performs bounded refresh/retry. Persistent failure leaves the cursor unchanged for review.
- Deferred reschedule or cancellation: this milestone deliberately makes no Zoho mutation and does not advance the cursor. Keep the job disabled or kill-switched until a separately approved action-key design is implemented.
- Partial Zoho note/task failure: the next reviewed retry checks the event marker in related records before creating missing note/task records.

## Emergency stop and recovery

Turn on the integration kill switch or set `BOOKING_SYNC_ENABLED=false`. Preserve `integration_log` and cursor state; do not delete audit rows or move the cursor backward. Review event ids only, never attendee data. Rehaan performs any CRM cleanup manually.

If the Google credential may be exposed, keep the kill switch on, revoke domain-wide delegation or rotate the service-account key, update SOPS, and redeploy. Code never rotates credentials.

