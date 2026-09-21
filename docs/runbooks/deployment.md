# Torus deployment and rollback

Run only after G3 and a tagged release. The host checkout must be clean and the three SOPS
ciphertexts must exist. As `rehaanmerchant` (never with `sudo docker`):

The human-installed `/etc/torus/age/tis.key` must be `root:rehaanmerchant` mode `0640`, inside
the bootstrap-created `root:rehaanmerchant` mode `0750` directory. This gives only root and the
single deploy user access; never place the key in the checkout, dotenv files, or Docker images.

1. Capture the shared-host before-state from the M5 G4 checklist in `PROGRESS.md`.
2. Run `deploy/deploy.sh vX.Y.Z --dry-run`.
3. Confirm the script reports digest equality, smoke PASS, and removal of `/run/torus/torus-*.env`.
4. Leave dry run active for 30 minutes and review aggregate status and skipped audit rows.

Smoke failure invokes rollback automatically. For a reviewed manual rollback, run
`deploy/rollback.sh`; it uses only `torus-previous.env`, the Torus Compose project, and the current
encrypted secrets. If rollback smoke also fails, stop the Torus project only, preserve redacted
logs, and do not change other containers, firewall rules, remote-login configuration, or Docker's
data root.
