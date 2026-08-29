# HFWM-R0 M3D.1 — Plan de puissance hiérarchique pré-data

## Contrat et règle conjointe

La simulation est synthétique, sans donnée partenaire ni entraînement. La frontière
relative de 5 % et les résultats M2 sont inchangés.

```yaml
delta_occ_relative: (error_candidate_absolute - error_local_absolute) / error_local_absolute
positive_delta_meaning: regression
relative_guardrail_margin: 0.05
alpha_one_sided: 0.05
target_power: 0.80
max_false_kill_under_h0: 0.01
max_inconclusive_rate_under_h0: 0.20
min_harm_detection_power_delta_10pct: 0.80
min_harm_detection_power_delta_15pct: 0.95
historical_m2c_estimate: 184
historical_estimate_is_unlock_gate: false
previous_planning_point: 384
central_internal_requirement: 512
pessimistic_icc_internal_requirement: 640
training_authorized: false
```

Le plus petit design doit satisfaire simultanément, pour COUNT et RATE : puissance
primaire >=80 %, `P(FAIL|delta=0)<=1 %`, `P(INCONCLUSIVE|delta=0)<=20 %`, procédure
non sous-couvrante à `delta=+5 %`, `P(FAIL|delta=+10 %)>=80 %` et
`P(FAIL|delta=+15 %)>=95 %`.

## Hypothèses de dépendance

L'ICC site central `0,15` est **postulé**, non estimé sur des données partenaire. Il est
seulement ancré sur l'ICC exploratoire M2 `0,14788`, obtenu sur trois pseudo-sites
synthétiques. L'ICC intra-bloc central `0,20` est également postulé. Ces chiffres sont
les paramètres les plus fragiles du plan et imposent un recalcul blinded sur données de
structure avant toute autorisation M3-L.

Le design central minimal est `episodes_512` : 1 groupe HCL, 8 sites, 4 unités/site,
8 blocs indépendants et 2 segments non chevauchants par unité-bloc ; facteur de design
1,65. Un scénario pessimiste (`ICC_site=0,30`, `ICC_intra-bloc=0,35`) porte le minimum à
`episodes_640` : 10 sites, 4 unités/site, 8 blocs, 2 segments/unité-bloc ; facteur 2,25.
**8 sites = `feasibility_floor`**, pas une garantie de puissance. La qualification finale
dépend de `N_effective` après exclusions/attrition et du `blinded sample-size
recalculation`. Un unique groupe HCL ne permet aucun claim de généralisation
inter-organisationnelle.

## Grille centrale

Chaque cellule ordinaire utilise 40 000 simulations valides. Le tableau donne
`puissance / P(FAIL|0) / P(INCONCLUSIVE|0) / P(FAIL|+5)`.

| Segments | Sites×unités×blocs×segments/bloc | Effet | COUNT | RATE |
|---:|---|---:|---|---|
| 192 | 6×2×8×2 | 1,35 | 61,60 / 0,36 / 38,52 / 4,48 % | 47,67 / 0,37 / 52,23 / 4,23 % |
| 224 | 7×2×8×2 | 1,35 | 69,89 / 0,19 / 30,36 / 4,43 % | 57,24 / 0,28 / 42,96 / 4,55 % |
| 256 | 8×2×8×2 | 1,35 | 77,25 / 0,10 / 22,43 / 4,65 % | 64,69 / 0,15 / 34,43 / 4,42 % |
| 288 | 6×3×8×2 | 1,50 | 73,69 / 0,25 / 26,28 / 4,75 % | 60,09 / 0,35 / 39,52 / 4,42 % |
| 320 | 8×2×10×2 | 1,35 | 85,18 / 0,09 / 15,14 / 4,51 % | 73,58 / 0,12 / 26,26 / 4,44 % |
| 352 | 11×2×8×2 | 1,35 | 88,01 / 0,05 / 11,78 / 4,65 % | 77,52 / 0,11 / 22,40 / 4,37 % |
| 384 | 8×3×8×2 | 1,50 | 87,66 / 0,07 / 12,32 / 4,65 % | 76,61 / 0,09 / 23,31 / 4,25 % |
| **512** | **8×4×8×2** | **1,65** | **91,71 / 0,06 / 8,00 / 4,55 %** | **83,86 / 0,10 / 16,51 / 4,48 %** |
| 640 | 10×4×8×2 | 1,65 | 95,44 / 0,03 / 4,68 / 4,33 % | 89,89 / 0,07 / 10,23 / 4,36 % |
| 768 | 12×4×8×2 | 1,65 | 97,43 / 0,02 / 2,64 / 4,56 % | 93,82 / 0,03 / 6,22 / 4,50 % |

