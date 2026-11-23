# Corrections du 20 novembre 2026

Cette campagne prolonge V2. Elle conserve ses résultats négatifs dans `RESULTATS.md` et ses preuves dans `evidence/filter_validation`. Les nouveaux résultats figurent dans `CORRECTIONS_RESULTATS.md` et `evidence/filter_correction`.

## Défauts corrigés

### Reconstruction des événements

Le rejeu public résolvait les égalités d'heure selon l'ordre de réception. Un `cleaning_done` tardif pouvait remplacer un `placed` déjà connu au même instant, faisant disparaître le nouvel occupant. De même, `bed_dirty` pouvait écraser un début de nettoyage simultané. `PublicStreamN._bed` applique désormais l'ordre physique des états à heure égale. Un événement réellement plus récent garde la priorité.

Un `transport_done` pouvait aussi être reçu avant `transport_start`. La reconstruction conserve désormais cette fin même lorsque le début manque. Un transport commencé ou terminé implique les prérequis de préparation et d'autorisation, même si leurs notifications arrivent plus tard. Ces corrections sont intégrées à `src/hospitalos/howmint/world.py`. Le moteur de génération de la vérité n'est pas modifié.

### Estimation des placements invisibles

L'ancien filtre ajoutait systématiquement un lit libre après chaque nettoyage estimé terminé. Le nouveau prototype échantillonne les fins de service puis réconcilie les lits disponibles avec les demandes déjà connues, selon les règles d'isolement et de file du moteur. Un placement retire la demande de la file, crée un seul séjour et occupe un seul lit. Les identités et capacités sont vérifiées à chaque échantillon. Aucun nouvel arrivant invisible n'est inventé.

Il s'agit d'une approximation contrainte. L'heure réelle d'un placement invisible n'est pas identifiée, les débuts de service et sorties encore invisibles ne sont pas tous inférés. Le filtre ne constitue donc pas encore une distribution bayésienne complète de l'hôpital.

### Planificateur de la campagne

L'action `none` est maintenant un candidat explicite. Les égalités privilégient l'abstention, au lieu de dépenser systématiquement le budget. Les renforts doivent se terminer dans les 24 h évaluées, et la projection utilise uniquement la durée de suivi restante. Les politiques partagent le même plafond journalier ; leur consommation effective est mesurée, sans imposer artificiellement une dépense identique.

Ces changements concernent le planificateur expérimental `correction.py`. Le catalogue général des interventions reste celui d'INT-1.

## Protocole

Le protocole est figé dans `correction_protocol.json` et son empreinte dans `evidence/filter_correction/frozen.sha256`. Les lois de service sont celles ajustées sur l'apprentissage V2, sans réentraînement. Une structure DEV vérifie l'exécution. Le test utilise huit nouvelles structures, trois retards moyens de notification, deux réalisations futures par structure et quatre politiques. Aucun résultat TEST ne sélectionne les paramètres ou les structures.

La calibration est mesurée chaque heure sur une trajectoire commune sans intervention. Les décisions utilisent l'historique propre à chaque politique. Les projections ont accès aux mêmes paramètres structurels synthétiques, avec des innovations indépendantes des futurs évalués. Le comparateur à état vrai connaît l'état courant, sans connaître les durées futures effectives. Ce diagnostic reste limité par les trois tirages de projection et le catalogue restreint aux renforts de nettoyage/transport.

Les quatre estimateurs d'état sont l'ancien ordre de rejeu (`legacy`), le rejeu corrigé (`public`), la correction analytique des services (`service_only`) et la reconstruction avec placements (`lifecycle`, 16 particules). L'ablation `legacy` restaure uniquement l'ancien ordre des événements. Les autres corrections de reconstruction sont communes ; ce n'est pas une reproduction complète du binaire V2.

Les intervalles de confiance rééchantillonnent huit structures, pas les milliers d'observations comme si elles étaient indépendantes. Les métriques d'état sont par unité et par instant. Les coûts de décision sont par épisode de 24 h.

Un diagnostic séparé `qualify_decisions.py` compare cinq horaires d'origine sur quatre structures DEV distinctes, avec neuf futurs de projection. Il examine l'activité des services et la sensibilité des actions à l'état vrai. Il ne modifie pas le protocole du test principal.

## Reproduction

À la racine du dépôt avec NumPy, SciPy, Pandas et PyTorch installés.

```bash
python -m unittest discover -s scripts/filter_validation -p 'test_*.py'
python -m unittest discover -s scripts/filter_jepa -p 'test_*.py'
for index in 0 1 2 3 4 5 6 7; do
  python scripts/filter_validation/correction.py --index "$index" --out evidence/filter_correction/run
done
python scripts/filter_validation/analyse_correction.py evidence/filter_correction/run
python scripts/filter_validation/qualify_decisions.py
```

L'archive de preuves conserve les sorties brutes DEV et TEST ainsi que les tableaux CSV. Le résumé JSON est aussi disponible directement dans le dépôt. Les résultats restent entièrement synthétiques.

## Deux boucles supplémentaires

Le diagnostic DEV a sélectionné l'origine 58 h, soit 10 h locale, pour un test indépendant sur huit nouvelles structures à 180 minutes de retard. `timing_protocol.json` fixe neuf tirages prospectifs. L'évaluation complète est conservée dans `evidence/filter_correction/timing_test`.

V3 a aussi révélé une régression significative sur le nombre de transports en cours à 60 minutes de retard. La version prudente de `guarded_filter.py` désactive donc toute inférence de fin de transport, quel que soit le retard. Elle conserve les transports déclarés et continue l'inférence nettoyage–placement. L'invariance de la liste des transports actifs est testée et vérifiée sur chaque particule. Ce choix global évite d'ajuster un seuil aux résultats du test.

`guarded_protocol.json` et `guarded_frozen.sha256` fixent un troisième test indépendant sur huit nouvelles structures, deux retards et deux futurs. L'estimateur est substitué explicitement dans le même banc d'évaluation. La colonne `service_only` garde l'ancien estimateur complet comme ablation ; la colonne `lifecycle` désigne ici la version prudente. Les anciennes commandes V3 reproduisent leur version d'origine.

```bash
for index in 0 1 2 3 4 5 6 7; do
  python scripts/filter_validation/timing_test.py --index "$index" --out evidence/filter_correction/timing_test
  python scripts/filter_validation/guarded_campaign.py --index "$index" --out evidence/filter_correction/guarded_test
done
python scripts/filter_validation/analyse_correction.py evidence/filter_correction/timing_test --expected 8
python scripts/filter_validation/analyse_correction.py evidence/filter_correction/guarded_test --expected 16
```
