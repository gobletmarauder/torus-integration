# Google Calendar integration

The booking sync uses a service account with domain-wide delegation and impersonates the configured `GOOGLE_IMPERSONATED_USER`. It requests only:

`https://www.googleapis.com/auth/calendar.events.readonly`

The implementation signs an RS256 JWT locally, exchanges it at the configured `GOOGLE_TOKEN_URL`, and reads events from `GOOGLE_CALENDAR_API_URL` through `tis.http`. It does not use Google SDKs and never writes to Calendar.

Required runtime settings are documented in `.env.example`. Store their real values only in the SOPS-managed runtime environment. Never commit or paste the service-account key, calendar id, impersonated user, or tokens.

The cursor is stored at `integration_state.key = 'google_calendar:handoff_review'`. It contains Google's opaque sync token plus a bounded set of event-id/start/status fingerprints. Initial reads and one recovery from an expired sync token use a seven-day window. Cursor state advances only after every selected event is accounted for and no write failed. Dry run never advances it.

The committed fixture is a synthetic replacement that preserves the captured response shape without names, addresses, phone numbers, meeting links, calendar ids, tokens, or event ids from production.

