# Computer-use agent. Runs inside the establishment's network, next to the portals it reads,
# and talks to the HospitalOS API with a service account. Build from the repository root:
#   docker build -f services/admissions_agent/Dockerfile -t hospitalos/admissions-agent .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
WORKDIR /app

COPY services/admissions_agent/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY services/__init__.py /app/services/__init__.py
COPY services/admissions_agent /app/services/admissions_agent
RUN rm -rf /app/services/admissions_agent/tests \
    && useradd --system --uid 10002 agent
USER agent

# No port: the agent only makes outbound calls (API, allowed portal hosts, model endpoints).
# `check` validates the configuration; `run` loops forever.
ENTRYPOINT ["python", "-m", "services.admissions_agent"]
CMD ["run"]
