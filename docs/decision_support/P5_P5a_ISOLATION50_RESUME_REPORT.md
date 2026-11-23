# P5A-D02 — Reprise limitée du contrôle d'isolation, rangs 48 à 50 (14 novembre 2026)

**Qualification.** Contrôle **postérieur au gel** et à la lecture P5a, avec la **méthode v2**. Il
complète la preuve d'isolation sans réécrire l'historique. P5a reste `exploratory`. F_a,
`RESULTS_P5a.json` et les relevés réservés sont inchangés.

**Autorisation.** Proposition adoptée explicitement (« Oui, j'adopte la reprise »). Texte conservé
(`evidence/decision_support/p5/ACCORD_REPRISE_ISOLATION50_TEXT_ADOPTED.txt`), relevé
`docs/decision_support/P5_DECISIONS_v6_reprise_isolation50.json`, registre n° 75.

**Résultat.**
- Les 50 épisodes de la sélection sont désormais couverts : 47 en méthode v1 (historique) et 3 en
  méthode v2.
- **Aucun véritable échec, aucune fuite.**
- **T04-a est non informatif sur un épisode**, le rang 48.
- Ce n'est donc **pas** un « 50/50 tout réussi ». Le critère de clôture de P5A-D02 n'est pas
  modifié : accepter un T04-a non informatif exige une décision explicite.

## 1. Déroulé (registre P5)

| N° | Étape | Résultat |
|---|---|---|
| 75 | accord consigné | — |
| 76–77 | lint ; tests avant E7 | 78 réussis + 1 refus d'intégrité attendu |
| 78–79 | **E7** (module `isolation50_v2.py`, script de reprise, correctif du refus dans l'ancien script) | graines inchangées ; moteur v6 identique à `856a57c` ; fichiers F_a et module v1 intacts |
| 80 | tests sous E7 | **79/79** (`pytest_p5_1_E7.xml`) |
| 81 | garde : contrôle demandé sans procédure | **refus propre**, code 4, reçu `procedure_missing`, aucune reconstruction |
| 82 | procédure v2 scellée (nouvelle identité `isolation50_resume/`) | `RESUME_PROCEDURE.json` `e5b94ad7…d6a3` |
| 83 | garde : procédure scellée mais non enregistrée | **refus propre**, code 4, reçu `procedure_not_recorded` |
| 84 | **procédure enregistrée au registre avant tout contrôle** | — |
| 85 | contrôle v2 des indices 47 à 49 | 3 reçus, code 0, 2,68 s |
| 86 | synthèse 47 + 3 | `RESUME_SUMMARY.json` |

L'ancien répertoire n'a pas été modifié : procédure, sélection `d4522515…`, 47 reçus et
`ISOLATION_FAILURE.json`.

## 2. Méthode v2 et différence avec v1

| | v1 (47 reçus historiques) | v2 (3 reçus de reprise) |
|---|---|---|
| Paire de vérités | A = (R1, 1) ; B = la première vérité de la liste dont **HABITUAL-1** change, sinon arrêt | A = (R1, 1) ; **les 5 vérités B** dans l'ordre fixé, sans nouveau tirage |
| T03-b (isolation du backend produit) | chaque plan contre **un** B | chaque plan contre **chacun des 5 B** |
| T04-a (détection d'un backend lisant la vérité) | sur HABITUAL-1 | recherche d'un plan témoin dans tout l'univers public, avec la **projection exacte** de `check_isolation` ; sinon **NON_INFORMATIF** |
| T03-a, T04-b/c/d | identiques | identiques |

## 3. Reçus des trois épisodes repris (`RESUME_RECEIPTS.jsonl`)

| Rang | Épisode | Plans | T03-a | T03-b (paires plan × B) | T04-a | T04-b/c/d |
|---:|---|---:|---|---:|---|---|
| 48 | `7f0869e7430c81ce` / 5 | 6 | choix = relevé | 30 / 30 | **NON_INFORMATIF** (30 paires examinées, aucune signature différente) | réussis |
| 49 | `a1e973184bf456ee` / 1 | 6 | choix = relevé | 30 / 30 | **DÉTECTÉ** (HABITUAL-1, B = (R2, 3)) | réussis |
| 50 | `e9b01fb227dd3d3a` / 8 | 14 | choix = relevé | 70 / 70 | **DÉTECTÉ** (HABITUAL-1, B = (R2, 3)) | réussis |

Aucune des vérités B n'est identique à A : les vérités diffèrent toujours. Au rang 48, ces
différences ne modifient la trajectoire d'**aucun** plan de l'univers. Le diagnostic historique
le montrait déjà pour HABITUAL-1, et la v2 l'étend aux 6 plans. Le témoin de détection ne peut donc
pas être construit sur cet épisode avec ces vérités et cette projection. Ce n'est **pas** une fuite.

## 4. Bilan 47 + 3, sans mélange de méthodes

| Indicateur | v1 (historique) | v2 (reprise) | Total |
|---|---:|---:|---:|
| Épisodes couverts | 47 | 3 | **50 / 50** |
| T03 réellement réussi (T03-a et T03-b) | 47 | 3 | 50 |
| T04-a informatif et détecté | 47 | 2 | 49 |
| **T04-a non informatif** | 0 | **1** | **1** |
| T04-b/c/d réussis | 47 | 3 | 50 |
| Véritables échecs (fuite, écart, faux négatif) | 0 | 0 | 0 |

L'arrêt historique du rang 48 sous v1 reste consigné et n'est pas effacé : c'était un échec de
précondition, pas une fuite.

## 5. Limites

- Les assertions valent pour ces 50 épisodes, ces vérités, cette projection et cet environnement
  (Python 3.11.18, gel post-D14). Elles ne prouvent rien au-delà.
- Les 47 reçus v1 n'ont **pas** été rejoués en v2 : leur T03-b porte sur un seul B. Les mélanger
  avec les 3 reçus v2 dans une même statistique serait trompeur ; le bilan les sépare.
- Le contrôle porte sur le comportement observable du planificateur et des backends. Ce n'est pas
  une preuve formelle d'absence de fuite.

## 6. Budget

| Lot | Utilisé | Plafond |
|---|---:|---:|
| P5.0 | 4,336 s | 30 s |
| P5.1 | 38,786 s | 130 s |
| P5.3 | 51,292 s avant la vérification de livraison | 330 s |
| **Total** | **134,548 s** avant la vérification de livraison | 1200 s |

Aucun transfert, aucun plafond modifié. P0–P4 inchangé.

## 7. Décision possible (non prise)

Clore P5A-D02 en acceptant explicitement que le rang 48 soit non informatif pour T04-a, T03 y
étant réussi, ou bien le laisser ouvert. Aucune autre suite n'est engagée. P5b et (iii), D16, P6,
AJ-H, l'installation et le push restent fermés. Statuts : `PARTIAL_WITH_CHECKPOINT`,
`PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`. Arrêt après livraison.
