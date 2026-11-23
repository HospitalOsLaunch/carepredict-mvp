FROM python:3.11.9-slim-bookworm@sha256:8fb099199b9f2d70342674bd9dbccd3ed03a258f26bbd1d556822c6dfc60c317

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /app/requirements.lock

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY rs_jepa /app/rs_jepa
COPY services /app/services
COPY orchestration /app/orchestration
COPY data /app/data

RUN pip install --no-cache-dir --no-deps -e . \
    && useradd --system --uid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin carepredict
USER 10001

CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
