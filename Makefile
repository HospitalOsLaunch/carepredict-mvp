COMPOSE ?= docker compose
PYTHON ?= python3

.PHONY: up down seed features test logs clean lint type-check docker-build

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

seed:
	$(PYTHON) data/synthetic/siips_generator.py --output data/generated/siips.csv

features:
	dbt --project-dir services/feature_pipeline/dbt --profiles-dir services/feature_pipeline/dbt run
	dbt --project-dir services/feature_pipeline/dbt --profiles-dir services/feature_pipeline/dbt test
	feast -c services/feature_pipeline/feast apply

test:
	pytest --cov=services/connectors --cov=services/feature_pipeline --cov-report=term-missing

logs:
	$(COMPOSE) logs -f --tail=200

clean:
	$(COMPOSE) down -v --remove-orphans

lint:
	ruff check .

type-check:
	mypy --strict services orchestration data tests

docker-build:
	$(COMPOSE) build
