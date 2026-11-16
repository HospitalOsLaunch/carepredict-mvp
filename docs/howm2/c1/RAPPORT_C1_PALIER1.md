# HOWM-2 — Rapport C1 amendé, palier 1 (décision n° 5)

## Cadre

**Statuts inchangés :** `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`. Monde
synthétique HOWM-1 seulement.

**Ce que ce rapport ne mesure pas :**
- aucun avantage décisionnel ;
- aucune validation sur des hôpitaux réels.

**Règles appliquées :**
- `docs/howm2/c1/NORME_C1_PALIER1.md`, consignée avant toute mesure (registre C1 n° 5) ;
- notes de registre `c1_lot_reallocation` (n° 15) et `c1_lot_reallocation_2` (n° 19), consignées
  **avant** les entraînements qu'elles concernent ;
- gel **F-C1** (n° 34), consigné **avant** toute génération de CEVAL.

**Respect des interdits :**
- ni la réserve HOWM-1, ni DEVTEST, ni DIAG-DEV n'ont été lus ;
- aucun fichier gelé G0 ou F1 n'a été modifié (tests `test_frozen_code_unchanged`) ;
- aucun résultat historique n'a été modifié ;
- aucun push.

## 0. Verdict et portée

| Système, au point retenu | Verdict (N7′) | ΔC à H6 [IC 95 %] | ΔC à H24 [IC 95 %] |
|---|---|---|---|
| **C.2b, N = 1 000** (système de tête, choisi sur CVAL) | **`C1_INDETERMINE`** | −0,0065 [−0,0130 ; −0,0011] | −0,0027 [−0,0089 ; +0,0033] |
| C.1, N = 1 000 | `C1_NE_BAT_PAS_REF` | −0,0273 [−0,0355 ; −0,0203] | −0,0239 [−0,0317 ; −0,0164] |
| C.2a | **pas de verdict** | N = 1 000 non exécuté : budget, signalé avant entraînement, aucun point substitué | |

ΔC = L(R) − L(modèle) : une valeur positive signifie que le modèle bat la référence.

**Verdict de la tranche : `C1_INDETERMINE`.**
- À H6, la meilleure référence explicite reste significativement meilleure que C.2b.
- À H24, l'intervalle contient 0.
- Aucun système appris ne **bat** la meilleure de {L2, L2c} sur CEVAL.

**Lecture principale : ρ** (agrégat des familles validées en A).
- C.2b, N = 1 000 : ρ = −0,02 [−0,09 ; +0,02] à H6, et +0,02 [−0,02 ; +0,06] à H24.
- Les dénominateurs sont stables : L_R − L4 = 0,107 et 0,157.
- `AMBITION_NON_ATTEINTE`.

**Portée.**
- Le résultat porte sur la **prévision** sur HOWM-1, dans ce protocole et à ces tailles (100 et
  1 000 établissements).
- Il ne dit rien d'un palier 10 000, ni d'une autre architecture, ni d'une valeur de décision, ni
  d'hôpitaux réels.

## 1. Ce qui a été exécuté

