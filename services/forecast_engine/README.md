# Moteur de prévision LISCOP (`services/forecast_engine`)

Service séparé, lancé en tâche planifiée : il lit la base par les modèles SQLAlchemy de
`services.admissions_smr`, calcule les prévisions et les écrit dans `forecast_runs` /
`forecast_values`. L'API ne l'importe jamais : elle lit les résultats
(`GET /api/forecast/liscop`), sans numpy, pandas ni statsforecast dans son image.

## Ce qui est prévu

Pour J+0 à J+7 (J+0 = jour du calcul, état pris à 0 h) :

| Cible (`target`) | Portées (`scope`) | Valeurs |
|---|---|---|
| `available_beds` | unité, site, groupe, GHT, département | moyenne, q10, q50, q90, `p_tension`, `p_critique` |
| `tension_prob` | idem | `mean` = `p_tension` (redondant, pour qui ne lit que cette cible) |
| `arrivals` | idem | arrivées dans l'unité, tous modes |
| `discharges` | idem | sorties du jour |
| `boarding_10h` | site, groupe, GHT, département | lits brancards à 10 h |
| `ed_arrivals` | idem | passages aux urgences (cible en plus du contrat) |

`scope_key` : `pool:<id>`, `site:<id>`, `group:<id>`, le nom du GHT, le code du département.

## Méthode

1. **Séries** (`data.py`) : par unité, arrivées (et par `admission_mode`), sorties,
   occupation en fin de journée ; par site, passages, admissions et **lits brancards à
   10 h** : patients présents aux urgences à 10 h (Europe/Paris), décision
   d'hospitalisation à 10 h au plus tard, arrivés avant 8 h. Définition et seuils dans
   `data.py` (`BOARDING_*`), à unifier avec `services/admissions_smr/domain/ed.py`.
2. **Modèles** (`models.py`, Nixtla statsforecast) : `SeasonalNaive(7)` (référence),
   `AutoETS`, `AutoTheta`, `MSTL` (hebdomadaire ; + annuel au-delà de deux ans
   d'historique), choisis par série par validation croisée à origine glissante (56
   origines, h = 8, réestimation tous les 7 jours) ; repli sur la référence quand aucun
   ne la bat (signalé `fallback`).
3. **Intervalles** (`conformal.py`) : conformal split par horizon sur les résidus de la
   validation croisée, adapté en ligne par **ACI** (Gibbs & Candès 2021, γ = 0,2) pour
   s'élargir en cas de rupture (épidémie).
4. **Lits disponibles** (`capacity.py`) : Monte Carlo, 2 000 tirages, graine fixe.
   Sorties des présents tirées des probabilités par patient du modèle existant
   (`service.build_forecast` : Kaplan-Meier, dates prévues avec glissement mesuré),
   report des sorties du week-end selon le profil observé ; arrivées en binomiale
   négative calée sur la prévision et l'intervalle conformal ; les arrivants peuvent
   sortir dans l'horizon ; admissions promises (demandes accordées, patients des urgences
   en attente de l'unité) en plancher des arrivées. Disponibles bornés à [0, lits
   ouverts]. Tension : seuil `TENSION_NORMAL_MIN` de `domain/ror.py` (20 % des lits
   installés), critique à 0. `p_tension` = P(tension ou critique).
5. **Agrégats** : somme des tirages des unités, tirage par tirage, avec un facteur
   commun journalier sur les arrivées (variance estimée sur la covariance des erreurs
   des unités) ; les sorties sont indépendantes entre patients.

Chaque run garde dans `metrics_json` le modèle et les MAE de validation de chaque
série, les niveaux ACI, l'erreur moyenne par type de jour (férié, vacances zone B,
ordinaire), le profil des sorties par jour de semaine, les 28 derniers jours observés.

## Lancer

```bash
pip install -r services/forecast_engine/requirements.txt
python -m services.forecast_engine run --group 1            # J+0 = aujourd'hui
python -m services.forecast_engine run --group 1 --as-of 2026-11-02
python -m services.forecast_engine run --all                # tous les groupes
python -m services.forecast_engine backtest --group 1 --out backtest.json
```

Même configuration que l'API (`ADM_DATABASE_URL`, `ADM_TIMEZONE`). Un run en échec est
enregistré (`status = failed`) et l'API continue de servir le dernier run réussi en le
signalant. Le backtest enregistre son en-tête (`status = backtest`, sans valeurs).
Durée sur la démo MCO (8 unités avec lits, un an) : environ 20 s par run, 5 min pour le backtest.

Docker : `services/forecast_engine/Dockerfile` (une exécution `run --all` puis sortie,
à planifier) ; service `forecast` de `docker-compose.demo.yml` (démo : toutes les
`FORECAST_EVERY_HOURS` heures, 6 par défaut).

## Tests

```bash
pytest -q services/forecast_engine/tests -m "not slow"   # < 30 s
pytest -q services/forecast_engine/tests                 # avec le run complet sur la démo
```

## Limites

- Validé seulement sur la démo synthétique (`docs/liscop/BACKTEST.md`) : critères (a),
  (c), (d) réussis, (b) échoué pour les lits disponibles (91,8 %, fourchettes trop
  prudentes dans les unités pleines). À rejouer sur des données réelles avant tout usage.
- Les arrivées ne sont pas contraintes par la place : quand une unité est pleine, le
  surplus attend aux urgences dans la réalité ; ici il fait passer les disponibles sous 0
  (borné à 0).
- Admissions programmées prévues comme des arrivées (aucun planning opératoire n'est lu).
- Jours fériés et vacances scolaires : diagnostic seulement (le générateur de démo n'a pas
  d'effet calendrier) ; dates zone B 2026-2027 à vérifier sur l'arrêté publié.
- Agrégats GHT / département limités aux établissements du groupe.
