# P5 — D13–D15 : installation isolée et banc A5 (14 novembre 2026)

**Accord :** l'utilisateur a adopté explicitement le message « D13–D15 » (réponse « Oui, j'adopte
D13–D15 »). Le texte adopté est conservé (`evidence/decision_support/p5/ACCORD_D13_D15_TEXT_ADOPTED.txt`),
le relevé est dans `docs/decision_support/P5_DECISIONS_v3.json` et la note au registre porte le
n° 24.
- D13 : P5-PROTO-3 et sa révision 3.1, approuvés par leurs quatre empreintes.
- D14 : installation isolée.
- D15 : banc A5 seul.

**Arrêt après A5, comme prévu.** Rien de plus n'est lancé : pas de D16, pas de (ii) ni de (iii),
pas d'ajustement supplémentaire, pas d'évaluation réservée, pas de P6, pas de push. Les statuts
`PARTIAL_WITH_CHECKPOINT`, `PROTOTYPE_UNVALIDATED`, `clinical_validation=false` et `G2=NO-GO`
sont inchangés.

## 1. Point de départ vérifié

Contrôlés et identiques à l'état local :
- paquet `HospitalOS_P5_Finalisation_20261114.zip` (`929eefcc…4635`) ;
- E2 (`72d65757…9552`) ;
- les quatre empreintes v3 et v3.1 ;
- HEAD `5850278` ;
- registre (23 enregistrements, 18,645 s, terminal `db1f5e39…`).

La revue `HospitalOS_Revue_Finalisation_P5_20261114.zip` (`2d93a029…b482`) est conforme ; son
rapport et sa proposition sont identiques aux pièces jointes.

## 2. D14 — installation isolée (lot P5.I : 8,557 s sur 60)

| Étape | Registre | Durée |
|---|---|---:|
| Téléchargement des roues binaires, borne `scikit-learn>=1.5,<1.9`, vers un dossier local | n° 25 | 3,73 s |
| Installation hors ligne (`--no-index`) dans l'environnement virtuel 3.11.18 | n° 26 | 4,83 s |

- **Versions ajoutées** : scikit-learn **1.8.0**, scipy 1.17.1, joblib 1.6.0, threadpoolctl
  3.8.0, cloudpickle 3.1.2 (cette dernière tirée par la résolution de pip).
- **Inchangés** : numpy 2.4.6 ; aucun paquet retiré.
- **Python** reste 3.11.18 ; l'environnement système n'a pas été modifié.
- Empreintes des roues : `D14_WHEELS_SHA256.txt`.
- **Nouveau couple approuvé** : (3.11.18, `bd5bc537…ca22`), gel dans
  `py311_venv_freeze_postD14.txt`, note `environment_approved` n° 27.

Le contrôle dans le processus a vérifié ce couple avant chaque série d'ajustements.

## 3. Code A5 testé puis engagé avant tout ajustement

- **Code** : `src/hospitalos/p5/a5.py` et `scripts/p5_a5_benchmark.py`.
- **Vérifications avant tout ajustement** :
  - engagement effectif ;
  - couple d'environnement dans le processus ;
  - `OMP_NUM_THREADS=1` ;
  - famille non encore mesurée ;
  - règle budgétaire avant chaque graine ;
  - écriture des mesures après chaque ajustement.
- **Tests** (estimateurs factices, aucun ajustement réel) :
  - n° 29 : 59 réussis et 1 refus d'intégrité attendu, le code ayant changé depuis E2 ;
  - **engagement E3** (n° 30–31, graines inchangées, moteur v6 identique à `856a57c`) ;
  - n° 32 : **60/60 sous E3** (`pytest_p5_1_E3.xml`).

## 4. D15 — banc A5 (lot P5.2 : 24,009 s sur 40)

**Matrice.** Les 20 parents du pilote historique E0 (P5a_dev, structures 0–1) donnent
148 lignes distinctes, tuilées à **1440 lignes**. Leurs instantanés publics ont été régénérés à
l'identique ; nombre de plans contrôlé contre chaque relevé. Les étiquettes sont les U moyens R1
**déjà enregistrés** par ce pilote : aucune simulation, et le pilote n'a été ni relancé ni
recompté. Préparation : 0,08 s par commande.