| Élément | Réalité |
|---|---|
| Données | HOWM2_CTRAIN 0–999 (10 tessons de 100), HOWM2_CVAL (48) : 1 048 établissements, un épisode chacun, 48 origines par établissement. Manifeste `DATA_MANIFEST.json`, 281 Mo hors dépôt. |
| Indépendance | `PARTITIONS_CHECK.json` : clés disjointes entre elles et de G0, HOWM2_REF et HOWM2_DIAG ; 1 548 vecteurs θ distincts ; génération fonction de la seule ekey. Seuls les identifiants et métadonnées ont été lus. |
| Entraînements achevés | 15 sur 18 prévus : C.1, C.2b et C.2a à N = 100 ; C.1 et C.2b à N = 1 000 ; 3 graines chacun. |
| Non exécutés | C.2a à N = 1 000, 3 exécutions (§ 4). |
| Un passage | Pour chaque exécution, les positions consommées sont **exactement** le flux prévu (`exact_one_pass_no_replay = true`) : 150 mises à jour × 32 origines = 4 800 exemples (100 établissements) à N = 100 ; 1 500 mises à jour = 48 000 exemples (1 000 établissements) à N = 1 000. |
| Sélection | `SELECTION.json`, sur CVAL seulement. Point retenu : 1 000 pour C.1 et C.2b, 100 pour C.2a. Système de tête : **C.2b** (perte CVAL normalisée moyenne 7,883, contre 7,953 pour C.1). |
| Gel F-C1 | `F_C1.json` : 15 poids `best.pt` et leurs états, code, références, script d'analyse, liste fermée des comparaisons. |
| Campagne finale unique | HOWM2_CEVAL (200) et HOWM2_DIAG (100), origines C1, H1, H6 et H24. Références L0–L5 et L2c ; 5 mélanges (C.1@100, C.1@1000, C.2b@100, C.2b@1000, C.2a@100). |
| Analyse | `RESULTS_C1_P1.json`, script gelé (n° 40). |

**Temps d'entraînement mesurés** (secondes par exécution, un fil) :

| Exécution | Secondes |
|---|---:|
| C.1 et C.2b à N = 100 | 163 à 171 |
| C.2a à N = 100 | 2 201 à 2 278 |
| C.1 et C.2b à N = 1 000 | 1 465 à 1 670 |

Le détail par exécution est dans `TRAINING_SUMMARY.json`.

## 2. Résultats sur CEVAL (200 établissements)

