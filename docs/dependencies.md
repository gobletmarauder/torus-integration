# Dependency register

M0 has no runtime dependencies. The following direct development dependencies are exact-pinned in `pyproject.toml` and resolved with hashes in `uv.lock`.

| Dependency | Version | License | Why | Alternatives considered |
|---|---:|---|---|---|
| ruff | 0.16.8 | MIT | Fast linting and deterministic formatting in G1/G2. | Flake8 + Black + isort; rejected because three tools increase configuration and dependency surface. |
| mypy | 2.1.0 | MIT | Strict static type checking for `src/tis`. | Pyright; rejected to match the master plan and Python-first local tooling. |
| pytest | 9.0.3 | MIT | Unit and contract test runner. | `unittest`; rejected because pytest fixtures make isolated guard repositories concise. |
| pytest-cov | 7.1.0 | MIT | Coverage measurement and the required 85% threshold. | Direct coverage.py invocation; rejected because pytest integration produces one consistent test command. |
| pip-audit | 2.10.1 | Apache-2.0 | Audit the locked Python dependency graph for known vulnerabilities. | Safety; rejected in favor of the PyPA-maintained tool required by the master plan. |
| pip-licenses | 5.5.5 | MIT | Inventory licenses and reject GPL/AGPL packages. | Custom metadata parsing; rejected because standardized package metadata has edge cases already handled here. |

Non-Python developer/CI executables are not project dependencies: uv manages the lock/environment; Docker/Buildx builds the image; gitleaks scans for secrets; Trivy scans the image and produces the SBOM; Terraform is invoked only for formatting and validation when infrastructure files exist.

