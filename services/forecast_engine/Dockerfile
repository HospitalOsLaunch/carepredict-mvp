# Forecast engine (scheduled job). Build from the repository root:
#   docker build -f services/forecast_engine/Dockerfile -t hospitalos/forecast-engine .
# Separate from the API image: numpy, pandas and statsforecast never ship with the API.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY services/admissions_smr/requirements.txt /tmp/admissions_smr/requirements.txt
COPY services/forecast_engine/requirements.txt /tmp/forecast_engine/requirements.txt
RUN pip install --no-cache-dir -r /tmp/forecast_engine/requirements.txt

COPY services/__init__.py /app/services/__init__.py
COPY services/admissions_smr /app/services/admissions_smr
COPY services/forecast_engine /app/services/forecast_engine
RUN rm -rf /app/services/admissions_smr/tests /app/services/forecast_engine/tests \
    && useradd --system --uid 10001 app
USER app

# One run for every group, then exit (schedule it with cron, a Kubernetes CronJob...).
ENTRYPOINT ["python", "-m", "services.forecast_engine"]
CMD ["run", "--all"]
