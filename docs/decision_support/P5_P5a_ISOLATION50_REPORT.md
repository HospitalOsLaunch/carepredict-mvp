# P5A-D02 — Contrôle d'isolation T03/T04 sur 50 épisodes P5a (14 novembre 2026)

**Qualification : contrôle POSTÉRIEUR au gel F_a et à la lecture P5a.** Il complète la preuve
d'isolation sans créer une exécution historique inexistante. Il ne relève pas la lecture P5a, qui
reste `exploratory` : ce verdict est imposé par la précision.

**Autorisation.** Proposition adoptée explicitement par l'utilisateur (réponse « Oui, j'adopte le
contrôle »). Texte conservé (`evidence/decision_support/p5/ACCORD_ISOLATION50_TEXT_ADOPTED.txt`),
relevé `docs/decision_support/P5_DECISIONS_v5_isolation50.json`, registre n° 58.

**Résultat : ARRÊT sur échec de précondition, conformément à la règle 6.**
- **47 épisodes sur 50** ont passé toutes les assertions.
- Le 48ᵉ a arrêté le contrôle (`no_distinguishable_truth_pair`). Il **ne révèle aucune fuite**.
- Les épisodes 49 et 50 **n'ont pas été contrôlés**.
- Aucun correctif, aucune substitution d'épisode, aucune modification de F_a ou de
  `RESULTS_P5a.json`.

P5A-D02 n'est donc **pas clos** : la preuve d'isolation sur 50 épisodes reste incomplète.

## 1. Déroulé (registre P5)

| N° | Étape | Résultat |
|---|---|---|
| 58 | accord consigné | — |
| 59–60 | lint ; tests avant E5 | 73 réussis + 1 refus d'intégrité attendu |
| 61–62 | **E5** (module `isolation50.py`, script) | graines inchangées, moteur v6 identique à `856a57c`, fichiers F_a inchangés |
| 63 | tests sous E5 | **74/74** (`pytest_p5_1_E5.xml`) |
| 64 | garde : contrôle refusé avant enregistrement de la procédure | refusé, **mais par une exception non rattrapée** (code 1, fichier de procédure absent), pas par la sortie propre prévue (code 4). Aucun épisode contrôlé. Limite consignée, non corrigée ici. |
| 65 | procédure et sélection écrites (identifiants seuls) | 50 parents, 30 structures, sélection `d4522515…e993` |
| 66 | **procédure enregistrée au registre avant tout contrôle** | `ISOLATION_PROCEDURE.json` `94e57c80…83a3` |
| 67 | contrôle des épisodes 0 à 24 | 25 réussis |
| 68 | contrôle des épisodes 25 à 49 | 22 réussis, **arrêt au 48ᵉ** (code 6, `ISOLATION_FAILURE.json`) |
| 69 | synthèse | 47 contrôlés, échec consigné |
| 70–72 | script de diagnostic (lecture seule), lint, **E6** | — |
| 73 | diagnostic du cas | `ISOLATION_FAILURE_DIAGNOSIS.json` |

## 2. Procédure enregistrée (résumé, texte complet dans `ISOLATION_PROCEDURE.json`)

**Sélection** indépendante de tout résultat : hachage salé
`P5a-isolation50|engagement|structure|parent`, tour de rôle entre les structures (un parent par
structure, puis 20 de plus). Seuls des identifiants sont lus.

**Reconstruction** depuis les graines scellées et les sources figées. Identifiants de plans et
empreinte d'univers identiques aux relevés, sinon arrêt.

**Paire de vérités.** A = (R1, k = 1). B = la première de (R2, 3), (R2, 2), (R2, 1), (R1, 3),
(R1, 2) dont l'exécution sous vérité de HABITUAL-1 diffère de celle de A.

**Assertions :**
- **T03-a** : recommandation publique v6 identique sur deux calculs, et égale au choix enregistré
  par P5a.
- **T03-b** : `check_isolation` du backend produit passe pour **chaque plan** de l'univers.
- **T04-a** : un backend lisant la vérité est détecté sur HABITUAL-1.
- **T04-b/c/d** : ce backend est refusé comme backend produit, par `recommend`, et sur une entrée
  non publique.

## 3. Résultats des 47 épisodes contrôlés (`ISOLATION_RECEIPTS.jsonl`)

- **30 structures** couvertes.
- Pour chacun des 47 épisodes :
  - recommandation identique sur deux calculs **et égale au choix enregistré par P5a** (47/47) ;
  - T04-a/b/c/d réussis.
- **T03-b sur 377 plans** : 0 dépendance de la sortie publique à la vérité privée.
- Détecteur T04-a déclenché sur 363 de ces plans par le backend lisant la vérité. Sur les 14 autres,
  les deux vérités donnent le même résultat pour ce plan.
- Vérités B utilisées : (R2, 3) et (R2, 2).

Ces assertions concernent ces 47 épisodes, dans cet environnement (Python 3.11.18, gel post-D14).
Elles ne prouvent rien au-delà.

## 4. Cas d'arrêt : 48ᵉ épisode de la sélection

Structure `7f0869e7430c81ce`, parent 5 :
- 6 plans, 7 séjours dont 3 autorisés, 7 lits occupés, 1 admission ;
- univers reconstruit **identique** au relevé.

**Diagnostic** (`ISOLATION_FAILURE_DIAGNOSIS.json`, lecture seule) :
- **Les six vérités diffèrent bien** : durées de nettoyage, préparation de X02 et X07, délai de
  transport de X07.
- **La trajectoire de HABITUAL-1 est pourtant identique dans les six** : départs à h16, h18, h20,
  admission à h21, U = 610.
- C'est cohérent avec les relevés P5a (U habituel = 610 dans les 3 réalisations de R1 et de R2).
- Les primitives qui varient ne contraignent pas ce plan :
  - les départs habituels sont fixés par l'heure d'organisation et les départs prévus ;
  - les nettoyages qui varient concernent surtout des lits dont le séjour ne part pas dans
    l'horizon.

**Lecture.** La précondition que j'ai écrite (paire distinguable *sur HABITUAL-1*) était trop
étroite pour cet épisode. La procédure n'a donc pas pu construire la paire exigée par T04-a. Ce
n'est **pas** une fuite, et l'isolation du backend produit (T03-b) n'a simplement **pas été
évaluée** sur cet épisode. Le défaut est dans ma procédure, pas dans le moteur.

**Suite possible (non engagée, décision distincte requise).** Amender la procédure pour choisir la
paire sur *n'importe quel* plan de l'univers, ou constater qu'aucune vérité ne change aucun plan
(épisode alors non informatif pour T04-a). Puis reprendre, sur les épisodes 48 à 50, une nouvelle
exécution identifiée comme telle, sans remplacer l'épisode.

## 5. Budget

| Lot | Utilisé | Plafond |
|---|---:|---:|
| P5.0 | 4,121 s | 30 s |
| P5.1 | 33,329 s | 130 s |
| P5.3 | 47,318 s avant la vérification de livraison | 330 s |
| **Total** | **119,918 s** avant la vérification de livraison | 1200 s |

Aucun transfert ni changement de plafond. P0–P4 inchangé.

## 6. Ce qui ne change pas

P5a reste `exploratory`. F_a, `RESULTS_P5a.json` et les relevés réservés sont inchangés. Statuts :
`PARTIAL_WITH_CHECKPOINT`, `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`.
P5b, D16, P6, AJ-H, installation et push restent fermés. Arrêt après cette livraison.
