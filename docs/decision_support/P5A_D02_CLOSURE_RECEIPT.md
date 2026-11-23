# P5A-D02 — Reçu de clôture qualifiée (14 novembre 2026)

**Décision adoptée par l'utilisateur** (« approuver », avec la proposition jointe) : **P5A-D02 clos,
accepté avec réserve nommée**. Texte conservé :
`evidence/decision_support/p5/DECISION_CLOTURE_P5A_D02_TEXT_ADOPTED.txt`. Version lisible par
machine : `evidence/decision_support/p5/p5a/P5A_D02_CLOSURE_RECEIPT.json`.

**Réserve explicite.** **T04-a NON_INFORMATIF au rang 48** (structure `7f0869e7430c81ce`, parent 5).
Sur les 30 paires (vérité B, plan) examinées, aucune ne modifie la signature comparée par
`check_isolation`. Les vérités diffèrent pourtant, et T03 comme T04-b/c/d sont réussis sur cet
épisode. Ce n'est pas une fuite, mais la détection n'a pas pu y être démontrée.

## Bilan exact

| Indicateur | Valeur |
|---|---:|
| Épisodes contrôlés | 50 (47 méthode v1 historique + 3 méthode v2 de reprise) |
| T03 (isolation du produit) réussi | 50 |
| T04-b/c/d (refus structurels) réussis | 50 |
| T04-a informatif et détecté | 49 |
| **T04-a non informatif** | **1** (rang 48) |
| Véritables échecs | 0 |

**Ce que ce reçu n'affirme pas :**
- une réussite intégrale 50/50 de T04-a ;
- une preuve formelle d'absence de fuite ;
- un changement rétroactif du protocole ou du statut exploratoire de P5a.

La réserve et la clôture sont **postérieures au gel**. Les 47 reçus v1 ne sont pas requalifiés en v2.

## Preuves de référence (inchangées)

| Objet | SHA-256 |
|---|---|
| Archive de reprise `HospitalOS_P5a_Isolation50_Resume_20261114.zip` | `45db113c…5b3e` |
| Archive POST correspondante | `afb5649c…8370` |
| Archive historique `HospitalOS_P5a_Isolation50_20261114.zip` | `bd5556e1…1767` |
| Sélection des 50 épisodes | `d4522515…e993` |
| Procédure, reçus et échec v1 ; procédure et reçus v2 | dans le reçu JSON |
| F_a, `RESULTS_P5a.json`, relevés réservés | `055a4d26…`, `1a797417…`, `445cf7de…` |

Ne sont pas modifiés :
- F_a, `RESULTS_P5a.json` et les relevés réservés ;
- le moteur v6 ;
- l'échec historique `ISOLATION_FAILURE.json` ;
- les deux méthodes et leurs reçus ;
- les critères et statuts historiques.

## Correction budgétaire, dans ce reçu seulement

Le tableau du rapport de reprise indiquait **P5.1 = 38,786 s**. La valeur exacte du registre est
**43,770 s** : la commande n° 80 (suite P5 sous E7, 4,984 s) avait été omise. Le rapport historique
n'est pas modifié.

| Lot | Au terminal |
|---|---:|
| P5.0 | 4,336 s |
| **P5.1** | **43,770 s** |
| P5.2 | 24,009 s |
| P5.I | 8,557 s |
| P5.3 | 51,324 s |
| P5.5 | 2,584 s |
| **Total** | **134,580 s sur 1200, 87 enregistrements**, terminal `80468986…d64c`, fichier `6fe6ce76…b1f4` |

Ce reçu ajoute seulement une note documentaire au registre, à 0 s. Le registre n'est pas remis à
zéro et aucune nouvelle autorisation de calcul n'est créée.

**Aucune exécution** pour ce reçu : aucun épisode, test du produit, simulateur, ajustement ou analyse
d'efficacité.

Statuts conservés : `PARTIAL_WITH_CHECKPOINT`, `PROTOTYPE_UNVALIDATED`,
`clinical_validation=false`, `G2=NO-GO`. P5a reste `exploratory`. P5b/(iii), D16, P6, AJ-H, les
installations, les dépenses, push, merge et rebase restent fermés. Arrêt après ce reçu.
