# Contributing

## Démonstration intégrée (sans infrastructure)

Avec Python 3.11+ et Node.js 22+ : `python3 demo.py` depuis la racine.
Cette commande prépare ses dépendances puis lance le backend et le cockpit.
`python3 demo.py --check` vérifie la connexion HTTP et arrête les deux services.
Le [guide dédié](docs/simulator/dynamic-demo.md) décrit les options et limites.
Le setup complet ci-dessous concerne les autres composants du dépôt.

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
