# HospitalOS · Revue technique de l'estimation des gains

**Objet.** Estimation des patient-minutes d'attente évitées par le cockpit et prévision de l'occupation à la relève. Revue rétrospective du 24 novembre 2026 sur la PR #50, commit `85a8ee794ac8952c134cd01e21d691103eb23d3e`. Les chiffres portent sur le banc et les situations synthétiques déjà publiés. Les deux scripts lisent le dépôt et écrivent leurs résultats sur la sortie standard.

## 1. Quel travail l'équipe aurait-elle fait sans la recommandation ?

Dans le cas nominal, le transport du patient P-0412 est admissible mais encore non demandé à la relève. La branche sans geste impose une demande déjà enregistrée pour faire partir ce patient. Aucun événement ultérieur n'y déclenche cette demande. Le reste de l'unité, y compris le nettoyage, continue de fonctionner. Le plan qui demande le transport immédiatement réduit l'attente cumulée de 1 166,72 patient-minutes en moyenne. La prolongation de la fenêtre de H+12 à H+24 ajoute à elle seule 720 patient-minutes à cet écart. [Conditions de départ](https://github.com/HospitalOsLaunch/carepredict-mvp/blob/85a8ee7/src/hospitalos/hybrid/models.py#L208-L246) · [Génération des départs](https://github.com/HospitalOsLaunch/carepredict-mvp/blob/85a8ee7/src/hospitalos/hybrid/simulation.py#L123-L172)

Un test de sensibilité donne à l'équipe un délai conventionnel de 60 minutes. La suite du parcours respecte deux hypothèses. Dans l'hypothèse successive, l'équipe déclenche la préparation après le délai. Dans l'hypothèse parallèle, la préparation progresse dès la relève et le transport peut démarrer dès que préparation et coordination sont toutes deux achevées. Le patient, le geste proposé, les 32 tirages, les ressources et les durées des autres tâches sont identiques dans les branches appariées.

| Hypothèse pour le témoin | Attente cumulée témoin | Avec transport immédiat | Gain du transport immédiat | Premier choix parmi les gestes isolés et l'inaction |
|---|---:|---:|---:|---|
| Aucune demande ultérieure pour ce patient | 1 645,31 | 478,59 | 1 166,72 | Transport |
| Coordination avec 60 min de retard, préparation successive | 511,88 | 478,59 | 33,28 | Transport |
| Coordination avec 60 min de retard, préparation parallèle | 480,00 | 478,59 | 1,41 | Nettoyage du lit L11 |

Unités en patient-minutes. Dans le dernier cas, les attentes sous les deux gestes de tête valent 477,19 et 478,59. Le rang s'inverse pour environ 1,4 patient-minute. C'est une quasi-égalité sur cet exemple. La fréquence de chaque pratique et son délai demandent une mesure de terrain. La grille complète à 0, 30, 60 et 120 minutes figure dans `transport.json`.

