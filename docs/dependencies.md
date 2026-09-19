# Dependency register

All direct dependencies are exact-pinned in `pyproject.toml` and resolved with hashes in `uv.lock`.

## Runtime dependencies

| Dependency | Version | License | Why | Alternatives considered |
|---|---:|---|---|---|
| pydantic | 2.13.5 | MIT | Explicit models for configuration and external payloads. | Relying on a transitive install; rejected because direct runtime dependencies must be reviewable. |
| pydantic-settings | 2.15.0 | MIT | Typed environment configuration and validation. | Hand-written environment parsing; rejected because it duplicates validation and error reporting. |
| httpx | 0.28.1 | BSD-3-Clause | Async HTTP client used only through `tis.http`. | aiohttp and requests; rejected by repository network policy. |
| psycopg | 3.3.6 | LGPL-3.0-only | Psycopg 3 async PostgreSQL interface. | asyncpg; rejected because the master plan specifies Psycopg and its pool. |
| psycopg-binary | 3.3.6 | LGPL-3.0-only | Prebuilt libpq implementation for deterministic CI/runtime installs. | Source build; rejected because final images must not contain compilers. |
| psycopg-pool | 3.3.2 | LGPL-3.0-only | Async PostgreSQL connection pooling. | Custom pooling; rejected as unsafe concurrency infrastructure. |

## Development dependencies

| Dependency | Version | License | Why | Alternatives considered |
|---|---:|---|---|---|
| ruff | 0.16.8 | MIT | Fast linting and deterministic formatting in G1/G2. | Flake8 + Black + isort; rejected because three tools increase configuration and dependency surface. |
| mypy | 2.1.0 | MIT | Strict static type checking for `src/tis`. | Pyright; rejected to match the master plan and Python-first local tooling. |
| pytest | 9.0.3 | MIT | Unit and contract test runner. | `unittest`; rejected because pytest fixtures make isolated guard repositories concise. |
| pytest-cov | 7.1.0 | MIT | Coverage measurement and the required 85% threshold. | Direct coverage.py invocation; rejected because pytest integration produces one consistent test command. |
| pip-audit | 2.10.1 | Apache-2.0 | Audit the locked Python dependency graph for known vulnerabilities. | Safety; rejected in favor of the PyPA-maintained tool required by the master plan. |
| pip-licenses | 5.5.5 | MIT | Inventory licenses and reject GPL/AGPL packages. | Custom metadata parsing; rejected because standardized package metadata has edge cases already handled here. |
| respx | 0.23.1 | BSD-3-Clause | Mock and assert HTTPX requests without real network access. | Hand-written transports; rejected because routing and unexpected-request assertions would be weaker. |

Non-Python developer/CI executables are not project dependencies: uv manages the lock/environment; Docker/Buildx builds the image; gitleaks scans for secrets; Trivy scans the image and produces the SBOM; Terraform is invoked only for formatting and validation when infrastructure files exist.

