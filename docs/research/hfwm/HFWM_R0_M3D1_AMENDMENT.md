# HFWM-R0 M3D.1 — Amendement provenance et statistique

## Incident AGORA et règle de provenance

L'affirmation initiale est corrigée ainsi : **« cité comme figurant dans un schéma du
règlement intérieur ; l'extraction texte du PDF utilisée lors du challenge ne contient
pas le terme ; non vérifié à ce stade »**. Elle est classée `UNSUPPORTED_REMOVE`. La
première occurrence enregistrée dans Git est le commit `6cd4819` (`chore(hfwm): freeze
M3D.1 release content`) ; ce point de provenance ne date pas l'édition réelle et ne
prouve pas l'attribution sémantique historique. Le terme reste absent du document
partenaire et son rôle historique demeure non vérifié.

Une vérification indépendante ultérieure du PDF actuellement servi par HCL, mis à jour en
mars 2026, a trouvé une attestation textuelle plus forte : annexe 9, article 9, page PDF
166, la plateforme AGORA est explicitement reliée au dépôt des demandes adressées au
secrétariat du Comité Scientifique et Éthique. Cette découverte est une nouvelle preuve
versionnée, interne seulement ; elle ne réhabilite pas la première attribution non
vérifiée et ne réintroduit pas AGORA dans la demande partenaire.

Le gate du ledger est désormais : **la source doit attester le rôle ou le fait affirmé,
pas seulement contenir le terme**. Chaque claim `SOURCED_OFFICIAL` porte
`attests_asserted_role: true`; le validateur échoue autrement.

## Collision CSE et ancrage HCL

Le règlement HCL emploie `CSE` pour le Comité Social d'Établissement à l'article 21 et,
dans l'annexe 9, pour le Comité Scientifique et Éthique de la recherche sur les données de
santé. La demande développe le second sens à sa première occurrence et utilise ensuite
`CSE-EDS`. L'article 111, page PDF 52, atteste que les HCL opèrent un Entrepôt de Données
de Santé pour la recherche en santé et les études relatives au pilotage hospitalier.

Le ledger contient 24 claims : 14 `SOURCED_OFFICIAL`, 4 `NOT_EXTERNAL_FACT`, 2 registres
`ASSUMED_QUESTION_ONLY` et 4 `UNSUPPORTED_REMOVE`. Aucun claim non soutenu n'est exposé.

## Reachability et dette M2

Le test M3D.1 neuf atteint le générateur final : mêmes seed/entrées = mêmes tirages,
seeds distinctes = tirages distincts, état RNG consommé et seed propagée jusqu'à
`numpy.random.default_rng`. Il ne réutilise pas le test M2 qui était vert avec trois
prédictions identiques.

La décision humaine accepte que la dette M2 ne bloque pas la revue partenaire : le paquet
externe ne contient aucun claim de robustesse inter-seeds M2. Le déterminisme M2 reste
affirmé par conception et non vérifiable sur les poids historiques ; il est interdit de le
citer comme preuve de robustesse ou de levée de fonds. Tout run futur doit persister
`configuration_hash`, `weights_hash`, `prediction_hash` et versions. Le rejeu autorisé des
fits est isolé dans `HFWM_R0_M2_SEED_AUDIT_TICKET.md` et ne modifie pas M2.

## Guardrail, dommage et ICC

La règle de sélection exige désormais, pour COUNT et RATE, puissance primaire >=80 %,
faux-kill <=1 %, inconclusifs <=20 %, couverture valide à +5 %, détection >=80 % à +10 %
et >=95 % à +15 %.

| Scénario | ICC site / bloc | Design minimal | COUNT dommage +10 / +15 | RATE dommage +10 / +15 |
|---|---|---:|---:|---:|
| central postulé | 0,15 / 0,20 | 512 | 91,46 / 99,93 % | 83,80 / 99,75 % |
| pessimiste | 0,30 / 0,35 | 640 | 89,89 / 99,90 % | 81,43 / 99,70 % |

L'ICC central n'est pas estimé sur données partenaire. Son seul ancrage est l'ICC M2
exploratoire 0,14788 sur trois pseudo-sites synthétiques ; il reste une hypothèse fragile.
L'unique groupe HCL interdit tout claim de généralisation inter-organisationnelle.

Sous `delta=0`, le design central retourne 0,06 % / 0,10 % de FAIL et 8,00 % / 16,51 %
d'inconclusifs pour COUNT / RATE. La branche RATE indéterminée concerne donc environ un
cas sans dommage sur six et doit être présentée comme coût opérationnel.

