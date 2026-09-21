FROM python:3.12.14-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9 AS python-builder
COPY --from=ghcr.io/astral-sh/uv:0.11.30@sha256:93b61e21202b1dab861092748e46bbd6e0e41dd84f59b9174efd2353186e1b47 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM golang:1.26.8-bookworm@sha256:a688600ca24f8a4d3ca77f95b0dd40704a9fc787c826660eb7ba0b641b8b175d AS rclone-builder
ENV GOPROXY=https://proxy.golang.org \
    GOSUMDB=sum.golang.org
ARG RCLONE_COMMIT=687d264b689b8c49a67e2e52a8a5e0caa01c04ce
ARG RCLONE_VERSION=v1.75.1
ARG GRPC_VERSION=v1.83.2
RUN git clone --filter=blob:none https://github.com/rclone/rclone.git /src \
    && cd /src \
    && git checkout --detach "$RCLONE_COMMIT" \
    && test "$(git rev-parse HEAD)" = "$RCLONE_COMMIT" \
    && go mod edit -replace=google.golang.org/grpc=google.golang.org/grpc@"$GRPC_VERSION" \
    && go mod download all \
    && mkdir -p /out \
    && CGO_ENABLED=0 go build -trimpath -buildvcs=false \
        -ldflags="-s -w -X github.com/rclone/rclone/fs.Version=$RCLONE_VERSION" \
        -o /out/rclone .

FROM postgres:17.6-bookworm@sha256:f3bd19c606e442c3d7bdfa8002e03fe260a1023351e0ea4598032022b68dd6e3 AS tools
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
ARG AGE_URL=https://github.com/FiloSottile/age/releases/download/v1.3.2/age-v1.3.2-linux-amd64.tar.gz
ARG AGE_SHA256=cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10
RUN curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error "$AGE_URL" -o /tmp/age.tar.gz \
    && echo "$AGE_SHA256  /tmp/age.tar.gz" | sha256sum --check --status \
    && tar -xzf /tmp/age.tar.gz -C /tmp \
    && mkdir -p /out \
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
COPY --from=rclone-builder /out/rclone /usr/local/bin/rclone
COPY --from=tools /out/age /usr/local/bin/age
COPY --chown=10001:10001 src ./src
COPY --chown=10001:10001 deploy/backup ./deploy/backup
RUN apt-get update \
    && apt-get upgrade --yes \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/* /usr/local/bin/gosu \
        /usr/bin/apt* /usr/bin/dpkg* /usr/sbin/dpkg*
USER 10001:10001
ENTRYPOINT []
CMD ["/app/deploy/backup/backup.sh"]
