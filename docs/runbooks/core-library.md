# Core library failure runbook

## Safety first

Keep `DRY_RUN=true` while investigating. If writes may be duplicating or exceeding expected
volume, turn on the administrative kill switch. Never paste credentials, raw request payloads,
personal data, or heartbeat URLs into logs or issues.

## Egress denied

An `EgressDenied` error means a request or redirect did not match the exact M1 allowlist. Confirm
the configured hostname, including redirects. Do not broaden the allowlist during an incident;
route any required host addition through a new approved G0 plan.

## External service errors

Check the redacted status code and correlation id. Idempotent reads retry only a bounded number of
times; unsafe methods do not retry implicitly. Leave dry run enabled until the provider and local
configuration are known-good.

## Kill switch or budget blocks

`KillSwitchOn` is expected while the administrative switch is enabled. `BudgetExceeded` means the
per-run or UTC-day ceiling was reached. Investigate the triggering schedule and audit counts; do
not increase a budget without an approved plan.

## Database failures

The pool uses a ten-second statement timeout and transactional rollback. Confirm database
availability and the service-role configuration without printing the DSN. The core library never
creates or alters tables. Schema drift must be reported before changing SQL.

## Recovery

After correcting the cause, verify in dry run that the intended write produces one `skipped`
audit row and no HTTP call. Then follow the milestone gates before re-enabling live writes.