À la frontière, le critère est explicitement `UCB95(P(FAIL | δ=+5 %)) ≤ 5 %` :

```text
COUNT: P(FAIL)=4,55 %, UCB95=4,692 % ≤ 5 %
RATE: P(FAIL)=4,48 %, UCB95=4,622 % ≤ 5 %
```

La règle mécanique de validation de cette procédure est :
`BOUNDARY_CALIBRATION_PASS` si UCB95 ≤5 %,
`INTERVAL_PROCEDURE_UNDERCOVERS` si LCB95 >5 %, sinon
`BOUNDARY_CALIBRATION_NOT_DEMONSTRATED`. Les deux derniers états bloquent ; une
LCB ≤5 % seule ne constitue jamais un passage.

La qualification des sites est distincte de la puissance. **8 sites =
`feasibility_floor`**, jamais une garantie statistique. La qualification finale dépend de
`N_effective` après exclusions et attrition, puis du `blinded sample-size recalculation`.
La projection conservatrice est `1 792 segments bruts -> 717 éligibles sous 60 % de
perte`, au-dessus des 640 requis dans la sensibilité ICC pessimiste.

## Test rétrospectif M2

Le point occupation M2 est `+17,3076 %`. Les neuf deltas d'épisode donnent une erreur
standard IID `0,103106`; avec le design effect exploratoire M2 `2,22192`, l'erreur standard
ajustée est `0,15374`. Même avec la valeur critique normale unilatérale, plus permissive
qu'une correction petits clusters, la nouvelle règle retourne :

```yaml
m3_three_way_retrospective_result: INCONCLUSIVE_GUARDRAIL
historical_m2_procedural_kill_unchanged: true
new_procedure_would_have_issued_scientific_kill: false
```

Le kill M2 reste un kill procédural de l'ancien régime ; il n'aurait pas été prononcé par
la procédure M3.

`INCONCLUSIVE_GUARDRAIL` est un résultat scientifique distinct de PASS et FAIL :

- aucun kill scientifique, aucune conclusion d'infériorité ou de dommage ;
- aucun avancement vers M3-L, M3-F, déploiement ou claim de guardrail satisfait ;
- clôture et gel de l'évaluation (candidat, snapshot, SAP, seuils, seeds et artefacts) ;
- aucun changement post-résultat de seuil, estimand, éligibilité, sites, unités, périodes,
  réglage ou réutilisation des données ;
- statut de gouvernance : `HOLD_NO_ADVANCE`, `M3_RESULT_INCONCLUSIVE` ;
- résolution uniquement par une nouvelle évaluation enregistrée, avec données nouvelles
  et candidat gelé avant l'évaluation des outcomes.

Une décision humaine peut archiver le candidat ou autoriser un nouveau protocole, sans
modifier le statut scientifique de l'évaluation close. Le recalcul de taille blinded reste
séparé : s'il conclut à une taille effective insuffisante, le statut est
`NO_GO_M3_INSUFFICIENT_EFFECTIVE_SAMPLE_SIZE`, qui n'est ni un FAIL scientifique ni un
kill.

## Fenêtre partenaire et agrégation

La demande passe à 28–36 mois : 28 mois minimum, 36 préférés, 8 sites minimum sous recalcul
blinded, 12 sites ciblés, 4 unités/site. À 8 sites, 28 mois produisent 1 792 segments bruts
et environ 717 après 60 % d'attrition (arrondi à l'entier le plus proche). À 8 sites, 36 mois
donnent environ 922 segments éligibles ; la cible 12 sites augmente la marge. Trois ans couvrent trois hivers et
réduisent la confusion saisonnalité/tendance.

La granularité six-heures n'est pas présumée stockée. L'option retenue est une
spécification exécutable par l'établissement dans son environnement : agrégation des
mouvements horodatés en Tier A, réconciliation avec le census quotidien autoritatif, puis
transmission des seuls agrégats et du rapport de conformité. Aucun mouvement pseudonymisé
n'est demandé à Spika à ce stade.

## Gels maintenus

- aucune donnée partenaire, aucun entraînement, aucune architecture ou bake-off ;
- résultats et frontière M2 inchangés ;
- M3-L et M3-F non autorisés ;
- aucune transmission automatique et aucun partenaire contacté.

Les résultats de tests et hashes finaux sont inscrits dans le manifeste M3D.1.
