# HospitalOS — validation du filtre et valeur décisionnelle

Campagne terminée le 20 novembre 2026. Expérience synthétique sur le moteur INT-1 à quatre unités. Seize structures d’apprentissage et huit structures d’évaluation sont rejouées à trois niveaux de retard moyen, 0, 60 et 180 minutes. Deux futurs par structure, soit 48 épisodes par politique et 192 exécutions en boucle fermée.

**Verdict.** L’estimation des nettoyages inachevés progresse sous retard important. Le critère de validation globale échoue sur les lits libres. Le gain décisionnel est indéterminé, car l’état vrai et l’état déclaré conduisent aux mêmes actions dans ce panel.

## 1. Précision de l’état courant

Erreur absolue moyenne par unité et par observation horaire.

| Retard moyen | Grandeur | Dernier statut déclaré | Filtre probabiliste |
|---|---|---|---|
| 0 min | cleaning | 0.0000 | 0.0000 |
| 0 min | free_beds | 0.0000 | 0.0000 |
| 0 min | transport | 0.0000 | 0.0000 |
| 60 min | cleaning | 0.0918 | 0.0903 |
| 60 min | free_beds | 1.0312 | 1.0553 |
| 60 min | transport | 0.0326 | 0.0398 |
| 180 min | cleaning | 0.1576 | 0.1171 |
| 180 min | free_beds | 1.0397 | 1.1048 |
| 180 min | transport | 0.0690 | 0.0635 |

Le filtre représente l’incertitude sur les fins des services connus. Une tâche de nettoyage terminée peut avoir été suivie d’un placement encore invisible. La correction appliquée ici attribue alors trop de probabilité à l’état libre. L’erreur sur les lits libres augmente aux deux niveaux de retard. L’intervalle à 95 % de la différence déclaré moins filtré est entièrement négatif, sur les huit structures, à 60 et à 180 minutes.

## 2. Calibration des services publiquement en cours

Le score de Brier mesure l’erreur des probabilités de service encore inachevé. Une valeur basse est meilleure. ECE est l’écart de calibration pondéré sur dix classes fixes. Les mêmes services peuvent être évalués à plusieurs heures successives.

| Retard | Service | Observations | Brier déclaré | Brier filtré | ECE |
|---|---|---|---|---|---|
| 0 min | cleaning | 208 | 0.0000 | 0.0000 | 0.0000 |
| 0 min | transport | 116 | 0.0000 | 0.0000 | 0.0000 |
| 60 min | cleaning | 143 | 0.3077 | 0.1200 | 0.1075 |
| 60 min | transport | 84 | 0.1190 | 0.1238 | 0.1076 |
| 180 min | cleaning | 172 | 0.7442 | 0.0632 | 0.0635 |
| 180 min | transport | 62 | 0.4677 | 0.1351 | 0.1220 |

Les nettoyages bénéficient du filtrage à 60 et 180 minutes. L’amélioration des probabilités de transport reste incertaine au vu des intervalles par structure et du petit nombre de tâches. Le modèle ajuste conjointement une durée lognormale arrondie et un retard exponentiel, en incluant les tâches dont la fin n’est pas disponible à la coupure. L’estimation concerne les services dont le début est déjà visible.

## 3. Décisions à budget égal

Les trois planificateurs prospectifs disposent des mêmes paramètres structurels du simulateur. Ils comparent les deux renforts dans le même créneau, sur 24 heures et trois futurs indépendants des futurs évalués. Leurs entrées sont respectivement l’état déclaré, un état échantillonné à partir du filtre et l’état vrai courant. Les durées futures privées sont rééchantillonnées pour le comparateur à état vrai.

Dans les 48 épisodes, les actions du planificateur filtré et du planificateur à état vrai sont identiques à celles du planificateur sur observations. Les valeurs ci-dessous sont les moyennes par épisode, identiques aux trois niveaux de retard.

| Politique | Attente, patients-minutes | Soins non couverts, minutes |
|---|---|---|
| Règle de charge déclarée | 8 984,0625 | 4 033,3750 |
| Planificateur sur observations | 8 984,0625 | 4 033,8125 |
| Planificateur filtré | 8 984,0625 | 4 033,8125 |
| Planificateur à état vrai | 8 984,0625 | 4 033,8125 |

Les heures-agents engagées ont été vérifiées égales dans chaque comparaison appariée. Elles incluent des créneaux démarrant après certaines décisions et pouvant déborder les 24 heures évaluées. Les coûts prévus pour les actions diffèrent entre certains estimateurs, mais leur classement reste identique. Le comparateur à état vrai confirme la faible sensibilité décisionnelle de ce panel à l’estimation d’état avec ce planificateur et ce catalogue.

Les intervalles nuls des différences entre ces trois politiques décrivent leurs trajectoires identiques sur ce panel. Ils ne démontrent aucune équivalence générale. Le choix des structures a été fixé avant les résultats. La présence simultanée de goulots nettoyage et transport n’a pas suffi à produire un test sensible à l’information.

## 4. Limites et suite

Cette campagne ne valide pas le filtre comme estimateur complet de l’hôpital. La prochaine version doit représenter explicitement la succession nettoyage terminé, lit libre puis nouveau placement, avec horodatage de l’événement et date de disponibilité. Elle devra être testée sur de nouvelles structures.

Pour la décision, construire d’abord un panel de développement où les deux renforts peuvent changer de priorité avec l’état disponible. Vérifier l’écart entre le planificateur sur observations et celui connaissant l’état vrai, puis figer une nouvelle famille de scénarios et l’évaluer sur un panel indépendant. Les tests actuels restent conservés.

La connaissance des paramètres structurels par les planificateurs donne un cadre diagnostic favorable. Le transfert à un établissement réel reste à établir.

## 5. Reproductibilité

Le protocole, la procédure de reproduction et les tests figurent dans scripts/filter_validation. Les paramètres ajustés, classes de calibration et résultats résumés sont dans evidence/filter_validation/run. L’archive de campagne contient les 24 fichiers détaillés, les tables de prédictions, les décisions et les empreintes. Huit tests de régression ont passé, dont quatre dédiés à cette campagne. Vingt états échantillonnés ont été vérifiés pour la conservation des lits et la cohérence des transports actifs.
