# Zoho Lead fields used by M2

These API names were supplied as a redacted contract. They contain no record values or credentials.

| Canonical value | Zoho API name | Rule |
|---|---|---|
| Supabase lead UUID | `supabase_lead_id` | Custom Single Line field; must be unique and is the upsert duplicate key. |
| First name | `First_Name` | Text before the first space; omitted for a single-word name. |
| Last name | `Last_Name` | Required; entire value for a single-word name. |
| Email | `Email` | Direct mapping; never logged. |
| Company | `Company` | Supplied company or email-domain fallback. |
| Calculator and attribution context | `Description` | Deterministic labeled block; never logged. |
| Attribution | `Lead_Source` | Optional configured value `Website`; omit if the picklist lacks it. |

The executable non-secret mapping is `config/zoho_lead_fields.toml`. Rehaan confirms the exact custom field API name and `Website` picklist value in Zoho before live enablement. M2 does not call the settings metadata API.
