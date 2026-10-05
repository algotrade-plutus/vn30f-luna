# syntax=docker/dockerfile:1.7
FROM --platform=$TARGETPLATFORM python:3.11-alpine3.24@sha256:cd04730b8511def3fbf14204d66a0c1536f290b8e896ed5a94cd64cb15ac1356 AS wheel-builder

RUN apk add --no-cache build-base linux-headers
WORKDIR /build
COPY requirements.lock vendor/paperbroker_client-0.2.8-py3-none-any.whl ./
RUN python -m pip install --upgrade \
       pip==26.2.1 wheel==0.48.0 setuptools==84.0.0 \
    && python -m pip wheel --wheel-dir /wheels \
       -r requirements.lock ./paperbroker_client-0.2.8-py3-none-any.whl

FROM python:3.11-alpine3.24@sha256:cd04730b8511def3fbf14204d66a0c1536f290b8e896ed5a94cd64cb15ac1356 AS runtime

ARG RELEASE_ID=local-unidentified
ARG SOURCE_KIND=local_build
ARG GIT_COMMIT=
ARG EFFECTIVE_SOURCE_SHA256=UNKNOWN
ARG BEHAVIOR_POLICY=unclassified_local_build

LABEL org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.version="${RELEASE_ID}" \
      io.algotrade.source-sha256="${EFFECTIVE_SOURCE_SHA256}"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PAPERTRADING_MODE=hold

RUN apk upgrade --no-cache \
    && apk add --no-cache libstdc++ \
    && addgroup -S -g 10001 algotrade \
    && adduser -S -D -H -u 10001 -G algotrade -s /sbin/nologin algotrade
WORKDIR /app
COPY --from=wheel-builder /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/* \
    && rm -rf /wheels
COPY --chown=algotrade:algotrade algotrade_adapter ./algotrade_adapter
COPY --chown=algotrade:algotrade runtime_core ./runtime_core
COPY --chown=algotrade:algotrade alphas ./alphas
COPY --chown=algotrade:algotrade luna_core ./luna_core
COPY --chown=algotrade:algotrade dashboard ./dashboard
COPY --chown=algotrade:algotrade scripts ./scripts
RUN RELEASE_ID="${RELEASE_ID}" \
    SOURCE_KIND="${SOURCE_KIND}" \
    GIT_COMMIT="${GIT_COMMIT}" \
    EFFECTIVE_SOURCE_SHA256="${EFFECTIVE_SOURCE_SHA256}" \
    BEHAVIOR_POLICY="${BEHAVIOR_POLICY}" \
    python - <<'PY'
import json
import os
from pathlib import Path

release = {
    "schema_version": 1,
    "release_id": os.environ["RELEASE_ID"],
    "source_kind": os.environ["SOURCE_KIND"],
    "git_commit": os.environ["GIT_COMMIT"] or None,
    "effective_source_sha256": os.environ["EFFECTIVE_SOURCE_SHA256"],
    "platform": "linux/amd64",
    "behavior_policy": os.environ["BEHAVIOR_POLICY"],
}
Path("/app/release.json").write_text(
    json.dumps(release, ensure_ascii=False, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
RUN mkdir -p /app/logs /app/runtime /app/state \
    && chown -R algotrade:algotrade /app

USER algotrade
VOLUME ["/app/logs", "/app/runtime", "/app/state"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "scripts/container_healthcheck.py"]
ENTRYPOINT ["python", "scripts/container_entrypoint.py"]
