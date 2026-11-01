# Backtest pré-enregistré du moteur de prévision (LISCOP)

Statut : **protocole figé avant toute exécution sur la période d'évaluation.** Ce
document est commité seul, avant le code qui produit les résultats ; les résultats sont
ajoutés plus bas, dans une section séparée, sans modifier le protocole. Un critère qui
échoue est rapporté comme échoué. Si quelque chose est changé après avoir vu les
résultats, c'est dit explicitement et le premier résultat est conservé.

**Données : démo synthétique.** Le backtest tourne sur l'hôpital MCO fictif généré par
notre propre simulateur (`python -m services.admissions_smr.cli seed-demo-mco`, un an
d'historique). Il prouve que la chaîne fonctionne et que les intervalles sont calibrés
sur ce générateur ; il ne prouve **pas** la précision sur des données réelles.

## Ce qui est prévu

Pour chaque unité avec des lits (`bed_pools.beds_installed > 0`) et chaque site :

| Cible | Série quotidienne | Portée |
|---|---|---|
| `arrivals` | entrées dans l'unité (tous modes : urgences, programmé, mutation, transfert), jour local Europe/Paris de `stays.admitted_at` (à défaut `admission_date`) | unité |
| `available_beds` | lits ouverts − patients présents en fin de journée, borné à [0, lits ouverts] | unité |
| `boarding_10h` | patients présents aux urgences à 10:00 (Europe/Paris), avec décision d'hospitalisation à 10:00 au plus tard, arrivés avant 08:00 le jour même | site |

Origine `o` : la prévision est faite le matin du jour `o` avec les données des jours
strictement antérieurs. J+k désigne le jour `o + k`. Horizons évalués : J+1 à J+7.

## Méthode (figée)

- Modèles candidats, Nixtla `statsforecast` 2.1 : `SeasonalNaive(7)` (référence),
  `AutoETS(season_length=7)`, `AutoTheta(season_length=7)`,
  `MSTL(season_length=[7, 365], trend_forecaster=AutoETS(model="ZZN"))` si la série
  couvre au moins deux ans, sinon `MSTL(season_length=7, …)` (la démo n'a qu'un an).
- Sélection par série et par origine, sur les seules données d'entraînement : validation
  croisée à origine glissante (`StatsForecast.cross_validation`, h = 8 jours pour couvrir
  J+0 à J+7, pas de 1 jour, 56 fenêtres, réestimation tous les 7 jours). Critère : MAE
  moyenne sur toutes les fenêtres et horizons. Si aucun candidat ne bat `SeasonalNaive`,
  on garde `SeasonalNaive` et on le note (`fallback`).
- Prévisions ponctuelles bornées à 0.
- Intervalles à 80 % : conformal split par horizon sur les résidus signés de la
  validation croisée du modèle retenu (quantiles 10 % et 90 % avec correction
  d'échantillon fini), fenêtre glissante des 56 derniers résidus, puis **ACI**
  (Gibbs & Candès 2021) : niveau adapté `α_{t+1} = α_t + γ (α − err_t)`, α = 0,2,
  γ = 0,05, résidus révélés avec le décalage de l'horizon.
- Lits disponibles : Monte Carlo, 2 000 tirages, graine fixe. Sorties des patients
  présents tirées des probabilités par patient du modèle existant (`build_forecast` :
  Kaplan-Meier par unité, dates de sortie prévues avec glissement mesuré) ; arrivées
  tirées d'une binomiale négative calée sur la prévision et l'intervalle conformal ;
  les arrivées du jour sortent selon la même loi de durée de séjour ; les admissions
  promises sont un plancher des arrivées. Quantiles 10/50/90 des lits disponibles
  bornés à [0, lits ouverts].

Les hyperparamètres ci-dessus (α, γ, fenêtre, nombre de fenêtres, tirages) ne peuvent
être réglés que sur la **période de développement** (avant la fenêtre d'évaluation) ou
sur des séries synthétiques de test. Tout changement est consigné ci-dessous dans un
amendement daté, commité avant la première exécution sur la fenêtre d'évaluation.

## Fenêtre d'évaluation et origines

Soit `T` le dernier jour complet de l'historique (veille du jour de génération de la
démo). Dernière origine `o₂₁ = T − 7` (son J+7 tombe sur `T`). Origines
`oᵢ = o₂₁ − 7 (21 − i)`, i = 1…21 : **21 origines hebdomadaires**, couvrant les
**21 dernières semaines** de l'historique. Tout ce qui précède `o₁` est la période de
développement.

## Critères (pré-enregistrés)

**(a) Arrivées, précision.** Rapport de MAE `MAE(modèle retenu) / MAE(SeasonalNaive(7))`,
calculé sur toutes les unités et origines, **pour chaque horizon J+1…J+7**.
Réussite si le rapport poolé est < 1 à chacun des 7 horizons. Les rapports par unité
sont publiés, sans valeur de critère.

**(b) Calibration à 80 %.** Couverture empirique de l'intervalle [q10, q90] (bornes
incluses), poolée sur unités, origines et horizons J+1…J+7. Réussite si elle est dans
[75 %, 85 %], **séparément** pour les arrivées et pour les lits disponibles. Couvertures
par horizon publiées.

**(c) Rupture de régime.** Sur une copie de chaque série d'arrivées par unité et de la
série des passages aux urgences par site, on multiplie les valeurs par 1,5 (arrondi à
l'entier) pendant 21 jours, du jour `S = T − 48` à `S + 20`. Origines quotidiennes ;
on évalue toutes les prévisions J+1…J+7 dont le jour cible tombe dans la fenêtre de
rupture. Deux intervalles autour des mêmes prévisions ponctuelles :
- *statique* : décalages conformal estimés avec les résidus dont le jour cible précède
  `S`, puis gelés ;
- *ACI* : même départ, puis mise à jour en ligne (niveau et fenêtre de résidus) à mesure
  que les résidus sont révélés.
Réussite si la couverture ACI poolée (séries, horizons) est dans [75 %, 85 %] **et** la
couverture statique est < 75 %. Si la statique ne décroche pas (≥ 75 %), le test est
déclaré **non concluant** (la rupture injectée n'est pas un stress).

**(d) Lits brancards à 10 h.** Rapport de MAE poolé (sites, origines, horizons J+1…J+7)
du modèle retenu contre `SeasonalNaive(7)`. Réussite si < 1. Si la MAE de la référence
est nulle, le critère est déclaré non évaluable.

**Informatif, sans critère** : MAE des lits disponibles contre la persistance (lits
disponibles la veille de l'origine), modèles retenus par série.

## Commande

```bash
python -m services.forecast_engine backtest --group <id>
```

## Amendements

### 1er novembre 2026, avant toute exécution sur la fenêtre d'évaluation

Contrôle sur la **période de développement** seulement : 10 origines hebdomadaires du
2026-03-21 au 2026-05-23 (leur J+7 précède `o₁` = 2026-06-06), rupture injectée du
2026-05-01 au 2026-05-21. Constats et changements, figés ici :

- **A1. Report des sorties du week-end.** Les lits disponibles à J+1 (un dimanche : les
  origines tombent un samedi) étaient mal calibrés (couverture 57,5 %, MAE 4,21 contre
  1,86 pour la persistance) alors que J+2 à J+7 allaient bien. Cause : le modèle de
  sorties (Kaplan-Meier par durée de séjour) ignore le jour de la semaine, alors que les
  sorties du week-end sont reportées au lundi (dans le générateur comme dans les
  hôpitaux). Changement : dans le Monte Carlo, une part des sorties de chaque jour est
  reportée au lendemain pour reproduire le profil hebdomadaire observé des sorties des
  12 semaines précédant l'origine (toutes unités ; `capacity.weekday_retention`). Après :
  J+1 à 92,5 %, MAE 1,70.
- **A2. Pas de l'ACI γ = 0,2** (au lieu de 0,05). Règle fixée avant de regarder : le plus
  petit γ de la grille {0,05 ; 0,1 ; 0,2 ; 0,3} dont la couverture ACI poolée reste à
  ±5 points de 80 % sur la rupture de développement. Résultats de développement
  (statique 62,7 %) : ACI 70,4 / 72,3 / 75,3 / 76,2 %. γ = 0,2 est donc retenu ; il
  s'applique aussi aux intervalles en production.
- **A3. Mesure informative ajoutée, sans critère** : couverture à 80 % par PIT
  randomisé (Czado, Gneiting & Held, *Biometrics* 2009) pour les lits disponibles, et la
  part des cas « q10 = 0 et réalisé = 0 ». Raison : une unité pleine a un atome à 0 lit
  disponible ; l'intervalle [q10, q90] bornes incluses sur-couvre alors par construction
  (en développement : 94,1 % en inclusif contre 83,8 % en PIT randomisé, 22 % des cas
  sont « 0 prévu en q10, 0 réalisé »). Le critère (b) reste **inchangé** (couverture
  inclusive dans [75 %, 85 %]) et sera jugé tel quel.

Rien d'autre n'a été modifié. Les critères (a) à (d) sont inchangés.

## Résultats

Exécution unique du 1er novembre 2026, après le commit du protocole (`dd50540`) et de
son amendement (`a226172`), avec `python -m services.forecast_engine backtest --group 1`
sur la démo `seed-demo-mco` générée le même jour. Rien n'a été modifié après avoir vu ces
chiffres. Rappel : **données synthétiques de notre propre simulateur** ; ces résultats
prouvent la chaîne et la calibration sur ce générateur, pas la précision sur un hôpital
réel.

Démo générée pour le 2026-11-01 ; dernier jour complet 2026-10-31 ; 21 origines du 2026-06-06 au 2026-10-24 ; durée 263.4 s.

| Critère | Résultat |
|---|---|
| (a) MAE arrivées / SeasonalNaive < 1 à chaque horizon | réussi |
| (b) Couverture 80 % dans [75 %, 85 %] (arrivées et lits) | échoué |
| (c) Rupture de régime : ACI à ±5 points, statique < 75 % | réussi |
| (d) MAE lits brancards à 10 h / SeasonalNaive < 1 | réussi |

### Par horizon

| Horizon | Arrivées : MAE / réf. | Arrivées : couverture | Lits disponibles : couverture | Lits dispo : MAE (persistance) | Brancards 10 h : MAE / réf. |
|---|---|---|---|---|---|
| J+1 | 0.796 | 91.7 % | 91.1 % | 1.83 (2.24) | 0.545 |
| J+2 | 0.853 | 71.4 % | 87.5 % | 2.66 (3.13) | 0.950 |
| J+3 | 0.783 | 77.4 % | 89.3 % | 2.91 (3.08) | 0.997 |
| J+4 | 0.731 | 80.4 % | 89.9 % | 3.09 (3.31) | 0.722 |
| J+5 | 0.785 | 78.0 % | 94.0 % | 2.80 (2.99) | 0.929 |
| J+6 | 0.694 | 76.2 % | 94.0 % | 2.69 (3.18) | 0.937 |
| J+7 | 0.703 | 90.5 % | 97.0 % | 2.76 (3.15) | 1.085 |
| **Poolé** | **0.762** | **80.8 %** | **91.8 %** | **2.68 (3.01)** | **0.868** |

### Par unité (J+1 à J+7 poolés)

| Unité | Arrivées : MAE (réf.) | MAE / réf. | Couverture arrivées | Lits dispo : MAE (persistance) | Couverture lits |
|---|---|---|---|---|---|
| Médecine polyvalente | 1.82 (2.33) | 0.784 | 78.2 % | 3.59 (4.67) | 87.8 % |
| Court séjour gériatrique | 1.41 (1.82) | 0.775 | 83.7 % | 3.33 (3.48) | 89.8 % |
| Cardiologie | 1.95 (2.78) | 0.704 | 83.7 % | 3.27 (3.68) | 88.4 % |
| Chirurgie viscérale | 1.60 (2.05) | 0.784 | 83.7 % | 2.84 (3.87) | 90.5 % |
| Chirurgie orthopédique | 1.90 (2.66) | 0.716 | 81.0 % | 2.94 (3.51) | 92.5 % |
| Réanimation | 1.13 (1.36) | 0.829 | 80.3 % | 2.01 (1.96) | 91.2 % |
| SMR polyvalent | 0.93 (1.19) | 0.781 | 78.2 % | 1.97 (1.53) | 98.0 % |
| SMR gériatrie | 0.91 (1.13) | 0.805 | 77.5 % | 1.48 (1.39) | 96.6 % |

Passages aux urgences (informatif) : MAE 9.02 contre 11.84 pour la référence (rapport 0.762), couverture 79.6 %.

### Rupture de régime (×1.5 du 2026-09-13 au 2026-10-03, 9 séries, 1323 prévisions)

| Horizon | Statique | ACI |
|---|---|---|
| J+1 | 67.2 % | 77.2 % |
| J+2 | 65.6 % | 79.4 % |
| J+3 | 65.1 % | 78.3 % |
| J+4 | 66.7 % | 76.2 % |
| J+5 | 66.7 % | 73.5 % |
| J+6 | 65.6 % | 73.0 % |
| J+7 | 65.1 % | 73.0 % |
| **Poolé** | **66.0 %** | **75.8 %** |

Modèles retenus (toutes origines) :

- `arrivals` : AutoETS 82, AutoTheta 55, MSTL 31
- `ed_arrivals` : AutoETS 12, AutoTheta 9
- `boarding_10h` : AutoETS 1, AutoTheta 14, MSTL 6

Mesure informative (amendement A3, sans critère) : lits disponibles, couverture par PIT
randomisé **82,7 %** poolée (de 78,6 % à J+4 à 86,3 % à J+6), contre 91,8 % en
intervalle inclusif ; dans 23,0 % des cas, q10 = 0 et 0 lit disponible réalisé.

### Lecture

- **(a) réussi.** Le modèle retenu bat la référence saisonnière à chaque horizon, de
  0,69 (J+6) à 0,85 (J+2) en rapport de MAE, et dans chaque unité (0,70 à 0,83). AutoETS
  est le plus souvent retenu, puis AutoTheta et MSTL ; aucune série n'a eu besoin du repli.
- **(b) échoué.** Les arrivées sont bien calibrées (80,8 % poolé ; 71 à 92 % selon
  l'horizon). Les **lits disponibles sur-couvrent : 91,8 %**, hors de [75 %, 85 %]. Les
  fourchettes sont donc prudentes, trop larges au sens de ce critère, surtout dans les
  unités presque toujours pleines (SMR : 97-98 %). La mesure par PIT randomisé (82,7 %)
  indique qu'une grande part de l'écart vient de l'atome à 0 lit (unité pleine) et non
  d'une loi trop dispersée ; mais le critère pré-enregistré est l'intervalle inclusif,
  et il échoue. Pistes, à valider sur une nouvelle période et non sur celle-ci : contraindre
  les arrivées par la place disponible (le surplus attend aux urgences, ce qui est la
  réalité des lits brancards), ou publier pour les unités pleines « P(au moins 1 lit) »
  plutôt qu'une fourchette.
- **(c) réussi.** Sous une hausse de 50 % des arrivées pendant trois semaines,
  l'intervalle gelé tombe à 66,0 % de couverture ; l'ACI tient 75,8 % poolé (77-79 % de
  J+1 à J+3, 73 % à J+6-J+7, car l'information arrive plus tard aux horizons longs). C'est
  à la limite basse de la tolérance (±5 points).
- **(d) réussi.** Lits brancards à 10 h : rapport de MAE 0,87 poolé ; 1,09 à J+7, donc au
  bout de la semaine la référence saisonnière fait aussi bien.
- Informatif : la MAE des lits disponibles est inférieure à la persistance à chaque
  horizon (2,68 contre 3,01 poolé), sauf en réanimation et en SMR où rien ne bouge beaucoup.
