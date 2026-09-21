UV ?= uv
PYTHON ?= $(UV) run python
IMAGE ?= tis:local
export IMAGE
BACKUP_IMAGE ?= tis-backup:local
GITLEAKS_IMAGE := ghcr.io/gitleaks/gitleaks:v8.30.0@sha256:691af3c7c5a48b16f187ce3446d5f194838f91238f27270ed36eef6359a574d9

ifeq ($(OS),Windows_NT)
BASH ?= C:/Program Files/Git/bin/bash.exe
ROOT_MOUNT := $(subst \,/,$(CURDIR))
else
BASH ?= bash
ROOT_MOUNT := $(CURDIR)
endif

.PHONY: setup check test lint type guard audit license build image-size backup-image backup-image-check compose-config verify-bundle tf-fmt tf-validate tf-init tf-lint tf-plan tf-gate tf-apply

TF_DIR := infra/cloudflare
TF_VARS ?= $(TF_DIR)/terraform.tfvars
TF_PLAN := $(TF_DIR)/plan.tfplan
TF_PLAN_JSON := $(TF_DIR)/plan.json
TF_PLAN_TEXT := $(TF_DIR)/plan.txt

setup:
	$(UV) sync --frozen

lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .

type:
	$(UV) run mypy src/tis

test:
	$(UV) run pytest

guard:
	$(PYTHON) scripts/guard.py

audit:
	$(UV) run pip-audit

license:
	$(UV) run pip-licenses --fail-on="GNU General Public License;GNU Affero General Public License;GPL;AGPL"

build:
	docker build --tag $(IMAGE) .

image-size: build
	$(PYTHON) scripts/check_image.py $(IMAGE)

backup-image:
	docker build --file deploy/backup/Dockerfile --tag $(BACKUP_IMAGE) .

backup-image-check: backup-image
	docker image inspect $(BACKUP_IMAGE) --format '{{.Config.User}}'
	docker run --rm --entrypoint pg_dump $(BACKUP_IMAGE) --version
	docker run --rm --entrypoint rclone $(BACKUP_IMAGE) version
	docker run --rm --entrypoint age $(BACKUP_IMAGE) --version
	docker run --rm --entrypoint sh $(BACKUP_IMAGE) -c 'for binary in apt apt-get dpkg gosu curl wget gcc cc make go; do ! command -v "$$binary" || exit 1; done'

compose-config:
	docker compose --env-file tests/fixtures/compose/synthetic.env -f deploy/compose.yaml config --quiet

check: lint type test guard audit license
	docker run --rm --volume "$(ROOT_MOUNT):/repo" --mount type=tmpfs,destination=/repo/.venv $(GITLEAKS_IMAGE) detect --no-git --source /repo
	$(MAKE) build

verify-bundle:
	"$(BASH)" scripts/verify_bundle.sh "$(MILESTONE)"

tf-fmt:
	terraform -chdir=$(TF_DIR) fmt -check -recursive

tf-validate:
	terraform -chdir=$(TF_DIR) init -backend=false -input=false
	terraform -chdir=$(TF_DIR) validate

tf-init:
	terraform -chdir=$(TF_DIR) init -input=false

tf-lint:
	tflint --chdir=$(TF_DIR) --config=.tflint.hcl

tf-plan:
	terraform -chdir=$(TF_DIR) plan -input=false -var-file=terraform.tfvars -out=plan.tfplan
	terraform -chdir=$(TF_DIR) show -no-color plan.tfplan > $(TF_PLAN_TEXT)
	terraform -chdir=$(TF_DIR) show -json plan.tfplan > $(TF_PLAN_JSON)

tf-gate:
	$(PYTHON) scripts/tf_gate.py $(TF_PLAN_JSON) --tfvars $(TF_VARS)

tf-apply: tf-gate
	$(PYTHON) -c "from pathlib import Path; assert Path(r'$(TF_PLAN)').is_file(), 'saved plan file is missing'"
	terraform -chdir=$(TF_DIR) apply -input=false plan.tfplan
