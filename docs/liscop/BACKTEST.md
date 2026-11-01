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

Aucun à ce jour.

## Résultats

À venir (ajoutés après exécution, sans retoucher ce qui précède).
