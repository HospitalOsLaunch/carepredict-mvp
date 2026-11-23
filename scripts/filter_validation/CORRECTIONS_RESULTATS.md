# Récapitulatif des corrections du filtrage — 20 novembre 2026

**Verdict : rejeu public corrigé ; estimation des lits améliorée sur synthétique ; gain décisionnel non établi.** Le profil retenu pour les prochaines boucles est `guarded_campaign.py`, avec inférence des fins de transport désactivée. Le statut reste `PROTOTYPE_UNVALIDATED`.

## Travaux exécutés

- Correction de l’ordre des événements simultanés. Un compte rendu de nettoyage tardif ne peut plus effacer un placement déjà connu. Les événements de salissure ne régressent plus un nettoyage simultané.
- Correction des notifications de transport reçues dans le désordre. Une fin connue est conservée même si le début manque ; les prérequis logiques des étapes connues sont reconstruits.
- Ajout de placements plausibles après nettoyage, avec file d’attente, identité du patient, compatibilité d’isolement et conservation des lits.
- Correction du banc décisionnel : abstention possible, égalités sans dépense, renforts intégralement compris dans le suivi de 24 h et projection limitée au suivi restant.
- Détection d’une régression du filtre transport à une heure de retard, puis désactivation globale de cette composante et nouvelle évaluation indépendante.

## Résultats de la version retenue

Huit nouvelles structures de quatre unités, deux retards moyens de notification, deux futurs par structure. Erreur absolue moyenne par unité et instant ; données entièrement synthétiques. Le comparateur est ici le rejeu public **déjà corrigé**, afin de distinguer le bénéfice probabiliste du correctif informatique.

| Retard | Métrique | Rejeu corrigé | Profil prudent | Gain absolu, IC 95 % |
|---|---|---:|---:|---|
| 60 min | Lits libres | 0.0781 | 0.0202 | 0.0579 [0.0390 ; 0.0754] |
| 60 min | Lits occupés | 0.0996 | 0.0652 | 0.0344 [0.0233 ; 0.0471] |
| 60 min | Nettoyages actifs | 0.1016 | 0.1010 | 0.0006 [-0.0114 ; 0.0141] |
| 60 min | Transports actifs | 0.0404 | 0.0404 | 0.0000 [0.0000 ; 0.0000] |
| 60 min | Patients en file | 0.1283 | 0.1064 | 0.0219 [0.0074 ; 0.0387] |
| 180 min | Lits libres | 0.2637 | 0.0821 | 0.1816 [0.1204 ; 0.2346] |
| 180 min | Lits occupés | 0.3320 | 0.1741 | 0.1579 [0.1096 ; 0.2060] |
| 180 min | Nettoyages actifs | 0.2220 | 0.1360 | 0.0860 [0.0522 ; 0.1310] |
| 180 min | Transports actifs | 0.0742 | 0.0742 | 0.0000 [0.0000 ; 0.0000] |
| 180 min | Patients en file | 0.3815 | 0.3375 | 0.0440 [-0.0045 ; 0.1061] |

L’erreur sur les lits libres diminue de **74,1 %** à 60 minutes et de **68,9 %** à 180 minutes. L’amélioration des lits occupés est aussi positive dans les intervalles par structure. Le gain sur la file à 180 minutes reste incertain. Les transports restent strictement identiques à l’état déclaré ; ce résultat traduit une désactivation, pas une calibration réussie du modèle de transport. Les intervalles proviennent de 2 000 rééchantillonnages des huit structures.

Pour situer le défaut informatique, l’ancien ordre de réception produisait sur ce même panel une erreur de lits libres de 1,702 à 60 minutes et 1,721 à 180 minutes. Le rejeu corrigé seul ramène ces valeurs à 0,078 et 0,264. La plus grande part du gain global vient donc de la correction des événements, et non d’un apprentissage nouveau.

## Boucles de validation et résultats négatifs conservés

1. **V3 principal** : huit nouvelles structures, retards 0/60/180 minutes, deux futurs. Les cinq métriques d’état restent exactes sans retard. À 180 minutes, le filtre complet améliore les lits libres de 0,277 à 0,093. Mais à 60 minutes, l’erreur des transports augmente de 0,0573 à 0,0761, avec un intervalle du gain entièrement négatif. Ce résultat a déclenché le profil prudent.
2. **Qualification des horaires** : cinq horaires sur quatre structures DEV, neuf futurs de projection. L’origine à 10 h est retenue uniquement sur DEV. Sur huit structures TEST inédites, l’état vrai change 8 décisions sur 64, mais le gain moyen d’attente vaut −15,94 patients-minutes, IC 95 % [−69,38 ; 23,44]. Il n’y a donc pas de gain d’attente établi. La consommation moyenne passe de 12 à 14 heures-agents pour ce comparateur ; les soins non couverts diminuent en moyenne de 27,5 minutes. Le filtre conserve les décisions de l’état public.
3. **V4 prudent** : huit autres structures inédites, retards 60/180 minutes, deux futurs. Les résultats d’état sont ci-dessus. Les décisions, l’attente, les soins non couverts, la file terminale et les heures-agents sont identiques au planificateur public corrigé. Aucun rejet d’action n’est observé.

Au total, les trois tests indépendants couvrent **24 structures inédites et 96 scénarios structure–retard–futur**, chacun comparant quatre politiques, soit 384 trajectoires décisionnelles de 24 h, hors projections prospectives et DEV. Les fichiers de protocole et de code ont été empreintés avant chaque test ; leurs empreintes ont été revérifiées après exécution. Aucun scénario TEST n’a été supprimé.

## Validation technique et portée

**14 tests passent** : dix tests de filtrage et de reconstruction, plus quatre tests existants du filtre quotidien et de l’interface JEPA. Les nouveaux tests couvrent les réceptions désordonnées, la visibilité temporelle, les placements avec isolement, les renforts dans le suivi et l’invariance des transports du profil prudent. Ils ne remplacent pas une exécution de toute la CI du dépôt.

Les modifications du moteur portent sur le rejeu des observations, sans modifier la dynamique qui génère la vérité. Le filtre probabiliste et le planificateur corrigé restent un prototype dans le banc d’évaluation ; cette campagne ne les déploie pas dans un produit hospitalier.

Le comparateur `legacy` restaure l’ancien ordre de rejeu, avec les autres corrections communes. Les changements d’action entre cet ancien ordre et le rejeu corrigé ne constituent pas un bénéfice clinique démontré. Par exemple, le panel prudent présente une attente moyenne publique légèrement supérieure à celle de l’ancien ordre, alors que le panel principal donne l’inverse.

Les séjours, sorties, arrivées et débuts de service encore invisibles ne sont pas complètement inférés. L’heure d’un placement supposé reste approximative. Le planificateur reçoit les paramètres structurels synthétiques et ne compare ici que nettoyage, transport et abstention. Ces conditions limitent toute extrapolation.

## Suite prioritaire

Conserver les corrections déterministes et le profil prudent pour les prochaines expériences. Étendre ensuite l’estimation aux sorties et aux débuts de service invisibles, avec des critères de calibration par composante. Il faut démontrer un gain sur les conséquences des actions avec garde-fous avant de relancer un entraînement JEPA de grande ampleur. Aucun réentraînement JEPA n’a été effectué dans cette correction ; les anciens scores d’entraînement ne sont pas revalidés par ce seul correctif.

Les commandes de reproduction sont dans [CORRECTIONS.md](CORRECTIONS.md). Les résultats bruts, résumés, protocoles, empreintes et environnement sont conservés dans `evidence/filter_correction`.
