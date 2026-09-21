# Encrypted backup and restore test

`torus-backup.timer` runs nightly and `torus-restore-test.timer` runs weekly. Both invoke the
profile-only `torus-backup` Compose job as `rehaanmerchant` with no Docker socket.
Each unit decrypts the three reviewed ciphertext files into `/run/torus`, loads the current
release digests, strips release-only fields from the backup environment, and removes every
plaintext dotenv file through an exit/signal trap.

- Backup plaintext and restore databases exist only under container tmpfs and are removed by traps.
- Only `torus-backup-YYYY-MM-DD.dump.gz.age` objects may be uploaded or deleted.
- Retention keeps the newest seven daily objects and four older weekly representatives.
- A heartbeat is sent only after verified upload or successful aggregate restore checks.

On failure, inspect `journalctl -u torus-backup.service` or
`journalctl -u torus-restore-test.service`. Never paste environment output. Disable only the
failing `torus-*` timer while investigating. Preserve R2 ciphertext; do not manually delete it.
