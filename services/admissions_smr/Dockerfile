# Admissions SMR API. Build from the repository root:
#   docker build -f services/admissions_smr/Dockerfile -t hospitalos/admissions-api .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY services/admissions_smr/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY services/__init__.py /app/services/__init__.py
COPY services/admissions_smr /app/services/admissions_smr
RUN rm -rf /app/services/admissions_smr/tests \
    && useradd --system --uid 10001 app
USER app

EXPOSE 8010
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/api/health')"
CMD ["uvicorn", "services.admissions_smr.main:app", "--host", "0.0.0.0", "--port", "8010", "--proxy-headers"]
