#!/usr/bin/env bash
set -euo pipefail

milestone="${1:-}"
if [[ -z "$milestone" ]]; then
  echo "usage: scripts/verify_bundle.sh <MILESTONE>" >&2
  exit 2
fi

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

head_commit="$(git rev-parse HEAD)"
short_sha="$(git rev-parse --short=8 HEAD)"
branch="$(git branch --show-current)"
if git rev-parse --verify --quiet origin/main >/dev/null; then
  base_commit="$(git merge-base HEAD origin/main)"
else
  base_commit="$(git merge-base HEAD main)"
fi

output_dir="docs/bundles"
mkdir -p "$output_dir"
output_base="$output_dir/${milestone}-${short_sha}"
temporary_dir="$(mktemp -d)"
temporary_bundle="$temporary_dir/bundle.md"
trap 'rm -rf "$temporary_dir"' EXIT

overall_failed=0
guard_status="FAIL"
gitleaks_status="FAIL"
trivy_status="FAIL"
checks_status="PASS"

section() {
  printf '\n## %s. %s\n\n' "$1" "$2" >>"$temporary_bundle"
}

code_block() {
  printf '```text\n' >>"$temporary_bundle"
  cat >>"$temporary_bundle"
  printf '\n```\n' >>"$temporary_bundle"
}

run_check() {
  local label="$1"
  shift
  local captured
  printf '### %s\n\n' "$label" >>"$temporary_bundle"
  if captured="$("$@" 2>&1)"; then
    printf 'PASS\n\n' >>"$temporary_bundle"
  else
    printf 'FAIL\n\n' >>"$temporary_bundle"
    checks_status="FAIL"
    overall_failed=1
  fi
  printf '%s\n' "$captured" | code_block
}

cat >"$temporary_bundle" <<EOF
# Verification bundle: $milestone
EOF

section 1 "Header"
cat >>"$temporary_bundle" <<EOF
- Milestone: $milestone
- Branch: $branch
- Base commit: $base_commit
- Head commit: $head_commit
- Generated (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)
- Codex task ids: M0.1, M0.2, M0.3, M0.4, M0.5, M0.6, M0.7, M0.8
EOF

section 2 "G0 plan"
awk '/^### M0 G0 plan /{copy=1} /^\*\*G1 evidence\*\*/{copy=0} copy' PROGRESS.md >>"$temporary_bundle"

section 3 "Scope check"
printf '| Status | File | In plan |\n|---|---|---|\n' >>"$temporary_bundle"
while IFS=$'\t' read -r status path; do
  [[ -z "${path:-}" ]] && continue
  if grep -Fq "\`$path\`" PROGRESS.md; then
    in_plan="yes"
  else
    in_plan="no"
    overall_failed=1
  fi
  printf '| %s | `%s` | %s |\n' "$status" "$path" "$in_plan" >>"$temporary_bundle"
done < <(git diff --name-status "$base_commit...$head_commit")

section 4 "Protected paths"
protected_changed="$temporary_dir/protected-changed.txt"
git diff --name-only "$base_commit...$head_commit" | awk '
  $0 == "AGENTS.md" || $0 == ".sops.yaml" ||
  $0 == "scripts/guard.py" || $0 == "scripts/verify_bundle.sh" ||
  $0 == "src/tis/http.py" || $0 == "src/tis/guards.py" ||
  $0 ~ /^\.github\// || $0 ~ /^deploy\// || $0 ~ /^infra\// || $0 ~ /^secrets\//
' >"$protected_changed"
printf 'Changed protected files:\n\n' >>"$temporary_bundle"
sed 's/^/- `/' "$protected_changed" | sed 's/$/`/' >>"$temporary_bundle"
printf '\nProtected-file SHA-256 values at head:\n\n' >>"$temporary_bundle"
git ls-files | awk '
  $0 == "AGENTS.md" || $0 == ".sops.yaml" ||
  $0 == "scripts/guard.py" || $0 == "scripts/verify_bundle.sh" ||
  $0 == "src/tis/http.py" || $0 == "src/tis/guards.py" ||
  $0 ~ /^\.github\// || $0 ~ /^deploy\// || $0 ~ /^infra\// || $0 ~ /^secrets\//
