# C1 palier 1 — Correctif documentaire de clôture (décision n° 6)

**Date :** 17 novembre 2026.

**Statut.** Correctif **documentaire**. Il n'y a aucune nouvelle expérience, aucune passe de modèle,
aucune relance.

**Inchangés :**
- le verdict **`C1_INDETERMINE`** ;
- la sélection et les résultats (`RESULTS_C1_P1.json`) ;
- le gel F-C1 ;
- le paquet `HOWM2_P2_C1_P1_FINAL.zip`.

**Rapport concerné :** `RAPPORT_C1_PALIER1.md`, version finale, commit 9aa61a7.

## 1. Coût de C.2a à N = 1 000 (§ 4.1 et § 6 du rapport C1)

| Grandeur | Valeur | Source |
|---|---:|---|
| Pas de C.2a, pilote (12 pas, 3 processus de pilote simultanés, 1 fil) | 13,03 s | `PILOT.json` (n° 14 du registre C1) |
| Pas de C.2a mesuré en exécution réelle (N = 100, 150 pas, 3 puis 2 processus simultanés, 1 fil, évaluation CVAL finale comprise) | 14,7 / 15,1 / 15,2 s | `state.json`, `C1_LOGS_EXPLORATORY.json` |
| **Une graine** à N = 1 000, un fil : 1 500 pas | ≈ **19 500 s** (pilote) ; ≈ **22 500 s** (mesure réelle) | calcul |
| + 3 évaluations CVAL (72 lots × 2,0 s) | ≈ 430 s | estimation à partir du pilote |
| **Trois graines, CPU cumulé** | ≈ **58 600 s** (pilote) ; ≈ **67 500 s** (mesure réelle) | calcul |

**Vérification.** L'estimation du mandat, 13 s × 1 500 ≈ 19 500 s par graine et 58 500 s pour trois,
est confirmée sur la base du pilote. La mesure en exécution réelle donne environ 15 % de plus.

**Temps mural réalisable.**
- **Mémoire.** Un processus C.2a culmine à environ 4,4 Go. Trois processus simultanés sur 15 Go
  sans swap ont été tués par le noyau (registre C1, n° 17, 18 et 31). Quatre processus ne tiennent
  pas.
- **Avec 2 processus simultanés**, en deux vagues : ≈ 45 000 s, environ 12 h 30.
- **Avec 3 processus simultanés**, une vague, *si* aucun n'est tué : ≈ 22 500 s, environ 6 h 15 ;
  non démontré.

**Formulation retirée.** L'expression « environ 4 h 30 de temps mural sur 4 cœurs » (rapport C1,
§ 6) divisait le CPU cumulé par 4 cœurs. Ce n'est **pas** une accélération mesurée. Elle est
remplacée par les deux estimations ci-dessus.

## 2. Lecture exploratoire des journaux train/CVAL déjà enregistrés

**Statut de cette lecture.** Elle est **post hoc**, faite après connaissance du résultat C1. Elle
n'utilise que des valeurs **déjà enregistrées** dans `state.json`. Elle ne change ni la sélection ni
le verdict. Elle n'invente aucune valeur manquante.

Détail par exécution, par famille et par point d'évaluation : `evidence/howm2_c1_closure/C1_LOGS_EXPLORATORY.json`.

**Perte CVAL normalisée totale par exécution**, aux pas 500, 1 000 et 1 500 (N = 1 000), ou au
pas 150 seulement (N = 100) :

| Exécution | 500 | 1 000 | 1 500 | Retenu = dernier |
|---|---:|---:|---:|---|
| C.1, N = 1 000, s0 | 7,9646 | 8,0041 | 7,9452 | oui |
| C.1, N = 1 000, s1 | 7,9792 | 7,9966 | 7,9642 | oui |
| C.1, N = 1 000, s2 | 7,9878 | 7,9679 | 7,9484 | oui |
| C.2b, N = 1 000, s0 | 7,9464 | 7,9056 | 7,8816 | oui |
| C.2b, N = 1 000, s1 | 7,9339 | 7,9309 | 7,8840 | oui |
| C.2b, N = 1 000, s2 | 7,9644 | 7,8938 | 7,8832 | oui |

| Exécution | Perte CVAL au pas 150 |
|---|---:|
| C.1, N = 100 (s0, s1, s2) | 8,0023 ; 8,0141 ; 8,0075 |
| C.2b, N = 100 (s0, s1, s2) | 8,0009 ; 8,0114 ; 8,0070 |
| C.2a, N = 100 (s0, s1, s2) | 8,0031 ; 8,0141 ; 8,0071 |

**Observations.**
- **Point retenu.** Partout, le checkpoint retenu est le **dernier**. Toutes les exécutions à
  N = 1 000 baissent encore sur le dernier intervalle, de −0,011 à −0,059 : rien n'indique une
  convergence à la fin du passage.
- **C.1 n'est pas monotone.** Pour deux graines sur trois, la perte CVAL remonte au pas 1 000.
- **Pertes par famille.** Elles existent dans les journaux, et chaque perte d'entraînement est
  mesurée sur des données neuves, puisqu'il n'y a qu'un passage.
  - C.2b, s0 : ready CVAL 3,729 → 3,679 ; transport 2,798 → 2,759 ; nettoyage 2,464 → 2,422 ;
    confirmation stable autour de 3,16 à 3,17.
  - Les pertes par famille du flux sont plus basses que celles de CVAL : ready 3,55, transport
    2,43. **Hypothèse non testée** : cela tiendrait à la composition par origine des lots, et non à
    un sur-apprentissage.
- **À N = 100**, il n'y a qu'une évaluation, à la fin : aucune courbe n'est disponible.
- **La comparaison 100/1 000 mélange deux facteurs** : la diversité des données (100 contre 1 000
  établissements) et le nombre de mises à jour (150 contre 1 500). Elle n'isole ni l'un ni l'autre.

## 3. Paquet de clôture complémentaire

`HOWM2_C1_CLOSURE_ENVELOPE.zip` (scratchpad `howm2_packages/`) contient :
- le paquet scientifique original **intact**, avec son empreinte vérifiée ;
- le rapport final et ce correctif ;
- le registre C1 et son ancre ;
- le reçu existant ;
- les journaux exploratoires ;
- un manifeste.

Le paquet scientifique ne contient pas son propre reçu. L'enveloppe les réunit. **L'entraînement
n'est pas reproduit.**
