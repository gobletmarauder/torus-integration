# Production ciphertext inventory

Only Rehaan creates or edits these SOPS-encrypted dotenv files:

- `tis.enc.env`: application settings only.
- `cloudflared.enc.env`: the Torus tunnel token only.
- `backup.enc.env`: backup database, R2, age-recipient, restore-test, heartbeat, and temporary
  deployment-release settings. Deploy tooling removes the release fields before this env file is
  passed into the profile-only backup container.

Plaintext files are ignored. Codex and CI never receive the age private key and never run SOPS.
Before G4, replace the public recipient placeholder in `.sops.yaml`, create all three files with
SOPS, and confirm their tracked form contains SOPS metadata rather than plaintext values.
Install the private key separately at `/etc/torus/age/tis.key` as `root:rehaanmerchant` mode
`0640`; the bootstrap-created parent directory is `root:rehaanmerchant` mode `0750`.