**Méthode et limites.** Le moteur ne permet de saisir une nouvelle demande qu'à l'origine. Le diagnostic représente sa mise en œuvre différée en décalant, dans la mémoire du processus, le premier instant d'éligibilité du transport de ce seul patient. La demande technique reste enregistrée à l'origine. Les ressources ne sont mobilisées qu'au démarrage dans cette situation. Pour un temps de préparation initial T et un délai d'équipe L, le parcours devient éligible à T + L ou à max(T, L). L'absence de toute hypothèse manuelle d'arrivées et de modèle de préparation appris est vérifiée sur cette situation. Chaque geste concurrent conserve le transport habituel du même patient. Le choix applique la garde sur les ressources et l'objectif publié combinant attente moyenne et pire décile. La recherche porte sur les cinq gestes isolés disponibles et l'inaction. Tous les coûts et objectifs livrés sont reproduits dans le scénario de référence, et le score officiel contrôle chaque trajectoire. Le test évalue une sensibilité de politique sur cette situation. La question du pilote est le bénéfice supplémentaire par rapport à l'organisation de l'équipe. [Objectif du moteur](https://github.com/HospitalOsLaunch/carepredict-mvp/blob/85a8ee7/src/hospitalos/hybrid/planning.py#L244-L310) · [Choix de la politique de référence en prédiction, van Geloven et al.](https://doi.org/10.1007/s10654-020-00636-1)

## 2. Quels flux expliquent les erreurs d'occupation ?

Sur les mêmes 1 120 origines et quatre tirages par origine, le diagnostic compte les admissions en lit et les départs. Il vérifie l'identité entre le stock final, le stock initial, les admissions et les départs. Les lits occupés de la trajectoire cible ne sont utilisés qu'au moment du score. Le biais est la prévision moins la cible. L'erreur absolue et le biais signé suivent des calculs distincts.

| Mode et échéance | Admissions prévues / cible | Sorties prévues / cible | Biais d'occupation | Erreur absolue du mode | Erreur de la persistance |
|---|---:|---:|---:|---:|---:|
| Court, H+24 | 0,47 / 2,42 | 1,68 / 2,41 | −1,22 | 1,71 | 1,23 |
| Long, H+24 | 2,00 / 2,42 | 1,68 / 2,41 | +0,31 | 1,45 | 1,23 |
| Long, J+3 | 4,58 / 7,25 | 1,68 / 7,26 | +2,91 | 2,92 | 1,53 |
| Long, J+7 | 5,10 / 16,88 | 1,68 / 16,92 | +3,47 | 3,47 | 1,56 |

**Entrées.** À 24 h, sur ce banc, le moteur court prend les demandes programmées et reçoit une liste vide d'hypothèses manuelles d'urgence. Il n'injecte pas la distribution d'urgences pourtant fournie au mode long. Ajouter uniquement les arrivées tirées de cette distribution ramène l'erreur moyenne à 1,33 lit. La baisse descriptive est de 0,38 lit, intervalle apparié à 95 % [0,24 ; 0,52], obtenu selon le découpage en univers et blocs de sept jours du banc. La médecine polyvalente passe de 2,12 à 0,85 lit d'erreur et le court séjour gériatrique de 1,60 à 1,02. La médecine interne passe de 1,61 à 1,65 et la pneumologie de 1,50 à 1,80. L'effet favorable du panel masque donc deux dégradations. Le signal journalier fourni et la vérité synthétique partagent un terme calendaire. [Alimentation des deux modes](https://github.com/HospitalOsLaunch/carepredict-mvp/blob/85a8ee7/src/hospitalos/hybrid/multiday.py#L97-L165)

**Sorties.** Un événement d'admission remplit le lit. La planification des départs n'est exécutée qu'une fois, pour les patients déjà présents et éligibles au départ. Les patients présents dont l'accord n'est pas connu à la relève peuvent aussi rester immobilisés en projection. Dans ce banc, le modèle fait sortir en moyenne 1,68 patient à J+1, autant à J+3 et J+7. À sept jours, les 15,24 sorties manquantes se répartissent entre 10,97 patients admis après la relève et 4,27 patients déjà présents sans accord enregistré à l'origine. À 24 h, la cible compte 0,95 sortie de patients déjà autorisés à la relève, contre 1,68 projetée. La sortie précoce de ce groupe masque donc une partie des départs manquants dans les deux autres groupes. Une distribution de durée résiduelle conditionnelle pour les séjours en cours et une distribution de sortie pour les nouvelles admissions répondent à deux problèmes distincts. La permission de recommander un transport doit continuer à dépendre de l'autorisation effectivement observée. [Admission dans le simulateur](https://github.com/HospitalOsLaunch/carepredict-mvp/blob/85a8ee7/src/hospitalos/hybrid/simulation.py#L225-L256) · [Séjours du générateur](https://github.com/HospitalOsLaunch/carepredict-mvp/blob/85a8ee7/scripts/unit_planning/benchmark.py#L76-L156)

## 3. Ce qu'il faut mesurer pour décider

| Priorité | Essai qui tranche | Mesure à examiner |
|---|---|---|
| 1 · Témoin correspondant à la pratique du service | En mode observation, dater éligibilité, demande, début d'exécution, départ, nettoyage et remise à disposition. Inclure les épisodes où personne ne demande le transport et ceux encore ouverts en fin de suivi. Rejouer les délais observés selon unité et garde. | Délai habituel, fréquence du geste, variation du gain et fréquence de changement du premier choix. L'observation décrit la pratique de référence. |
| 2 · Continuité des flux | Donner aux modes court et long les mêmes informations à la relève. Évaluer séparément urgences seules, sorties seules et les deux ensemble, sur de nouveaux univers et par unité. | Erreurs d'admissions, de sorties et de stock. Identifier un bon total obtenu par compensation de deux erreurs de flux. Maintenir les identités comptables et l'autorisation d'agir. |
| 3 · Qualification du choix | Générer pour chaque état plusieurs suites d'événements avec les mêmes aléas exogènes. Inclure la politique habituelle, les gestes concurrents et les combinaisons admissibles. Produire les conséquences dans un générateur d'évaluation indépendant du planificateur. Geler les règles de décision et les seuils avant le nouveau lot. | Erreur sur le gain, signe, regret en patient-minutes face au meilleur geste admissible, risque de surcharge et couverture de la fourchette annoncée. Définir avant calcul l'écart jugé utile par l'équipe pour les quasi-égalités. |

Le banc d'occupation n'exécute que `no_op`. À chacune des 1 120 relèves, l'état initial transmis au moteur indique zéro patient en file et zéro patient avec un transport requis. La file peut se constituer après la relève. Le générateur renvoie les débuts et fins de séjours en lit et les nombres journaliers d'urgences. Un autre point à tester ensuite est l'horaire intrajournalier. Les urgences de la vérité sont tirées entre 7 h et 21 h 59, tandis que la projection longue répartit ses arrivées sur toute la journée civile. Des totaux quotidiens similaires peuvent masquer des pointes d'attente différentes. Un test conserve les totaux et change les heures de la relève, des sorties et des arrivées, puis mesure l'attente et le classement. [Construction et score du banc](https://github.com/HospitalOsLaunch/carepredict-mvp/blob/85a8ee7/scripts/unit_planning/benchmark.py#L204-L266)

Les scénarios de la présente revue sont postérieurs aux résultats publiés et réutilisent le panel déjà lu. Le croisement des hypothèses, les quatre tirages par origine et les 32 scénarios de démonstration permettent un diagnostic mécanique. La généralisation à des organisations indépendantes reste une question d'évaluation. Le protocole antérieur de décision v2 porte sur une autre comparaison de transport et son critère principal publié est non concluant. [Protocole décision v2](https://github.com/HospitalOsLaunch/carepredict-mvp/blob/85a8ee7/docs/operational/decision-v2-protocol.md)

## Reproduction

Depuis la racine d'une copie du dépôt au commit indiqué, utiliser le Python de l'environnement verrouillé et remplacer `/chemin/audit` par le dossier extrait.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python /chemin/audit/flux.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python /chemin/audit/temoin_transport.py
```

`flux.json` contient les moyennes, le détail par unité et l'intervalle de rééchantillonnage. `transport.json` contient les coûts des six options, les classements, les gardes et les écarts à H+12 et H+24. Les deux scripts vérifient la révision. L'analyse des flux reproduit les erreurs d'occupation à J+1, J+3 et J+7 du banc publié et le résultat du mode court de la relecture précédente.
