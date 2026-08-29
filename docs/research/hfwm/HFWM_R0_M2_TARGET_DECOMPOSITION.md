# HFWM-R0 M2 — Décomposition exploratoire inflow / occupation

## Statut épistémique

Cette analyse est **exploratoire** et utilise une seule copie des prédictions
déterministes M2. Elle ne modifie ni métrique, ni seuil, ni résultat. Elle ne
démontre aucune cause.

```yaml
candidate_status: REJECTED_BY_OCCUPANCY_GUARDRAIL
procedural_basis: PRE_REGISTERED_POINT_ESTIMATE_RULE
primary_superiority: INCONCLUSIVE
primary_inferiority: NOT_DEMONSTRATED
occupation_guardrail: FAILED_PROCEDURALLY
true_occupation_regression: NOT_ESTIMATED_WITH_DECISION_GRADE_PRECISION
world_model_advantage: NOT_TESTABLE_ON_M1
```

## Signal observé

| Target | Local NMAE | Partagé NMAE | Delta relatif | Biais local → partagé | Variance résiduelle locale → partagée |
|---|---:|---:|---:|---:|---:|
| occupation | 0.4463524620 | 0.5236052645 | **+17.3076 %** | -0.503562 → -0.091460 | 7.031657 → 11.864727 |
| inflow | 0.5896901649 | 0.5809256174 | **-1.4863 %** | 0.608380 → 0.675731 | 7.606422 → 6.918631 |

Le biais moyen occupation se rapproche de zéro, mais sa variance augmente de
68.73 %. La divergence n'est donc pas un simple décalage global. La corrélation
des résidus occupation–inflow passe de `0.46521` local à `0.37119` partagé; la
corrélation des deltas d'erreur absolue entre targets n'est que `0.15243`.

## Horizon, régime et entité

| Strate occupation | Local MAE | Partagé MAE | Delta |
|---|---:|---:|---:|
| pas 1 / 00 h | 1.685863 | 1.820310 | +7.97 % |
| pas 2 / 06 h | 1.890573 | 2.122238 | +12.25 % |
| **pas 3 / 12 h** | **2.433515** | **3.415861** | **+40.37 %** |
| pas 4 / 18 h | 2.917097 | 3.113697 | +6.74 % |
| occupation ≤24, n=14 | 2.906888 | 3.009227 | +3.52 % |
| occupation 25–30, n=12 | 1.689833 | 1.588556 | -5.99 % |
| **occupation ≥31, n=10** | **1.936902** | **3.305710** | **+70.67 %** |
| site/unité 0, n=12 | 2.706713 | 2.958898 | +9.32 % |
| site/unité 1, n=12 | 1.907894 | 1.778628 | -6.78 % |
| **site/unité 2, n=12** | **2.080681** | **3.116554** | **+49.79 %** |

Les trois épisodes de tension sont tous sur le site/unité 2 et les périodes
sont communes entre sites : tension, site, unité et niveau ne sont pas
identifiables séparément. Le résultat localisé est observable; son attribution
causale ne l'est pas.

Missingness exploratoire (`observed_hours_last_6h`) : +45.88 % pour 2 h (n=2),
+41.04 % pour 3 h (n=5), -6.31 % pour 4 h (n=16), +37.37 % pour 5 h (n=12),
-56.45 % pour 6 h (n=1). Les faibles effectifs interdisent une conclusion.

## Échelle, loss, heads et calibration

- Train : occupation moyenne 25.256, écart-type 4.432, IQR 5; inflow moyenne
  9.298, écart-type 3.016, IQR 4.
- L'entraînement utilise les valeurs brutes; la normalisation IQR intervient
  seulement à l'évaluation. Le même `ridge_alpha=1` agit donc sur des échelles
  différentes.
- Chaque target est ajustée par un solve ridge séparé. Il n'existe ni loss
  pondérée commune, ni gradients enregistrés, ni covariance de sortie apprise.
- Les deux heads utilisent les deux états courants comme inputs, mais leur
  distribution jointe n'est pas modélisée.
- Couverture occupation : 94.44 % local contre 91.67 % partagé; largeur moyenne
  12.504 contre 13.512. Inflow couvre 97.22 % pour les deux.
- Dérive free-running : 1.04184 local contre 1.04999 partagé.

## Identité stock–flux

L'identité attendue est
`occupation(t+1) = occupation(t) + admissions - sorties +/- transferts`.
M1 ne contient qu'un `inflow_last_6h` agrégé et l'occupation; admissions
effectives, sorties, transferts et capacité sont absents. La conservation et la
cohérence stock–flux sont donc **non testables**, pas échouées.

## Registre des explications

| Explication | Statut | Justification |
|---|---|---|
| negative transfer direct entre losses inflow/occupation | NOT_SUPPORTED | Solves et coefficients séparés; aucune pondération de loss commune. |
| pondération défavorable à l'occupation | NOT_SUPPORTED | Aucune pondération ou loss multi-target enregistrée. |
| échelles brutes + ridge commun | PLAUSIBLE | Échelles différentes observées, mais même traitement local/partagé; interaction avec pooling non isolée. |
| capacité partagée insuffisante | PLAUSIBLE | 18 paramètres partagés contre 54 agrégés locaux; aucune ablation de capacité. |
| heads marginales sans distribution jointe | SUPPORTED_BY_EXISTING_EVIDENCE | Ajustements séparés et aucune covariance apprise; le lien avec la régression reste non démontré. |
| spécialisation locale par site | SUPPORTED_BY_EXISTING_EVIDENCE | Trois modèles locaux routés par site contre un modèle poolé sans adaptation. |
| negative transfer inter-site/régime | PLAUSIBLE | Dégradation concentrée site 2/haute occupation; facteurs confondus. |
| missingness comme cause | UNTESTED | Signal hétérogène, cellules très peu nombreuses, pas de fraîcheur par variable. |
| incohérence stock–flux comme cause | UNTESTED | Sorties/transferts/admissions effectives absents. |
| gradients ou instabilité d'optimisation | NOT_SUPPORTED | Solve fermé déterministe; aucun gradient ni optimisation itérative. |

## Conclusion exploratoire

Les preuves existantes supportent la présence d'une spécialisation locale et
l'absence de dynamique jointe explicite. Elles rendent plausible un effet de
pooling inter-site dans les régimes de forte occupation, sans identifier sa
cause. Elles ne permettent pas de choisir entre adaptation site, capacité,
normalisation ou structure stock–flux. M3 doit d'abord enrichir les variables et
le plan d'échantillonnage, puis tester une seule modification pré-enregistrée.
