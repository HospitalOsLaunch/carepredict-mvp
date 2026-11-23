# Vérification numérique ciblée — B-FRAG 2 après correction du calendrier

**Date** 17 novembre 2026, décision n° 8, § 4.

**Périmètre :** DEV uniquement ; aucune donnée CONF n'est lue ou recalculée.

**Panel et tolérances.** Ils ont été déclarés **avant** la mesure (`evidence/howm2_bfrag2w/STAB_PREDECLARED.json`,
registre `stab_predeclared`). Résultats : `VERIF_NUM_DEV.json`, registre **#125** (179 s de mur).

## 1. Paramètres réellement enregistrés (relus fichier par fichier)

| Jeu | Mode | Mr (risque) | Md (choix d'action) | E (évaluation) | Fichiers | Ce qui est réellement utilisé |
|---|---|---|---|---|---|---|
| CONF-S `S/BF2_CONF` | full | 32 | 32 | 8 | 72 | risque, planificateurs R1/F/O, évaluation |
| VAL-S `S/BF2_VAL` | val | 32 | 32 | 8 | 54 | risque, planificateur R1, évaluation (pas de F ni d'O) |
| Vues TRAIN, VAL, CONF (`F/…`) | features | 32 | **8** (défaut) | 8 | 600 / 300 / 528 | **aucun** de ces paramètres (vues seulement) |
| DEV `DEVM` | full | 32 | 32 | 8 | 3 | coûts |
| DEV `SMOKE` | full | 32 | **8** | 8 | 1 | coût seulement |
| DEV `DEVF`, `DEVF2` | features | 32 | 8 | 8 | 18 + 18 | aucun |

Tous les résultats comparatifs B-FRAG 2 (VAL-S, CONF-S) utilisent donc Mr = 32, Md = 32 et E = 8. La valeur
Md = 8 inscrite dans les fichiers de vues est une valeur par défaut sans usage.

## 2. Stabilité du choix d'action (2 répétitions indépendantes, tirages imbriqués)

Panel : 4 décisions DEV, structures 0 (SF1), 1 (SF2), 2 (SF3, baisse planifiée) et 4 (SC5, baisse planifiée).

| Méthode | Md | Accord des choix | Regret relatif moyen | Regret relatif max | Tolérance ≤ 0,005 |
|---|---|---|---|---|---|
| F | 8 | 3/4 | 0,0031 | 0,0122 | non |
| F | 16 | 3/4 | 0 | 0 | oui |
| F | **32** | **4/4** | 0 | 0 | **oui** |
| R1 | 8 | 1/4 | 0,0150 | 0,0245 | non |
| R1 | 16 | 1/4 | 0,0099 | 0,0248 | non |
| R1 | **32** | **3/4** | 0,0031 | **0,0122** | **non** |

**Règle préenregistrée appliquée.**

- Md = 32 est conservé : aucun Md plus grand n'est finançable.
- La tolérance n'est pas atteinte pour R1. **F et R1 ne sont pas traités comme des références exactes de
  décision.**
- O n'a pas été recontrôlé (budget), ce qui est déclaré.
- Avec 4 décisions, la stabilité de F reste établie sur très peu de cas.

## 3. Stabilité de l'évaluation vraie (E = 8 ; jeux de futurs disjoints A = r 1–8 et B = r 9–16)

| Structure | Gain F − R1 sur A | Gain F − R1 sur B | Meilleure action A / B | Gain meilleure(A) − aucune, sur A / sur B | Spearman des 10 attentes A vs B |
|---|---|---|---|---|---|
| 0 (SF1) | +2 072 | **−831** | 5 / 3 | 6 420 / 8 464 | 0,90 |
| 1 (SF2) | 0 | −8 | 0 / 8 | 0 / 0 | 0,11 |
| 2 (SF3) | +83 | +647 | 3 / 3 | 744 / 2 130 | 0,45 |
| 4 (SC5) | 0 | 0 | 1 / 1 | 793 / 647 | 0,94 |

**Lecture.**

- À E = 8, l'évaluation d'un écart entre deux actions **pour une décision isolée** est bruitée : le signe peut
  s'inverser (structure 0).
- Le niveau d'attente lui-même varie fortement entre jeux de futurs (structure 1 : 3 503 contre 13 734).
- Les verdicts B-FRAG 2 restent des moyennes sur 72 décisions, et leurs intervalles par structure incluent ce
  bruit. Mais un gain moyen faible (254 patients-minutes) doit être lu avec cette variance de décision à
  l'esprit.
- Le pilote de la décision n° 8 en tient compte en fixant E avant l'évaluation neuve (protocole du pilote).
