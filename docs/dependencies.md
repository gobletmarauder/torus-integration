# Dependency register

All direct dependencies are exact-pinned in `pyproject.toml` and resolved with hashes in `uv.lock`.

## Runtime dependencies

| Dependency | Version | License | Why | Alternatives considered |
|---|---:|---|---|---|
| APScheduler | 3.11.3 | MIT | AsyncIO-native interval scheduling with overlap prevention, coalescing, and bounded misfire handling. | A custom sleep loop; rejected because correct overlap and shutdown behavior is concurrency-sensitive. |
| PyJWT | 2.14.0 | MIT | Strict local RS256 Cloudflare Access JWT validation using the existing cryptography package. It performs no network I/O. | Authlib adds broader OAuth machinery; hand-written JWT parsing is error-prone. |
| cryptography | 50.0.1 | Apache-2.0 OR BSD-3-Clause | Load the Google service-account PEM key and produce a reviewed RS256 JWT signature without adding a network-aware Google client. | `google-api-python-client` and `google-auth` could bypass `ControlledClient`; PyJWT/Authlib add unnecessary JWT abstraction; the standard library has no safe RSA signer. |
| fastapi | 0.141.1 | MIT | Typed internal health and operations endpoints with lifespan-managed resources and closed response models. | Starlette directly; rejected because FastAPI's dependency and response-model validation make the access boundary clearer. |
| pydantic | 2.13.5 | MIT | Explicit models for configuration and external payloads. | Relying on a transitive install; rejected because direct runtime dependencies must be reviewable. |
| pydantic-settings | 2.15.0 | MIT | Typed environment configuration and validation. | Hand-written environment parsing; rejected because it duplicates validation and error reporting. |
| httpx | 0.28.1 | BSD-3-Clause | Async HTTP client used only through `tis.http`. | aiohttp and requests; rejected by repository network policy. |
| psycopg | 3.3.6 | LGPL-3.0-only | Psycopg 3 async PostgreSQL interface. | asyncpg; rejected because the master plan specifies Psycopg and its pool. |
| psycopg-binary | 3.3.6 | LGPL-3.0-only | Prebuilt libpq implementation for deterministic CI/runtime installs. | Source build; rejected because final images must not contain compilers. |
| psycopg-pool | 3.3.2 | LGPL-3.0-only | Async PostgreSQL connection pooling. | Custom pooling; rejected as unsafe concurrency infrastructure. |
| uvicorn | 0.53.0 | BSD-3-Clause | Minimal pure-Python ASGI server for the internal API, without optional extras. | Hypercorn; rejected because the deployment needs one small, conventional ASGI process. |

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

## M5 host and backup-image tools

| Dependency | Version | License | Why | Alternatives considered |
|---|---:|---|---|---|
| PostgreSQL client/server | 17.6 | PostgreSQL License | `pg_dump`/`pg_restore` plus a local tmpfs server for weekly restore verification; client major is checked against the remote server. | A second Docker daemon/container for restore was rejected because the backup job must not mount the Docker socket. |
| rclone | 1.71.1 | MIT | R2 S3 transport with explicit object listing, verification, download, and narrow deletion commands. | A new AWS SDK dependency was rejected to avoid a large application dependency and a second in-process HTTP stack. |
| age | 1.2.1 | BSD-3-Clause | Encrypt every dump to two recipients before any upload and decrypt only on restore-test tmpfs. | GPG was rejected because age has a smaller key-management and command surface. |
| SOPS | 3.10.2 | MPL-2.0 | Decrypt the three reviewed production dotenv ciphertext files into `/run` tmpfs during a human deploy. | Hand-written encryption/decryption was rejected; plaintext host files are forbidden. |
| Docker Engine / Compose | 28.2.2 / 2.40.3 | Apache-2.0 | Existing host runtime; bootstrap verifies it and uses the official signed repository only when absent. | Replacing the established shared-host runtime was rejected as unsafe. |

The PostgreSQL base image is digest-pinned. rclone, age, and SOPS downloads are exact-versioned
and SHA-256 verified. These tools do not change the Python lockfile.
