# HFWM-R0 M3D — Statistical Analysis Plan pré-data

## Statut et portée

Ce SAP est gelé avant toute donnée partenaire. Il prépare uniquement l'examen du banc
M3. Il n'autorise ni accès aux données, ni M3-L, ni M3-F, ni entraînement.

Question scientifique : **une dynamique jointe stock-flux apporte-t-elle un avantage
mesurable sur des propriétés que les forecasters locaux ne représentent pas, sans
dépasser le guardrail occupation ?** Le contrôle principal est le modèle local gelé.
HGBR/CQR reste une référence externe non candidate ; le mécanistique est un contrôle
structurel ; le candidat partagé M2 reste mort et historique.

## Résultat M2 conservé

```yaml
candidate_status: REJECTED_BY_OCCUPANCY_GUARDRAIL
procedural_basis: PRE_REGISTERED_POINT_ESTIMATE_RULE
primary_superiority: INCONCLUSIVE
primary_inferiority: NOT_DEMONSTRATED
occupation_guardrail: FAILED_PROCEDURALLY
true_occupation_regression: NOT_ESTIMATED_WITH_DECISION_GRADE_PRECISION
world_model_advantage: NOT_TESTABLE_ON_M1
```

M2 a rejeté procéduralement le candidat parce que son point estimate d'occupation a
franchi le guardrail pré-enregistré. Le banc M1 est trop peu puissant pour établir la
direction ou l'amplitude vraie de cet effet.

## Population, unités et eligibility mask

- Population : unités-périodes des seuls sites expressément autorisés, après contrôle
  du contrat sémantique, temporel, stock-flux et capacité.
- Hiérarchie : `hospital_group → hospital_site → unit → temporal_block → episode`.
- Unité d'analyse : épisode complet. Targets et pas de rollout restent groupés.
- Les unités d'un site, les fenêtres chevauchantes, les pas et les targets ne multiplient
  jamais la taille indépendante.
- L'`eligibility_mask` est produit avant outcomes par `(site, unit, temporal_block)` à
  partir de `HFWM_R0_M3_REPLAYABILITY_SPEC.yaml`. Chaque exclusion conserve son motif.
  Toute sélection fondée sur la performance est interdite.
- HCL constitue une organisation ; ses 13 hôpitaux éventuels sont des sites imbriqués,
  pas 13 institutions indépendantes.

## Endpoints gelés

Endpoint primaire : score joint free-running, normalisé par des échelles calculées sur
la partition d'apprentissage seulement, évalué à 1, 2 et 4 pas. La définition numérique
finale exige que les variables Tier A soient confirmées et que la puissance simulée soit
acceptable ; à défaut M3-L reste bloqué. L'hypothèse primaire est un gain relatif de 5 %
face au contrôle local, avec borne de confiance cluster/block démontrant un gain > 0.

Guardrail critique : régression relative de la MAE free-running de
`patient_census_count` face au contrôle local, frontière inchangée `+5 %`. Si le partenaire
définit « occupation » comme un taux ou une autre mesure, le guardrail M3 n'est pas une
continuation métrique directe de M2.

```text
delta_occ_relative
= (error_candidate_absolute - error_local_absolute) / error_local_absolute
```

Une valeur positive indique une régression. L'analyse rapporte aussi
`error_candidate_absolute`, `error_local_absolute` et `delta_occ_absolute`. Le dénominateur
est `error_local_absolute`. Si celui-ci varie d'un facteur supérieur à 2 par rapport au
banc ayant justifié le seuil, ou devient proche de zéro, une
`GUARDRAIL_DENOMINATOR_REVIEW_REQUIRED` est conduite sur le contrôle seul, avant accès
aux résultats candidat. Elle n'autorise aucun changement rétroactif du seuil.

Métriques secondaires : fermeture stock-flux, score joint par pas, calibration jointe,
dérive free-running, non-finitude, erreurs par target/horizon, couverture et largeur des
intervalles. Les analyses par site, régime, missingness et tension sont exploratoires.

Contraintes confirmatoires uniquement si testables après le gate data : identité de
conservation sur `patient_census_count`, non-négativité des comptes et flux, cohérence des
transferts couplés, et cohérence census/capacité. Un taux n'est jamais soumis à l'identité
additive.

## Inférence et puissance

- Alpha unilatéral : `0.05`; puissance cible : `0.80`; gain cible : `5 %`.
- Méthode M3D.1 : simulation hiérarchique de statistique suffisante avec unités imbriquées
  dans les sites et valeurs critiques unilatérales calibrées avant les scénarios. La règle
  exige aussi une puissance de détection >=80 % à +10 % de dommage et >=95 % à +15 %.
  Le design central est 512 segments ; le scénario ICC pessimiste exige 640 segments.
  Une future substitution par wild-cluster/bootstrap hiérarchique exige un amendement
  pré-outcomes et une démonstration équivalente du risque à la frontière. Épisodes entiers,
  targets et rollout steps restent groupés.
- La valeur 184 épisodes est une hypothèse M2C, pas une garantie ni un gate. Le point 384
  était une planification antérieure ; il échoue la règle conjointe COUNT/RATE. Le nombre
  final est dérivé de la règle conjointe et ne constitue pas une demande partenaire.
- Un recalcul blinded est permis sur structure et variance seulement, sans accès aux
  résultats par bras. Toute modification est versionnée et hashée avant déblindage ; elle
  ne peut réduire la protection contre un effet de 5 %.
- L'ICC site central 0,15 et l'ICC intra-bloc 0,20 sont postulés, non estimés sur données
  partenaire. La sensibilité pessimiste utilise 0,30 et 0,35. L'unique groupe HCL ne compte
  jamais comme plusieurs organisations indépendantes.

