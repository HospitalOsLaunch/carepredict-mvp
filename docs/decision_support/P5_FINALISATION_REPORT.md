# P5 — Finalisation de la reprise P5.0–P5.2 et de P5-PROTO-3 (14 novembre 2026)

**Entrées.**
- Paquet `HospitalOS_P5_Reprise_P5.0-2_20261114.zip` (`d677e255…42f0`) et E1 (`dbe20aec…f14f`).
- Revue `HospitalOS_Revue_P5_Reprise_20261114.zip` (`d18637d4…78b3`), 4/4 empreintes conformes.
- Prompt de finalisation identique à la pièce jointe.

**Base d'action.** La transmission du prompt de finalisation est prise comme instruction de
reprise, dans le seul périmètre déjà autorisé (D11-i : mise en œuvre et pilote, lots P5.0 et
P5.1). Aucune des décisions D13, D14, D15, D16, (ii) ou (iii) n'a été prise ni appliquée.

**Non fait.**
- Pas d'installation, pas de scikit-learn, pas de modèle, pas d'ajustement.
- Pas de génération sur une partition engagée, pas de nouveau pilote, pas de lecture réservée.
- Pas de push, merge ou rebase.
- Aucun rejeu indépendant n'est déclaré : tous les tests ci-dessous sont des exécutions de
  l'auteur.

## 1. Registre P5 (prolongé, jamais remis à zéro)

- État reçu : 17 enregistrements, 13,769 s, terminal `7582b1a9…870b`, identique à l'état local
  et préfixe exact.
- État final : **23 enregistrements, 18,645 s / 1200 s**, terminal `db1f5e39…9dc96`.

| Lot | Plafond | Avant | Après |
|---|---:|---:|---:|
| P5.0 | 30 s | 2,682 | 2,897 (engagement E2) |
| P5.1 | 130 s | 8,563 | 13,224 (lint, 2 passages de tests) |
| P5.2 | 40 s | 2,524 | 2,524 (reliquat 37,476 s) |

Le refus volontaire n° 23 (lot P5.3) est consigné à 0 s. P0–P4 est inchangé, sans transfert de
reliquat.

## 2. Corrections (code P5 seulement ; moteur v6, cockpit et mvp/computer-use hors périmètre)

| Constat | Correction |
|---|---|
| R-P5-01 : version Python non comparée | Couple approuvé (Python 3.11.18, gel `bf540981…`), contrôlé avant lancement par le compteur, en plus du chemin exact, et **dans le processus** du pilote avant toute opération scientifique (`check_runtime`). Une note `environment_approved` sans version Python est ignorée. |
| R-P5-03 : refus de lot non consigné | Registre validé d'abord. Un registre absent ou corrompu bloque sans genèse. Le refus est ensuite consigné à 0 s avec le lot et la raison. |
| R-P5-02 : `invariant failure` parmi les abstentions | Le pilote s'arrête avec reçu sur `habitual_practice_invariant_failure`. Les véritables abstentions restent HABITUAL-1. |

**E2** (`COMMITMENT_E2.json`, `72d65757…9552`, registre n° 21) : graines inchangées ; moteur v6
identique à `856a57c`. E0, E1, les graines, le pilote historique, les documents v3 et les 24
tests initiaux sont inchangés (`git diff` vide contre `4d13be6`).

## 3. Contrôles exécutés sous compteur

- **n° 19** (avant E2) : 51 réussis, 1 échec attendu. Le test « engagement effectif vérifié
  sur le disque » refuse le code modifié depuis E1 : c'est le contrôle d'intégrité qui fonctionne.
- **n° 22** (sous E2) : **52/52** (`pytest_p5_1_E2.xml`, `88ac0fe7…9552`). Les 42 tests
  précédents sont conservés et adaptés. Nouveaux tests :
  - **compteur** :
    - même gel avec Python 3.11.9 refusé, couple conforme accepté ;
    - note post-installation sans Python ignorée, puis acceptée avec les deux champs ;
    - lot non autorisé consigné à 0 s ;
    - registre absent ou corrompu bloquant ;
  - **contrôle dans le processus** : mauvaise version refusée, mauvais gel refusé, couple
    conforme accepté ;
  - **pilote** : échec d'invariant de la pratique habituelle ⇒ arrêt ;
  - **cohérence documentaire** (5 tests) :
    - abstentions sans échec d'invariant, cohérentes avec la liste d'arrêt et le code ;
    - P5.2 = banc A5 de 6 ajustements, mesures historiques non recomptées ;
    - L2 = 28 ajustements, hors les 6 du banc ;
    - seuils, tailles et plafonds identiques à v3 ;
    - couple d'environnement identique dans le JSON, le compteur et le document ;
    - statut et absence de transfert d'approbation.
- **n° 23** : `P5.3` refusé et consigné (code 4, 0 s).

## 4. Documents (versions précédentes intactes)

| Document | SHA-256 | Statut |
|---|---|---|
| `P5_PROTOCOL_v3.md` | `dbf517ca…6ab6` | proposé, inchangé |
| `P5_PROTOCOL_PARAMS_v3.json` | `653a426a…18ac` | proposé, inchangé |
| `P5_PROTOCOL_v3_1.md` | `e0cbe6de…ec62` | **proposé** : révisions R1–R5 |
| `P5_PROTOCOL_PARAMS_v3_1.json` | `c01eae5e…58f4` | **proposé**, concordant |

Révisions de P5-PROTO-3.1 :
- R1 : couple (Python, gel) ;
- R2 : refus journalisés ;
- R3 : abstentions et arrêts ;
- R4 : P5.2 = banc A5 de 6 ajustements, L2 = 28 hors banc, mesures historiques comptées une fois ;
- R5 : note éditoriale (le paquet précédent avait **2** patchs sur la base
  `97c23a0e73ad6b3a332deb1ea14508f5f720b5b8`, et non 3 commits).

Aucune approbation antérieure n'est transférée.

## 5. Accords demandés (une seule demande)

| # | Objet |
|---|---|
| **D13** | Approuver P5-PROTO-3 (`dbf517ca…6ab6`, `653a426a…18ac`) et sa révision P5-PROTO-3.1 (`e0cbe6de…ec62`, `c01eae5e…58f4`) |
| **D14 (= D4)** | Installation isolée de scikit-learn et de ses dépendances dans l'environnement 3.11.18, versions exactes consignées, lot P5.I (60 s, 30 s par commande), nouveau couple (Python, gel) enregistré par une note `environment_approved`. Cela n'approuve pas P5b. |
| **D15** | Banc A5 : 6 ajustements de chronométrage (M_agg et M_ent × graines 0, 1, 2 ; `max_depth` 5, `learning_rate` 0,1, `max_iter` 400) sur 1440 lignes de développement tuilées, `OMP_NUM_THREADS=1`, modèles jetés, dans le reliquat P5.2 (37,476 s) et 30 s par commande. Le banc ne prouve ni efficacité ni généralisation ; son extrapolation ne garantit pas le coût. |

D16 n'est pas applicable avant le résultat A5. Aucune évaluation réservée P5a ou P5b sans (ii)
ou (iii) et sans F_a ou F_b.

Statuts inchangés : `PARTIAL_WITH_CHECKPOINT`, `PROTOTYPE_UNVALIDATED`,
`clinical_validation=false`, `G2=NO-GO`. P6 reste fermé. Pas de v7 du moteur.
