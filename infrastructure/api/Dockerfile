FROM python:3.11.9-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml README.md /app/
COPY services /app/services
COPY orchestration /app/orchestration
COPY data /app/data

RUN pip install --no-cache-dir -e ".[dev]"

CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