**Pertes absolues à H24** (nats par item ; agrégat R1 de L, sans l'autorisation) :

| Système | L | L2 | L2c | L4 |
|---|---:|---:|---:|---:|
| C.1@100 | 2,2256 | 2,1855 | 2,1896 | — |
| C.1@1000 | 2,2094 | | | |
| C.2b@100 | 2,2253 | | | |
| **C.2b@1000** | **2,1882** | | | |
| C.2a@100 | 2,2257 | | | |

**Par famille à H24, C.2b@1000.** R = L2 (choix de l'agrégat à cet horizon). Pour chaque famille :
L du modèle, gain L_R − L_modèle [IC], dénominateur L_R − L4 [IC] et ρ_f [IC].

| Famille | L modèle | L2 | L2c | L4 | Gain [IC] | Dénominateur [IC] | ρ_f [IC] | Stabilité |
|---|---:|---:|---:|---:|---|---|---|---|
| ready | 3,4856 | 3,4609 | 3,4609 | 3,1439 | −0,025 [−0,045 ; −0,007] | 0,317 [0,268 ; 0,374] | −0,08 [−0,15 ; −0,02] | stable |
| confirmation | 2,9223 | 2,9580 | 2,9831 | 2,6658 | +0,036 [+0,022 ; +0,047] | 0,292 [0,254 ; 0,332] | +0,12 [+0,08 ; +0,16] | stable |
| arrivées | 0,4624 | 0,4613 | 0,4613 | 0,4600 | −0,001 [−0,002 ; −0,000] | 0,0013 [0,0008 ; 0,0018] | −0,87 | **instable** |
| soins | 1,5386 | 1,5430 | 1,5430 | 1,5243 | +0,005 [+0,002 ; +0,007] | 0,0187 [0,0166 ; 0,0210] | +0,24 | **instable** (borne basse < 0,02) |
| transport (descriptif) | 2,4647 | 2,4538 | 2,4538 | 2,3447 | | | | |
| nettoyage (descriptif) | 2,2623 | 2,2420 | 2,2420 | 2,1277 | | | | |

Présence : aucun item. Les tableaux complets, pour chaque système, horizon et famille, avec tous les
IC, sont dans `RESULTS_C1_P1.json`.

**Lecture.**
- Le réseau gagne sur la **confirmation** (+0,036) et un peu sur les **soins**.
- Il reste **moins bon** que L2 sur **ready**, transport et nettoyage. À H6, la perte sur ready
  domine : −0,046 [−0,064 ; −0,030].
- C.2b ne devance C.1 que sur transport et nettoyage. Ses entrées L2 y aident, mais restent
  au-dessus de L2.

**Échelle, de N = 100 à N = 1 000** (L à H24) :
- C.1 : 2,2256 → 2,2094 (−0,016) ;
- C.2b : 2,2253 → 2,1882 (−0,037).

Les modèles à N = 100 sont tous presque identiques. Ils partent de la même initialisation, et 150
mises à jour les éloignent peu des têtes B0 ; C.2a@100 ≈ C.1@100. Avec deux points, aucune forme de
loi d'échelle n'est revendiquée.

## 3. Transfert vers HOWM2_DIAG (100 établissements, descriptif, sans réentraînement)

Les poids sont identiques à F-C1. Sur DIAG, C.2b@1000 obtient :

| Horizon | ΔC [IC 95 %] |
|---|---|
| H1 | −0,003 [−0,010 ; +0,003] |
| H6 | −0,008 [−0,017 ; +0,002] |
| H24 | −0,005 [−0,015 ; +0,005] |

C.1@1000 est nettement moins bon : ΔC = −0,111 à H6.

Il n'y a ni verdict ni sélection sur DIAG.

## 4. Limites, incidents et écarts (tous consignés)

1. **C.2a à N = 1 000 non exécuté.**
   - Le pilote (n° 14) mesure 13 s par pas sur un fil pour C.2a, contre 0,94 s pour C.1. Le
     contexte complet multiplie la longueur des séquences et la taille des graphes.
   - 3 graines à N = 1 000 coûteraient environ 60 000 s CPU, au-delà de l'enveloppe de 17 400 s.
   - Selon la norme § 6, c'est signalé : C.2a n'a pas de verdict, et N = 100 n'est pas substitué.
   - C.2a@100 est rapporté à titre descriptif.
2. **Réallocations entre lots**, total inchangé, consignées avant usage : C.TRAIN.100 passe de
   1 100 à 3 000 puis à 4 600 s, C.TRAIN.1000 de 9 900 à 6 000 s, réserve de 1 100 à 1 500 s.
3. **Mémoire.** Plusieurs processus ont été tués par le noyau, faute de mémoire (15 Go, sans
   swap) :

   | Exécution | Moment | Conséquence |
   |---|---|---|
   | C.2a@100 graine 1 | deux fois, n° 17 et 18 | jamais de checkpoint à ce stade, repartie de zéro |
   | C.1@1000 graine 2 | n° 21 | sans checkpoint, repartie de zéro |
   | C.2b@1000 graine 1 | n° 21 | reprise au checkpoint de 410 pas |
   | C.2a@100 graine 0 | n° 31 | reprise à son checkpoint |

   La trajectoire **retenue** de chaque modèle est un passage exact. Les exemples traités par un
   processus tué, puis rejetés, n'ont laissé aucune trace dans les poids. Les commandes n° 17 et 18
   ont atteint le plafond de 540 s.
4. **Correctif de code avant mesure.**
   - Un conflit de nom dans la fenêtre C.2a dérivée faussait le lot dès 8 origines. Le pilote n° 10
     a échoué.
   - Les tests T-C05 et T-C06′ passaient par chance ; ils ont été renforcés (T-C05b) avant tout
     entraînement.
   - Après les premiers entraînements, le pilote d'entraînement a aussi été rendu robuste aux
     processus tués et au chargement différé de CVAL. Le calcul des pas est inchangé.
5. **Redémarrage du conteneur** pendant la campagne CEVAL. La commande interrompue n'avait écrit
   aucun enregistrement. Elle est consignée au n° 36, à 240 s (estimation majorée). Les 43
   fichiers écrits ont été validés ; la campagne a repris sans recalcul.
6. **Mesures secondaires non exécutées** : calibration (PIT) et sondes de θ. Elles ne figuraient
   pas dans la liste fermée de F-C1 ; les ajouter après l'ouverture de CEVAL était exclu.
7. **Invocations hors registre**, déclarées dans la norme § 13 : quelques secondes de vérification
   d'import et une collecte pytest échouée.

## 5. Budget (`evidence/howm2_c1/BUDGET_LEDGER_HOWM2_C1.jsonl`)

| Lot | Plafond (s) | Utilisé avant reçu (s) |
|---|---:|---:|
| C.SETUP | 700 | 37,8 |
| C.GEN | 700 | 308,1 |
| C.PILOT | 300 | 208,5 |
| C.TRAIN.100 | 4 600 | 3 649,0 |
| C.TRAIN.1000 | 6 000 | 3 167,0 |
| C.EVAL | 3 000 | 1 307,7 (avec la commande interrompue, 240) |
| C.REST | 600 | 97,8 |

- **Total final :** **8 776,0 s** sur 17 400.

**Paquet et reçu**
- Paquet : `HOWM2_P2_C1_P1_FINAL.zip`, sha256
  `bd8a75994fe076cf24eafcb1af4e44eaddeb09e3d195ada69e7f643f5e1c7a35`, 67 Mo, commit 4ca78309.
  Il ne contient pas les tessons de données (281 Mo) : ils sont régénérables, avec leurs empreintes
  dans le manifeste.
- Reçu `RESTORE_RECEIPT_C1_P1.json` (n° 43), obtenu dans un répertoire neuf, en quatre sections
  distinctes :
  1. **Intégrité** : 397 fichiers vérifiés, 0 erreur.
  2. **Chargement des checkpoints** : les 15 `best.pt` de F-C1, avec contrôle d'empreinte,
     chargement et passe avant finie.
  3. **Reproduction de l'analyse** : `RESULTS_C1_P1.json` identique.
  4. **Régénérations effectivement faites** :
     - scores finaux de CEVAL 0 et 1, identiques ;
     - un enregistrement d'entraînement (CTRAIN 0), régénérable.
- Tests C1 : 11 réussis.
- **L'entraînement n'a pas été rejoué**, et le reçu ne le prétend pas (`training_reproduced = false`).
- **Le CPU** est enregistré séparément dans chaque ligne du registre. Les commandes tuées n'ont
  pas d'enregistrement CPU complet.
- **Échecs conservés :** n° 10 (pilote), n° 17 et 18 (plafond), n° 36 (interrompue).

## 6. Suite, proposée (non autorisée par ce mandat)

**Palier 2.** Règle N9′, reproduite **exactement** de `NORME_C1_AMENDE_PROPOSEE.md` :

> « Palier 2 : N = 10 000, 1 graine par système, puis 2 graines du meilleur selon CVAL. Il est lancé
> si et seulement si, pour au moins un système, CVAL(100) − CVAL(1 000) > 2 × l'écart-type entre
> graines à N = 1 000. »

**Évaluée sur CVAL, à titre descriptif seulement :**

| Système | CVAL(100) − CVAL(1 000) | 2 × écart-type à N = 1 000 | Condition |
|---|---:|---:|---|
| C.1 | 0,055 | 0,020 | remplie |
| C.2b | 0,124 | 0,0025 | remplie |
| C.2a | — | — | non évaluable |

**Les 45 000 s du plan C1 amendé** forment un plafond **supplémentaire**, propre au palier 2, et non
un total qui inclurait le palier 1. Le texte d'accord C1 amendé dit « Palier 2 (10 000) : lancé
seulement selon la règle N9′, plafond de 45 000 s », à côté du plafond de 17 400 s du palier 1.

**CEVAL ne peut plus servir.** Cette population a été ouverte (campagne n° 36 à 40). Elle ne peut
plus fournir de confirmation indépendante pour un palier 2. Un protocole de palier 2 devra définir
une nouvelle population d'évaluation, jamais ouverte, et le déclarer.

**C.2a.** Une exécution à N = 1 000 demanderait environ 60 000 s CPU, soit environ 4 h 30 de temps
mural sur 4 cœurs, ou une redéfinition à coût borné, par exemple un contexte tronqué. Cette
redéfinition serait une nouvelle variation à déclarer : elle n'est pas proposée ici en silence.