Règle occupation à trois voies :

```text
PASS_GUARDRAIL: borne supérieure unilatérale 95 % de la régression <= +5 %
FAIL_GUARDRAIL: borne inférieure unilatérale 95 % de la régression > +5 %
INCONCLUSIVE_GUARDRAIL: tous les autres cas
```

Le seul critère de calibration à la frontière est `UCB95(P(FAIL | δ=+5 %)) ≤ 5 %`.
Pour le design central, les valeurs gelées sont `COUNT: P(FAIL)=4,55 %, UCB95=4,692 % ≤ 5 %`
et `RATE: P(FAIL)=4,48 %, UCB95=4,622 % ≤ 5 %`.
La classification implémentée est : `BOUNDARY_CALIBRATION_PASS` si UCB95 ≤5 %,
`INTERVAL_PROCEDURE_UNDERCOVERS` si LCB95 >5 %, sinon
`BOUNDARY_CALIBRATION_NOT_DEMONSTRATED`; les deux derniers états bloquent.

Sous vraie régression nulle, le design doit satisfaire `P(FAIL)<=1 %` et
`P(INCONCLUSIVE)<=20 %`. `INCONCLUSIVE_GUARDRAIL` interdit non-infériorité, promotion,
déploiement et kill scientifique ; l'action de gouvernance est `HOLD_NO_ADVANCE` et le
statut est `M3_RESULT_INCONCLUSIVE`. L'évaluation, ses données et ses artefacts sont
clos et gelés. Aucune extension de collecte
après consultation des résultats n'est autorisée dans ce protocole. Une collecte
supplémentaire exige un nouveau protocole, SAP, plan de puissance, traitement de
multiplicité ou design séquentiel pré-enregistré, et un hash antérieur aux nouveaux
résultats. La règle M2 au seul point estimate reste un historique procédural seulement.

Un recalcul blinded de taille est administratif et séparé de la décision d'effet. Une
taille effective insuffisante produit `NO_GO_M3_INSUFFICIENT_EFFECTIVE_SAMPLE_SIZE`, sans
conclusion scientifique de FAIL.

La grille utilise 40 000 simulations valides par cellule ordinaire. La cellule
`delta=+5 %` du design retenu utilise 82 000 simulations et exige une demi-largeur IC
Monte-Carlo 95 % <=0,15 point pour `P(FAIL)`. Si la borne inférieure de cet IC dépasse
5 %, le statut devient `INTERVAL_PROCEDURE_UNDERCOVERS` et M3D.1 est bloqué.

La puissance dommage du design central est 91,46 % / 99,93 % à +10 % / +15 % pour COUNT,
et 83,80 % / 99,75 % pour RATE. L'inconclusivité RATE sous absence de dommage est 16,51 %
et doit être rapportée comme coût opérationnel, jamais comme résultat anodin.

Appliquée rétrospectivement au point M2 `+17,3076 %`, avec les 9 épisodes et le design
effect exploratoire 2,22192, la règle M3 retourne `INCONCLUSIVE_GUARDRAIL`. Le kill M2
reste historiquement valide sous sa règle procédurale au point estimate, mais la procédure
M3 n'aurait pas prononcé un kill scientifique.

## Valeurs manquantes, corrections et temporalité

Les features exigent `available_at <= as_of`. Une correction future ne réécrit pas un
snapshot passé. Sans `available_at` historique : évaluation rétrospective seulement,
aucun claim de disponibilité temps réel ; `extract_generated_at` est une borne
documentaire, pas un substitut silencieux. Pas d'imputation utilisant test/outcomes. Les
méthodes d'imputation et indicateurs de missingness sont figés avant déblindage.

La série six-heures est reconstruite par l'établissement à l'aide de
`HFWM_R0_M3_AGGREGATION_SPEC.yaml`, dans son environnement autorisé, puis réconciliée avec
le census quotidien autoritatif. Aucun mouvement pseudonymisé n'est demandé à Spika au
Tier A. Tout futur run doit persister configuration, poids, prédictions et hashes séparés.

## Multiplicité et analyses

L'endpoint primaire et le guardrail sont co-requis ; aucun claim primaire n'est permis si
l'un échoue ou est inconclusif. Les métriques jointes secondaires sont hiérarchisées et
descriptives tant qu'une procédure de multiplicité n'est pas ajoutée avant données. Les
strates site, unité, niveau de census, tension, missingness et count/rate sont exploratoires.
Il est interdit de changer target, seuil, horizon ou strate après résultats.

## Arrêts et kill criteria

1. contrat sémantique, transfert couplé, capacité ou rejouabilité bloquant : ne pas ouvrir
   M3-L ;
2. fuite temporelle, chevauchement de split ou correction future : invalider le résultat ;
3. puissance de planification insuffisante ou règle conjointe non satisfaite : M3-L reste
   non autorisé ;
4. `FAIL_GUARDRAIL` : pas de promotion du candidat ;
5. `INCONCLUSIVE_GUARDRAIL` : statut `M3_RESULT_INCONCLUSIVE`, sans claim, promotion,
   kill scientifique ou extension de collecte dans le même protocole ;
6. fermeture stock-flux non testable : aucun claim de dynamique jointe.

## Gel et amendements

Le SHA-256 de ce fichier est inscrit dans `artifacts/hfwm-r0/m3d/manifest.json`. Toute
modification future crée une version nouvelle, datée et hashée avant accès aux outcomes.
Le design ne peut être modifié à partir des performances observées.
