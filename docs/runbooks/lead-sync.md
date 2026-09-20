# Lead sync failure runbook

The M2 slice is disabled by default and production writes remain blocked while `DRY_RUN=true`.

## Before enabling

1. Confirm the human-applied `leads` migration provides `is_test`, `crm_synced_at`, and `zoho_lead_id` with the redacted contract recorded in `PROGRESS.md`.
2. Confirm Zoho has a unique Lead field whose API name matches `supabase_lead_id` in `config/zoho_lead_fields.toml`.
3. Confirm `Website` exists in the `Lead_Source` picklist, or remove the configured value so the field is omitted.
4. Run the G4 dry run and verify `integration_log` contains only `skipped` rows and Zoho contains no new test record.

## Failures

- `ZohoDataError`: inspect the field API names and required-field configuration using only redacted metadata. The source row remains unsynced and its bounded error class is recorded.
- Repeated authentication error: turn on the kill switch, rotate/re-authorize the Zoho credential through the password manager and SOPS workflow, then redeploy. Never paste the credential into an issue, PR, log, or command output.
- Rate-limit or service error: leave the job enabled only if attempts remain below ten; the next scheduler run retries the unsynced row. Turn on the kill switch if write volume is unexpected.
- Attempts reached ten: keep the row unsynced, correct the mapping or source data through the owning system, then have a human reset the attempt counter through the approved admin path. Do not edit production data from Codex.
- Suspected duplicate/wrong record: turn on the kill switch immediately. Use the Supabase UUID and `integration_log` metadata to identify the intended operation; clean up Zoho manually only after review.

## Rollback

Disable `LEAD_SYNC_ENABLED` or turn on the kill switch, roll back the service image, and preserve `integration_log` and lead status columns. Never delete audit evidence or automatically move retry state backward.