| Famille | Variables | Empreinte de la matrice tuilée | Commande |
|---|---:|---|---:|
| M_agg | 290 | `d0ef2e55…` | n° 33 : 6,45 s |
| M_ent | 718 | `6b3bd3be…` | n° 34 : 15,04 s |

**Configuration.** `max_depth` 5, `learning_rate` 0,1, `max_iter` 400, paramètres fixes du
protocole (`early_stopping=False`…). Threadpools OpenMP et OpenBLAS à 1 fil. Mêmes données et
même matrice de comparaison pour les trois graines. Modèles jetés.

| Famille | Graine | Ajustement (s) | Itérations | Écart max. à la graine 0 |
|---|---:|---:|---:|---:|
| M_agg | 0 | 2,024 | 400 | 0 |
| M_agg | 1 | 1,626 | 400 | 0 |
| M_agg | 2 | 1,655 | 400 | 0 |
| M_ent | 0 | 4,203 | 400 | 0 |
| M_ent | 1 | 4,807 | 400 | 0 |
| M_ent | 2 | 4,847 | 400 | 0 |

Coût par arbre (1440 lignes) : 4,42 ms pour M_agg, 11,55 ms pour M_ent, soit environ **11 ns
par ligne × variable × arbre**. Aucun arrêt budgétaire, aucun reçu d'échec.

**Condition L2 : satisfaite sur ce banc**, écart 0 ≤ 1e-12 pour les deux familles. Portée : cette
configuration, ces données tuilées, cette machine. Ce n'est ni une preuve pour toutes les
configurations, ni une autorisation d'entraîner P5b.

## 5. Devis actualisé : mesures, extrapolations et limites séparées

**Mesuré :**
- simulation sous vérité : 0,77 ms ;
- recommandation : 0,044 s ;
- extraction : 0,09 ms par ligne et par famille ;
- installation : 8,56 s ;
- ajustements A5 : tableau ci-dessus.

**Extrapolé** : coût linéaire en lignes ; les 12 configurations sont comptées au coût par arbre
de la profondeur 5, ce qui surestime ; matrice tuilée et non un corpus divers ; marge ×1,5
indiquée.

| Ajustements P5b | Univers moyen (5328 lignes) | Univers maximal (11 520 lignes) |
|---|---:|---:|
| 1 ajustement M_ent à 400 itérations | 17,1 s | **37,0 s (> 30 s par commande)** |
| Avec L2 (28) | 213 s ; 319 s avec marge | 460 s ; 690 s avec marge |
| Sans L2 (72) | 496 s ; 745 s avec marge | 1073 s ; 1610 s avec marge |

**Lecture, sans rien appliquer :**
- Au plafond P5.4 de 470 s (incluant 39 à 70 s hors ajustements), seule la voie L2 tient, et
  seulement si les univers restent proches de la moyenne mesurée.
- À l'univers maximal, un ajustement M_ent isolé dépasserait déjà 30 s par commande.
- La règle d'arrêt couvre ce cas, mais **une décision serait nécessaire avant (iii)**.
- L'application de L1, L2 ou L3 relève de la planification de P5.4 et n'est pas faite ici.

## 6. Registre

| Lot | Utilisé | Plafond |
|---|---:|---:|
| P5.0 | 3,112 s | 30 s |
| P5.1 | 18,239 s | 130 s |
| P5.2 | 24,009 s | 40 s (reliquat 15,991 s) |
| P5.I | 8,557 s | 60 s |
| **Total** | **53,917 s** | 1200 s |

Terminal après la note du rapport A5 : voir l'ancre du registre. P0–P4 inchangé, aucun transfert.
P5.2 passe de `PILOT_PARTIAL_FITS_NOT_TIMED` à **`PILOT_COMPLETE_A5_MEASURED`**.

## 7. Suite (aucune décision prise)

D16 n'est pas nécessaire, le banc à 1440 lignes ayant abouti. (ii) est l'évaluation réservée P5a,
après F_a. (iii) correspond aux étiquettes, ajustements et évaluation P5b, après F_b, avec une
décision préalable sur la limite de 30 s par commande à l'univers maximal. Chacune exige un accord
distinct.