`384` échoue RATE. Le design central 512 satisfait la règle complète. Sous l'ICC
pessimiste, 512 échoue mais 640 satisfait les six critères pour COUNT et RATE.

## Puissance de détection du dommage — design central 512

| Sémantique | Vrai delta | P(PASS) | P(INCONCLUSIVE) | P(FAIL) | Qualification |
|---|---:|---:|---:|---:|---|
| COUNT | 0 % | 91,95 % | 8,00 % | **0,06 %** | faux-kill sans dommage |
| COUNT | +5 % | 4,44 % | 91,01 % | **4,55 %** | rejet à la marge |
| COUNT | +10 % | 0,04 % | 8,50 % | **91,46 %** | puissance dommage |
| COUNT | +15 % | 0,00 % | 0,08 % | **99,93 %** | puissance dommage |
| RATE | 0 % | 83,39 % | 16,51 % | **0,10 %** | faux-kill sans dommage |
| RATE | +5 % | 4,26 % | 91,26 % | **4,48 %** | rejet à la marge |
| RATE | +10 % | 0,07 % | 16,13 % | **83,80 %** | puissance dommage |
| RATE | +15 % | 0,00 % | 0,26 % | **99,75 %** | puissance dommage |

Le guardrail n'est donc pas inerte : même dans la sémantique RATE, il détecte 83,80 %
des dommages vrais de +10 % et 99,75 % des dommages de +15 %. L'inconclusivité RATE sous
absence de dommage reste néanmoins élevée, 16,51 %, et doit être présentée comme coût
opérationnel du contrôle d'erreur.

La cellule `delta=+5 %` utilise 82 000 simulations valides. IC Monte-Carlo 95 % de
`P(FAIL|+5%)` : COUNT `[4,407 % ; 4,692 %]`, RATE `[4,339 % ; 4,622 %]` ; les bornes
supérieures (UCB95) restent ≤5 %. Le seul critère de passage est
`UCB95(P(FAIL | δ=+5 %)) ≤ 5 %` :

```text
COUNT: P(FAIL)=4,55 %, UCB95=4,692 % ≤ 5 %
RATE: P(FAIL)=4,48 %, UCB95=4,622 % ≤ 5 %
```

Toutes les cellules ordinaires ont une demi-largeur <=0,5 point.

## Application rétrospective à M2

M2 contient 9 épisodes indépendants au mieux. Le point occupation est `+17,3076 %` ;
l'erreur standard IID des deltas relatifs par épisode est `0,103106`. Avec le facteur de
design exploratoire M2 `2,22192`, l'erreur standard ajustée est `0,15374`. Même en utilisant
la valeur critique normale unilatérale 95 % — plus permissive qu'une correction petits
clusters — la borne inférieure reste sous +5 %. La nouvelle règle retourne donc :

```yaml
m2_point_estimate: 0.1730757844
m3_three_way_retrospective_result: INCONCLUSIVE_GUARDRAIL
historical_m2_procedural_kill_unchanged: true
new_procedure_would_have_issued_scientific_kill: false
```

Le kill M2 demeure la conséquence de sa règle procédurale pré-enregistrée au point
estimate. Il ne doit pas être présenté comme un résultat que le régime M3 aurait reproduit.

## Décision attachée à INCONCLUSIVE et dénominateur

`INCONCLUSIVE_GUARDRAIL` produit `HOLD_NO_ADVANCE` et `M3_RESULT_INCONCLUSIVE` : aucun
kill scientifique, promotion, non-infériorité, déploiement ou claim de guardrail satisfait
n'est permis. L'évaluation est close et gelée. Seule une nouvelle évaluation indépendante,
pré-enregistrée et utilisant des données non utilisées dans ce run peut la résoudre.
Un recalcul blinded séparé peut conclure `NO_GO_M3_INSUFFICIENT_EFFECTIVE_SAMPLE_SIZE`;
ce statut n'est pas un FAIL scientifique.

Le plan rapporte les deux erreurs absolues et les deltas absolu/relatif. Si l'erreur du
contrôle change d'un facteur >2 ou devient proche de zéro, une revue blinded du contrôle
précède les outcomes candidat et ne peut modifier rétroactivement le seuil. Tout recalcul
de taille reste versionné et hashé avant déblindage.