' | while IFS= read -r path; do
  printf -- '- `%s` `%s`\n' "$path" "$(sha256sum "$path" | awk '{print $1}')" >>"$temporary_bundle"
done
printf '\nFull protected diffs:\n\n```diff\n' >>"$temporary_bundle"
if [[ -s "$protected_changed" ]]; then
  mapfile -t protected_paths <"$protected_changed"
  git diff "$base_commit...$head_commit" -- "${protected_paths[@]}" >>"$temporary_bundle"
fi
printf '\n```\n' >>"$temporary_bundle"

section 5 "Dependencies"
printf '### pyproject.toml diff\n\n```diff\n' >>"$temporary_bundle"
git diff "$base_commit...$head_commit" -- pyproject.toml >>"$temporary_bundle" || true
printf '\n```\n\n### uv.lock package/version summary\n\n```text\n' >>"$temporary_bundle"
git diff "$base_commit...$head_commit" -- uv.lock | grep -E '^[+-](name|version) = ' >>"$temporary_bundle" || true
printf '\n```\n\n### docs/dependencies.md diff\n\n```diff\n' >>"$temporary_bundle"
git diff "$base_commit...$head_commit" -- docs/dependencies.md >>"$temporary_bundle" || true
printf '\n```\n\n### Installed license list\n\n' >>"$temporary_bundle"
uv run pip-licenses --format=plain-vertical 2>&1 | code_block

section 6 "Egress allowlist"
printf '```diff\n' >>"$temporary_bundle"
git diff "$base_commit...$head_commit" -- src/tis/http.py >>"$temporary_bundle" || true
printf '\n```\n' >>"$temporary_bundle"

section 7 "Scopes and privileges"
printf '```text\n' >>"$temporary_bundle"
git grep -n -E 'scope|privilege|ENV|DRY_RUN|BUDGET|DROP|TRUNCATE|ALTER|GRANT|REVOKE|CREATE ROLE|DELETE' -- ':!docs/bundles/**' >>"$temporary_bundle" || true
printf '\n```\n' >>"$temporary_bundle"

section 8 "External writes"
printf 'Decorated functions and non-GET HTTP call review:\n\n```text\n' >>"$temporary_bundle"
git grep -n -E '@external_write|http\.client\(|client\.(post|put|patch|delete)\(' -- 'src/**' >>"$temporary_bundle" || true
printf '\n```\n' >>"$temporary_bundle"

section 9 "Guard output"
if guard_output="$(uv run python scripts/guard.py --base "$base_commit" 2>&1)"; then
  guard_status="PASS"
else
  overall_failed=1
fi
printf '%s\n' "$guard_output" | code_block

section 10 "Checks summary"
run_check "ruff check" uv run ruff check .
run_check "ruff format check" uv run ruff format --check .
run_check "mypy" uv run mypy src/tis
run_check "pytest and coverage" uv run pytest
run_check "pip-audit" uv run pip-audit
run_check "license policy" uv run pip-licenses --fail-on="GNU General Public License;GNU Affero General Public License;GPL;AGPL"

printf '### gitleaks\n\n' >>"$temporary_bundle"
gitleaks_image="ghcr.io/gitleaks/gitleaks:v8.30.0@sha256:691af3c7c5a48b16f187ce3446d5f194838f91238f27270ed36eef6359a574d9"
if gitleaks_output="$(MSYS_NO_PATHCONV=1 docker run --rm --volume "$repo_root:/repo" --mount type=tmpfs,destination=/repo/.venv "$gitleaks_image" detect --no-git --source /repo 2>&1)"; then
  gitleaks_status="PASS"
  printf 'PASS\n\n' >>"$temporary_bundle"
else
  overall_failed=1
  printf 'FAIL\n\n' >>"$temporary_bundle"
fi
printf '%s\n' "$gitleaks_output" | code_block

printf '### Docker image\n\n' >>"$temporary_bundle"
if docker_output="$(docker image inspect tis:m0-local --format 'image={{.Id}} size={{.Size}}' 2>&1)"; then
  printf 'PASS\n\n' >>"$temporary_bundle"
else
  overall_failed=1
  printf 'FAIL\n\n' >>"$temporary_bundle"
fi
printf '%s\n' "$docker_output" | code_block

