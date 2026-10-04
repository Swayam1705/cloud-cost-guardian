# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Cloud Cost Guardian — small, non-root, secret-free image.
#   docker build -t cloud-cost-guardian .
#   docker run --rm cloud-cost-guardian scan --mode demo
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
# Build a wheel so the runtime stage has no build tooling and no source tree.
RUN pip install "pip>=24,<27" "build>=1.2,<2" && python -m build --wheel --outdir /build/dist


FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="cloud-cost-guardian" \
      org.opencontainers.image.description="Zero-cost, local-first AWS waste detection with approval-gated remediation" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/Swayam1705/cloud-cost-guardian"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CCG_ARTIFACTS_DIR=/app/artifacts \
    CCG_DATA_DIR=/app/data

# Pull Debian security updates published after the base image was built (keeps Trivy clean),
# then create a non-root user with a writable working directory for artifacts.
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 ccg \
 && useradd --system --uid 10001 --gid ccg --home-dir /app --no-create-home ccg \
 && mkdir -p /app/artifacts /app/data \
 && chown -R ccg:ccg /app

# Install the wheel, then remove the package tooling: the runtime image needs no installer, and
# pip/setuptools/wheel are the most common source of HIGH CVEs flagged in slim Python images.
COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install /tmp/*.whl \
 && rm -f /tmp/*.whl \
 && pip uninstall -y pip setuptools wheel \
 && rm -rf /usr/local/lib/python3.12/ensurepip /root/.cache

# Repo-level fixtures are also shipped for users who want to edit them (package has its own copy).
COPY --chown=ccg:ccg demo /app/demo

USER 10001:10001
WORKDIR /app
VOLUME ["/app/artifacts", "/app/data"]

# A cheap self-check: the CLI must import and validate its built-in config.
HEALTHCHECK --interval=5m --timeout=10s --start-period=5s --retries=1 \
  CMD ["ccg", "validate-config"]

ENTRYPOINT ["ccg"]
CMD ["scan", "--mode", "demo"]
