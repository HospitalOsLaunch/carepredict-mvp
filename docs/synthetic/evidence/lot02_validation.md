# Vérification locale — lot 02

Environnement : Python 3.12.14, NumPy 2.3.5, pandas 2.2.3, Pydantic 2.13.5.
Les commandes ont été exécutées depuis la racine du dépôt.

| Vérification | Résultat |
|---|---|
| `python -m ruff check .` | Succès, y compris après construction d'une wheel |
| `python -m ruff format --check src/hospitalos/synthetic tests/synthetic` | 11 fichiers conformes, import historique exclu |
| Typage strict des 8 modules du socle et des 2 fichiers de tests | Succès, 10 fichiers |
| `PYTHONPATH=src python -m pytest -q tests/synthetic` | 63 tests passent : 31 du socle et 32 du lot 02 |
| Rejeu annuel ci-dessous | Succès, 61 320 lignes de variables et autant de lignes de cibles |

```bash
PYTHONPATH=src python -m hospitalos.synthetic.learning \
  --source runs/synthetic/annual-validation \
  --output runs/synthetic/asof-annual-lot02-final
```

Source : année 2025, graine 41, 61 jours de chauffe, 4 unités dans 2 pôles,
partition `development`, vérité du lot 01. Le [manifeste](lot02_annual_manifest.json)
identifie exactement la source et les modules exécutés ; leurs empreintes ont été
comparées aux fichiers locaux après le run. Les [métriques complètes](lot02_metrics.json)
incluent les erreurs et la couverture pour chacune des 7 entités et 3 variables.

## Erreur absolue moyenne à 24 h, référence de persistance

| Niveau | Lits occupés (lits) | File urgences (patients) | Charge (minutes de soins par heure) |
|---|---:|---:|---:|
| Unité, moyenne des 4 MAE | 1,9295 | 0,3016 | 42,6234 |
| Pôle, moyenne des 2 MAE | 2,8961 | 0,5196 | 71,7541 |
| Hôpital | 4,3301 | 0,8366 | 125,8340 |

Chaque entité a 8 760 décisions horaires : 23 cibles sont censurées, 8 737 sont
éligibles, 3 prévisions s'abstiennent pour ancienneté et 8 734 sont évaluées.
La couverture est donc 99,9657 % des décisions éligibles, et non de toutes les décisions.
Les unités ont des tailles et des dynamiques différentes ; la moyenne des MAE ne
constitue pas une normalisation par capacité. La charge est une valeur horaire à la
cible, pas un cumul de 24 heures.

## Qualité d'observation et invariance

- 41 335 livraisons, dont 870 corrections et 307 doublons de transport.
- 40 158 événements d'état distincts disponibles ; 738 états non livrés à la clôture
  (absence simulée ou disponibilité après la fin d'extraction, sans attribuer ces
  deux causes à partir du seul flux reçu).
- Aucune ligne unité sans historique grâce à la chauffe ; 12 lignes unité trop
  anciennes, soit 3 par unité. Les relevés non livrés n'entraînent pas automatiquement
  une ligne vide : le dernier état connu est conservé avec son ancienneté.
- Les tests de mutation refusent les horloges inversées, une provenance future,
  une colonne de cible dans les variables, un doublon divergent, une identité
  d'événement modifiée et une grille de vérité incomplète ou dupliquée.
- Le rejeu vérifie l'invariance aux livraisons futures et aux retransmissions ; les
  exports sont reproductibles octet pour octet à code, entrée et environnement identiques.

## État des contrôles GitHub du socle

La CI générale du lot 01 avait parcouru les copies générées sous `build/` après
installation du paquet. L'exclusion des artefacts de compilation a été corrigée
dans la PR #4 et vérifiée en construisant effectivement une wheel avant le lint.
Au commit `661d674`, la [CI générale](https://github.com/HospitalOsLaunch/carepredict-mvp/actions/runs/38654745126)
et la [CI synthétique](https://github.com/HospitalOsLaunch/carepredict-mvp/actions/runs/38654745157)
réussissent, incluant les 54 tests historiques et une année complète. Le lot 02
ajoute son propre rejeu annuel en CI. Ce relevé local ne préjuge pas de l'issue de
ces nouvelles exécutions distantes.

Ces résultats sont descriptifs sur un seul hôpital synthétique de développement.
Aucun modèle n'a été entraîné, aucun réglage n'a été sélectionné à partir d'un test
final et aucune performance clinique, causale ou de transfert au réel n'est établie.
