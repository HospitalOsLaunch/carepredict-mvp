# Contributing

## Setup local

```bash
cp .env.example .env
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install ".[dev]"
make up
```

## Qualite

```bash
make lint
make type-check
make test
docker compose config
```

Python est type en mode strict avec mypy. Les logs applicatifs doivent etre structures en JSON avec `structlog`.

## Commits

Utiliser des messages conventionnels :

- `feat: add hl7 admission parser`
- `fix: normalize discharge timestamps`
- `chore: update compose healthchecks`
- `docs: document feature store`
