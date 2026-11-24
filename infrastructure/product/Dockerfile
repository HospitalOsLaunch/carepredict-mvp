# HospitalOS product backend: hybrid "release -> allocate" API and 24-hour planner engine (same image,
# two services in deploy/nantes/docker-compose.release.yml). Locked environment, non-root, no code bind-mount.
FROM python:3.11.9-slim-bookworm@sha256:8fb099199b9f2d70342674bd9dbccd3ed03a258f26bbd1d556822c6dfc60c317

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src:/app

WORKDIR /app
COPY requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /app/requirements.lock

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY services /app/services
COPY web/decision /app/web/decision
COPY tests/decision_support/fixtures /app/tests/decision_support/fixtures
COPY configs /app/configs

RUN useradd --system --uid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin hospitalos \
    && mkdir -p /data/backups && chown -R 10001:10001 /data
# /data: platform accounts database (named volume, initialised from this owner at first start).
USER 10001

EXPOSE 8000 8765
CMD ["uvicorn", "services.api.hybrid_app:app", "--host", "0.0.0.0", "--port", "8000"]
