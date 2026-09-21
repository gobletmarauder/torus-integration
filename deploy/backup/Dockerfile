FROM python:3.12.14-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9 AS python-builder
COPY --from=ghcr.io/astral-sh/uv:0.11.30@sha256:93b61e21202b1dab861092748e46bbd6e0e41dd84f59b9174efd2353186e1b47 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM postgres:17.6-bookworm@sha256:f3bd19c606e442c3d7bdfa8002e03fe260a1023351e0ea4598032022b68dd6e3 AS tools
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*
ARG RCLONE_URL=https://github.com/rclone/rclone/releases/download/v1.71.1/rclone-v1.71.1-linux-amd64.zip
ARG RCLONE_SHA256=417e3da236f3a12d292da4e7287d67b1df558b8c2b280d092e563958ed724be7
ARG AGE_URL=https://github.com/FiloSottile/age/releases/download/v1.2.1/age-v1.2.1-linux-amd64.tar.gz
ARG AGE_SHA256=7df45a6cc87d4da11cc03a539a7470c15b1041ab2b396af088fe9990f7c79d50
RUN curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error "$RCLONE_URL" -o /tmp/rclone.zip \
    && echo "$RCLONE_SHA256  /tmp/rclone.zip" | sha256sum --check --status \
    && unzip -q /tmp/rclone.zip -d /tmp/rclone \
    && mkdir -p /out \
    && install -m 0755 /tmp/rclone/rclone-v1.71.1-linux-amd64/rclone /out/rclone
RUN curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error "$AGE_URL" -o /tmp/age.tar.gz \
    && echo "$AGE_SHA256  /tmp/age.tar.gz" | sha256sum --check --status \
    && tar -xzf /tmp/age.tar.gz -C /tmp \
    && install -m 0755 /tmp/age/age /out/age

FROM postgres:17.6-bookworm@sha256:f3bd19c606e442c3d7bdfa8002e03fe260a1023351e0ea4598032022b68dd6e3
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PATH=/app/.venv/bin:/usr/lib/postgresql/17/bin:$PATH
WORKDIR /app
COPY --from=python-builder /usr/local/bin/python3.12 /usr/local/bin/python3.12
COPY --from=python-builder /usr/local/lib/ /usr/local/lib/
RUN ln -s python3.12 /usr/local/bin/python3 \
    && ln -s python3 /usr/local/bin/python \
    && ldconfig
COPY --from=python-builder --chown=10001:10001 /app/.venv /app/.venv
COPY --from=tools /out/rclone /usr/local/bin/rclone
COPY --from=tools /out/age /usr/local/bin/age
COPY --chown=10001:10001 src ./src
COPY --chown=10001:10001 deploy/backup ./deploy/backup
RUN rm -rf /var/lib/apt/lists/* /var/cache/apt/* /usr/bin/apt* /usr/bin/dpkg* /usr/sbin/dpkg*
USER 10001:10001
ENTRYPOINT []
CMD ["/app/deploy/backup/backup.sh"]
