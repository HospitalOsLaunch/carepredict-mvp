# HospitalOS

**Aide à la décision pour la gestion des lits et des sorties, en mode observation.**

Statut : `PROTOTYPE_UNVALIDATED` · `clinical_validation=false` · `G2=NO-GO`. Toutes les données sont
**synthétiques** ; aucun système d'information hospitalier n'est raccordé ; l'outil n'émet aucune
commande et ne prend aucune décision clinique.

## Le produit

Un **cockpit web** et deux moteurs, pensés pour le cadre de santé et le gestionnaire de lits en
période de tension.

| Brique | Ce qu'elle fait | Code |
|---|---|---|
| **Cockpit « Libérer → Attribuer »** | Pour une unité : ce qui bloque chaque sortie, qui attend quel lit, **une seule action proposée** (réserver un lit propre compatible, prioriser un nettoyage, demander un transport, ou ne rien faire), avec son effet simulé contre « sans action » ; journal des décisions (validée, faite, refusée, sans réponse) | `web/` |
| **Moteur hybride** | Faits horodatés (heure de l'événement et heure de disponibilité), abstention si les données sont périmées ou contradictoires, simulation par scénarios appariés, notateur indépendant, proposition qui expire après 15 minutes | `src/hospitalos/hybrid`, `services/api/hybrid_app.py` |
| **Planificateur 24 h** | Plan de couverture soignante d'une unité : compétences, prêts entre unités, prévision de référence ; recommandation automatique puis mode manuel | `src/hospitalos/decision_support`, `web/decision/serve.py` |
| **Comptes et paramètres** | Un compte individuel par pilote (email et mot de passe, sur invitation d'un administrateur), réinitialisation par email, espace isolé par compte (journal, planificateur), paramètres (profil, sécurité, confidentialité, administration des comptes), journal d'audit | `src/hospitalos/platform`, `web/src/auth` |
| **Pilote silencieux** | Stockage par unité en mode *shadow*, contrôles de complétude et de fraîcheur, import d'un export local (6 tables) | `src/hospitalos/hybrid/live_*`, `docs/operational/live-unit-pilot.md` |

Ce que le produit **ne fait pas** : raccordement à un SI, authentification unique de l'établissement
(SSO), exécution d'actions, validation clinique. Sur données synthétiques, le planificateur 24 h réduit les minutes-soignant non
couvertes face à la pratique habituelle (lecture « exploratoire », `docs/decision_support/P5_P5a_REPORT.md`) ;
aucun bénéfice réel n'est établi.

## Démarrer

Environnement unique et verrouillé (`requirements.lock`, Python 3.11) — détails dans
[`docs/ENVIRONMENT.md`](docs/ENVIRONMENT.md).

```bash
python3.11 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.lock
.venv/bin/pip install --no-deps -e .

# Démonstrateurs en ligne de commande
PYTHONPATH=src .venv/bin/python -m hospitalos.hybrid --demo
PYTHONPATH=src .venv/bin/python -m hospitalos.decision_support --help

# Cockpit : deux moteurs, la plateforme (comptes, passerelle /api) et l'interface
PYTHONPATH=src:. .venv/bin/uvicorn services.api.hybrid_app:app --host 127.0.0.1 --port 8000 &
PYTHONPATH=src:. .venv/bin/python web/decision/serve.py --port 8765 &
PYTHONPATH=src:. .venv/bin/uvicorn --factory hospitalos.platform.app:app_from_env --port 8100 &
PYTHONPATH=src:. .venv/bin/python -m hospitalos.platform invite-admin vous@exemple.fr   # affiche le lien d'invitation
cd web && npm ci && npm run dev     # http://localhost:5173 ; sans plateforme, démonstration hors ligne
```

En développement (`APP_ENV=development`, valeur par défaut), les emails sont affichés dans la console
de la plateforme et la base des comptes est `var/platform.sqlite3`.

## Environnements et mise en production

| Environnement | Déclenchement | Particularités |
|---|---|---|
| **staging** (recette) | automatique, chaque commit vert de `main` | non indexé, bandeau « Recette », pas de mesure d'audience |
| **production** | tag `vX.Y.Z` + approbation dans GitHub | même image que la recette (aucune reconstruction), Google Analytics 4 après consentement |

Une VM par environnement, `deploy/cloud/docker-compose.yml` (Caddy en HTTPS devant le cockpit, la
plateforme et les moteurs), images dans GHCR, déploiement par `.github/workflows/deploy.yml` avec
sauvegarde de la base des comptes et retour arrière automatique. Procédure complète (serveurs, secrets
GitHub, premier administrateur, SMTP, GA4, sauvegardes, retour arrière) :
[`docs/operations/MISE_EN_PROD.md`](docs/operations/MISE_EN_PROD.md).

## Déployer (enclave hors ligne)

`deploy/nantes/docker-compose.release.yml` : cockpit (127.0.0.1:8080), la plateforme de comptes (emails
par le relais SMTP du CHU, sans mesure d'audience) et les deux API sur un réseau interne, plus la pile de données CarePredict. Images épinglées par empreinte, secrets obligatoires,
aucun port de base de données, privilèges réduits. Contrôle automatique :

```bash
python scripts/deploy/check_release.py --env deploy/nantes/.env.release
```

Enveloppe et état des contrôles : [`docs/nantes/deployment_envelope.md`](docs/nantes/deployment_envelope.md).

## Qualité

```bash
PYTHONPATH=src:. .venv/bin/python -m pytest -q      # ≈ 1 370 tests
.venv/bin/ruff check . && .venv/bin/mypy --strict services data src/hospitalos/platform tests/platform tests/unit tests/hybrid
cd web && npm run typecheck && npm test
```

CI : `.github/workflows/` (produit hybride, cockpit, fondation synthétique, fondation
opérationnelle, qualité générale avec les portes de déploiement enclave et cloud ; `deploy.yml` pour
staging et production). Périmètres de lint et de typage, et dette restante :
[`docs/ENVIRONMENT.md`](docs/ENVIRONMENT.md).

## Organisation du dépôt

| Dossier | Contenu | Statut |
|---|---|---|
| `web/`, `src/hospitalos/hybrid`, `src/hospitalos/decision_support`, `services/api/hybrid_app.py` | **produit** | maintenu |
| `src/hospitalos/synthetic`, `src/hospitalos/operational` | générateur multi-hôpitaux, contrat opérationnel | maintenu |
| `services/` (connecteurs, validation, API CarePredict), `orchestration/`, `infrastructure/` | pile de données et ingestion (agrégats Nantes) | maintenu |
| `src/hospitalos/platform`, `web/src/auth` | comptes, sessions, paramètres, passerelle `/api` | maintenu |
| `deploy/` | `cloud/` (staging, production) et `nantes/` (enclave) | maintenu |
| `src/hospitalos/{howm,howm2,howmint,bfrag*,p5}`, `scripts/int1`, `scripts/filter_*`, `scripts/plan48`, `evidence/` | **recherche** (world models, filtrage, campagnes gelées et leurs preuves) | gelé, non lint |
| `src/hospitalos/{dynamics,encoders,training,eval}`, `rs_jepa/` | prévision CarePredict v2 (TS-JEPA, RSSM) | historique |

## Recherche

Les world models et la prévision restent de la R&D, derrière l'interface du planificateur :

- **Prévision de charge v2** : ne bat pas les références naïves (`docs/v2_findings.md`).
- **World model INT-1** : +3,5 % d'attente face à la règle historique, +0,4 % face au meilleur modèle
  direct, en synthétique (`docs/howm_int1/RAPPORT_INT1.md`).
- **Correctifs du 23 novembre** sur les campagnes de filtrage (`docs/research/CORRECTIFS_2026-11-23.md`).

L'ancien README (CarePredict) est archivé dans `docs/carepredict/README_CAREPREDICT_2026-10.md`.