printf '### Trivy image scan\n\n' >>"$temporary_bundle"
trivy_image="ghcr.io/aquasecurity/trivy:0.69.3@sha256:bcc376de8d77cfe086a917230e818dc9f8528e3c852f7b1aff648949b6258d1c"
docker save --output "$temporary_dir/tis-image.tar" tis:m0-local
if trivy_output="$(MSYS_NO_PATHCONV=1 docker run --rm --volume "$temporary_dir:/scan" "$trivy_image" image --input /scan/tis-image.tar --ignore-unfixed --severity HIGH,CRITICAL --exit-code 1 --no-progress 2>&1)"; then
  trivy_status="PASS"
  printf 'PASS\n\n' >>"$temporary_bundle"
else
  overall_failed=1
  printf 'FAIL\n\n' >>"$temporary_bundle"
fi
printf '%s\n' "$trivy_output" | code_block

section 11 "Tests added"
printf 'Added or changed tests:\n\n```text\n' >>"$temporary_bundle"
git diff --unified=0 "$base_commit...$head_commit" -- tests | grep -E '^\+[[:space:]]*(async[[:space:]]+)?def test_' | sed 's/^+//' >>"$temporary_bundle" || true
printf '\n```\n\nSkip, xfail, and deleted-test audit:\n\n```text\n' >>"$temporary_bundle"
git diff --unified=0 "$base_commit...$head_commit" -- tests | grep -E '^[+-].*(skip|xfail|def test_)' >>"$temporary_bundle" || true
printf '\n```\n' >>"$temporary_bundle"

section 12 "Source diff"
printf '```diff\n' >>"$temporary_bundle"
git diff "$base_commit...$head_commit" -- 'src/tis/**' >>"$temporary_bundle" || true
printf '\n```\n' >>"$temporary_bundle"

section 13 "Infra"
if git diff --quiet "$base_commit...$head_commit" -- infra/; then
  printf 'No infrastructure changes. Terraform commands were not run.\n' >>"$temporary_bundle"
else
  run_check "terraform fmt" make tf-fmt
  run_check "terraform validate" make tf-validate
fi

section 14 "Previous verdict"
previous_verdict="$(awk '/^\*\*G3 verdict/{copy=1; next} /^\*\*Decisions made/{copy=0} copy' PROGRESS.md)"
if [[ -n "$previous_verdict" && "$previous_verdict" != *"PASS/FAIL"* ]]; then
  printf '%s\n' "$previous_verdict" >>"$temporary_bundle"
else
  printf 'No previous G3 verdict for %s.\n' "$milestone" >>"$temporary_bundle"
fi

section 15 "Codex notes"
cat >>"$temporary_bundle" <<'EOF'
### Security notes

No secrets, production credentials, personal data, service egress, or production writes were added.

### Open questions

None.

### Deviations from plan

None.
EOF

bundle_scan_dir="/repo/docs/bundles"
cp "$temporary_bundle" "${output_base}.md"
if ! MSYS_NO_PATHCONV=1 docker run --rm --volume "$repo_root:/repo" "$gitleaks_image" detect --no-git --source "$bundle_scan_dir" >/dev/null 2>&1; then
  rm -f "${output_base}.md" "${output_base}"-part*.md
  echo "verify-bundle: generated bundle failed its gitleaks scan" >&2
  exit 1
fi

bundle_paths=()
if [[ "$(wc -c <"${output_base}.md")" -le 40000 ]]; then
  bundle_paths+=("${output_base}.md")
else
  split -b 38000 -d -a 2 "${output_base}.md" "${output_base}-chunk"
  rm -f "${output_base}.md"
  part=1
  for chunk in "${output_base}"-chunk*; do
    part_path="${output_base}-part${part}.md"
    mv "$chunk" "$part_path"
    bundle_paths+=("$part_path")
    part=$((part + 1))
  done
fi

printf 'Bundle path(s): %s\n' "${bundle_paths[*]}"
printf 'Summary: sections=15 checks=%s guard=%s gitleaks=%s trivy=%s protected_changes=%s\n' \
  "$checks_status" "$guard_status" "$gitleaks_status" "$trivy_status" "$(wc -l <"$protected_changed" | tr -d ' ')"

if [[ "$overall_failed" -ne 0 ]]; then
  echo "verify-bundle: FAIL (bundle retained for diagnosis)" >&2
  exit 1
fi
echo "verify-bundle: PASS"
