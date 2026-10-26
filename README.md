# MVP computer use — HospitalOS Admissions SMR

Branche `mvp/computer-use` : un MVP à tester, séparé du reste de `carepredict-mvp`. Elle a
son propre historique (celui du module Admissions SMR, extrait de la branche
`feat/admissions-smr-v1`), sa propre CI, et aucun fichier du world model, du simulateur ou
des pipelines de données.

Le produit : un agent relève les demandes d'admission sur le portail d'orientation, les
dépose dans HospitalOS, et y reporte la réponse décidée par la coordination. Les écritures
sont relues, et chaque tâche est routée entre un script, des modèles open source
auto-hébergés et des modèles propriétaires selon la tâche, le coût et ce que chaque moteur
a le droit de voir.

## Tester en une commande

```bash
docker compose -f docker-compose.demo.yml up -d --build
```

| Adresse | Quoi | Accès |
| --- | --- | --- |
| http://localhost:8080 | HospitalOS | `coordination@demo.hospitalos.fr` ou `admin@…`, mot de passe `demo-hospitalos-2026` |
| http://localhost:8020 | Portail d'orientation fictif : une nouvelle demande toutes les 3 minutes | `demo` / `demo-portail` |

Parcours à essayer :

1. **Demandes** : les dossiers du portail arrivent seuls (source « Autre portail d'orientation »).
2. Donner un accord à une date : le bloc « Report sur le portail » passe à « fait et relu ».
3. Ouvrir le dossier sur le portail : l'accord et la date y sont saisis.
4. **Paramètres → Agent et routage** : état de l'agent, moteurs, routes, budgets, dernières tâches.

Vérification automatique du parcours complet (c'est aussi ce que fait la CI) :

```bash
pip install httpx && python tools/demo_check.py
```

Réglages : `DEMO_ARRIVAL_MINUTES` (rythme des nouvelles demandes), `DEMO_AGENT_CYCLE_SECONDS`
(pause de l'agent). Pour essayer les modèles sur le portail fictif : `ANTHROPIC_API_KEY`,
ou `OPEN_LIGHT_URL` / `OPEN_LIGHT_MODEL` (vLLM), puis activer le moteur dans
Paramètres → Agent et routage. Les écrans du portail fictif ne montrent que des identités
inventées.

## Reprendre des PR de carepredict-mvp

Les deux historiques sont séparés : une PR de `carepredict-mvp` ne peut pas être fusionnée
ici, mais ses commits peuvent être **dupliqués**.

```bash
python tools/duplicate_pr.py 31                          # crée la branche dup/pr-31
python tools/duplicate_pr.py 31 --push --open-pr         # et ouvre la PR vers mvp/computer-use
python tools/duplicate_pr.py 31 --include-outside        # apporte aussi les fichiers hors MVP
```

- Chaque commit est rejoué avec son auteur, son message et la mention
  `cherry picked from commit …` ; la duplication est consignée dans `DUPLICATIONS.md`.
- Seuls les chemins de [`tools/mvp-scope.txt`](tools/mvp-scope.txt) sont repris par défaut ;
  les autres sont listés et laissés de côté. Les fichiers propres au MVP (ce README,
  `pyproject.toml`, `tools/`, `docker-compose.demo.yml`, `.github/`) ne sont jamais remplacés.
- Un conflit sur un chemin du MVP arrête tout sans rien pousser : les deux lignes ont
  divergé, quelqu'un décide.
- Une PR empilée sur une autre branche est refusée tant que sa base n'a pas été dupliquée.
- Il faut `gh` authentifié sur `HospitalOsLaunch/carepredict-mvp`.

Les PR dupliquées passent par la CI de cette branche avant d'être fusionnées ici.

## Contenu

| Dossier | Contenu |
| --- | --- |
| [`services/admissions_agent/`](services/admissions_agent/README.md) | Agent de computer use, moteurs, routage, garde-fous, portail fictif |
| [`services/admissions_smr/`](services/admissions_smr/README.md) | API, prévisions, North Star ; AIPD et guide HDS dans `docs/` |
| [`services/admissions_web/`](services/admissions_web/) | Application web |
| `tools/` | Duplication de PR, vérification de la démo |

```bash
pip install -r services/admissions_smr/requirements-dev.txt && python -m playwright install chromium
pytest -q
ruff check services tools && ruff format --check services tools
mypy --config-file services/admissions_smr/mypy.ini services/admissions_smr services/admissions_agent tools
cd services/admissions_web && npm ci && npm test && npm run build
```

La même branche peut être poussée telle quelle dans un dépôt dédié le jour où le produit
doit être séparé pour un hébergement HDS : rien n'y dépend de `carepredict-mvp`.
