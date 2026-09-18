UV ?= uv
PYTHON ?= $(UV) run python
IMAGE ?= tis:local
export IMAGE
GITLEAKS_IMAGE := ghcr.io/gitleaks/gitleaks:v8.30.0@sha256:691af3c7c5a48b16f187ce3446d5f194838f91238f27270ed36eef6359a574d9

ifeq ($(OS),Windows_NT)
BASH ?= C:/Program Files/Git/bin/bash.exe
ROOT_MOUNT := $(subst \,/,$(CURDIR))
else
BASH ?= bash
ROOT_MOUNT := $(CURDIR)
endif

.PHONY: setup check test lint type guard audit license build verify-bundle tf-fmt tf-validate

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

check: lint type test guard audit license
	docker run --rm --volume "$(ROOT_MOUNT):/repo" --mount type=tmpfs,destination=/repo/.venv $(GITLEAKS_IMAGE) detect --no-git --source /repo
	$(MAKE) build

verify-bundle:
	"$(BASH)" scripts/verify_bundle.sh "$(MILESTONE)"

tf-fmt:
	terraform -chdir=infra/cloudflare fmt -check -recursive

tf-validate:
	terraform -chdir=infra/cloudflare init -backend=false -input=false
	terraform -chdir=infra/cloudflare validate
