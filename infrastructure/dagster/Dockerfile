FROM python:3.11.9-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install --no-cache-dir \
    dagster==1.7.16 \
    dagster-dbt==0.23.16 \
    dagster-postgres==0.23.16 \
    dagster-webserver==1.7.16 \
    dbt-core==1.7.19 \
    dbt-postgres==1.7.19 \
    feast[redis,postgres]==0.40.1 \
    great-expectations==0.18.22 \
    structlog==24.2.0

RUN mkdir -p /opt/dagster/dagster_home

WORKDIR /app
