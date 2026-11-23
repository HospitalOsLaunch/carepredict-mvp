# HOWM-INT-1 — estimation de fin (17 novembre 2026, 22 h 22 UTC)

Estimation fondée sur les débits mesurés au registre (commandes #282 à #324). C'est une projection, pas un
engagement. Deux grandeurs sont distinguées :

- **temps calendaire** : temps écoulé ;
- **budget comptabilisé** : somme des durées des commandes au registre ; deux commandes concurrentes comptent
  toutes deux.

**Consommé à ce jour :** 59 430 s de mur sur 259 200 (23 %), soit DATA 22 569, LEARN 35 954, L0 907 ;
91 122 s de CPU sur 1 036 800 (9 %).

## Débits mesurés

| Élément | Mesure | Conditions |
|---|---|---|
| Corpus palier 2 | 95 structures par commande de 410 s (≈ 800 s CPU) | en parallèle de W-M ; seul : ≈ 230 par 480 s |
| W-M palier 1 | ≈ 350 mises à jour par commande et par graine (≈ 0,8/s) | 3 graines dans une commande, avec le corpus en parallèle |
| W-S palier 1 | ≈ 2 000 mises à jour par commande de 447 s (≈ 4,5/s) | 3 graines en commandes séparées, avec le corpus |
| Branchement moteur | 0,03 s (2 unités, 48 h) ; 0,08–0,09 s (8–12 unités, 24 h) | pilote de coût |
| Décision F (Md = 4) | 3,2 s CPU | R1 : 1,6 s |
| Décision W non entraîné | 0,1–0,3 s hors contention | à remesurer avec les modèles finaux |

**État à 22 h 22 :** corpus 4 571 / 10 000 ; W-M palier 1 à environ 13 200 / 20 000 ; W-S palier 1 terminé.

## Projection par étape

| Étape | Calendaire | Budget comptabilisé | Base |
|---|---|---|---|
| Fin de W-M palier 1 (≤ 6 800 mises à jour restantes) | 1,5–2,5 h | 5–8,5 ks | 350 par commande ; la patience peut l'arrêter plus tôt |
| Fin du corpus (5 429 structures) | 3–6,5 h | 11–23 ks | 230 par commande seul, 95 en concurrence |
| Ablations VAL (sans historique, sans messages ; 1 commande) | 1 h, en parallèle du corpus | 4 ks | débit S mesuré |
| D (DSet palier 1, puis Ridge, HGB et DSet palier 2) | 1–1,5 h, en parallèle du corpus | 4–6 ks | HGB 30–40 s au palier 1, ×10 de lignes |
| Empaquetage du palier 2 | 0,3 h | 1 ks | lecture de 10 000 fichiers |
| Palier 2, W-S (≤ +30 000 mises à jour, 3 graines) | 0,8–1,6 h | 3–6 ks | 6–10 mises à jour/s par graine sans corpus |
| Palier 2, W-M (≤ +20 000, 3 graines) | 2,2–3,7 h | 8–13 ks | 1,5–2,5 mises à jour/s par graine sans corpus |
| Panel VAL (B\* et taille de W), tests, gel, pilote de coût d'évaluation | 0,7–1 h | 2,5–3,5 ks | 40 × 2 boucles fermées × 7 politiques |
| Évaluation finale (MAIN, SUB32 F/R1, EXT, COMBO, SIZE12) | **6–12 h** | 22–45 ks | ≈ 106 ks CPU projetés, dont MAIN ≈ 32, SUB32 F/R1 ≈ 48, extensions ≈ 26 ; 4 processus |
| Analyse, démonstration, rapport, archive, reçu neuf, enveloppe | 1,5–2,5 h | 5–9 ks | reçus précédents de 110–210 s, plus les régénérations annoncées |

## Synthèse

**Chemin critique :**

1. corpus palier 2 ;
2. empaquetage ;
3. W-M palier 2 (l'apprentissage le plus long) ;
4. panel VAL et gel ;
5. évaluation finale, dominée par le sous-panel F/R1 à Md = 16 et par les décisions de W-M ;
6. livraison.

Ablations, D, W-S palier 2 et diagnostics se placent en parallèle et ne sont pas sur ce chemin.

**Temps calendaire restant : 15 à 26 h**, valeur centrale ≈ 19 h.

- Borne basse : corpus seul dès la fin de W-M, coûts de décision bas, arrêts par patience.
- Borne haute : contention prolongée et décisions des modèles finaux plus coûteuses.

**Budget comptabilisé final projeté : 145 à 185 ks de mur sur 259,2 ks (56–71 %)**, et 75 à 100 h de CPU sur
288. Le lot `INT.EVAL` (43,2 ks) peut être dépassé dans le haut de la fourchette d'évaluation. Une réallocation
documentée depuis `INT.RESERVE` (25,2 ks) est alors prévue, sans dépasser le plafond.

**Plus grande incertitude : le coût de l'évaluation.** Il dépend du coût réel des décisions de W-M et de F à
Md = 16. Un pilote de coût d'évaluation sur DEV, après le panel VAL et avant le gel, resserrera cette
fourchette. Les volumes de panel seront fixés avant toute ouverture du test et ne seront pas modifiés après.

**Pour réduire le calendaire sans changer le protocole :**

- au plus 2 commandes concurrentes ;
- 4 processus pour le corpus dès la fin de W-M ;
- W-S et W-M du palier 2 lancés l'un après l'autre (ou ensemble si la mémoire le permet), en une commande chacun.

## Mise à jour (18 novembre) — pilote de coût d'évaluation sur DEV (`EVAL_COSTPILOT_DEV.json`, registre #426)

**Coûts mesurés avec les modèles entraînés du palier 1**, en CPU par boucle fermée (une politique, un
épisode-futur) :

| Politique | 2 unités, 7 jours | 4 à 12 unités, 24 h |
|---|---|---|
| Règles | 0,2 s | — |
| D | 0,35–0,55 s | 0,1–0,5 s |
| W-S | 0,8–1,0 s | 0,4–1,1 s |
| W-M | 1,9 s | 0,9–2,7 s |
| **F (Md = 16)** | **79 s** (11,2 s par décision) | — |
| **R1 (Md = 16)** | **49 s** (7,0 s par décision) | — |

**Évaluation projetée : ≈ 72 ks de CPU** (MAIN ≈ 15 ; SUB32 F/R1 ≈ 49 ; EXT, COMBO et SIZE12 ≈ 8), au lieu de
106. Cela donne **4,5 à 7 h de calendrier** et 17 à 26 ks de budget comptabilisé.

**Temps calendaire restant : 12 à 20 h.**

---

# Mise à jour du 18 novembre 2026, 11 h 02 UTC (débits mesurés au registre)

**Définitions.** Le temps calendaire est le temps écoulé. Le budget comptabilisé est la somme des durées des
commandes au registre : des commandes concurrentes comptent chacune.

## Étapes terminées : réalisé mesuré

| Étape | Mur comptabilisé | CPU | Débit mesuré |
|---|---|---|---|
| Corpus (10 000 structures + VAL), lot DATA | 39 689 s | 91 425 s | 2,1 s de mur par structure à 4 processus seuls, environ 4 fois moins en concurrence |
| Apprentissage (W S/M × 3 graines × 2 paliers, D, ablations), lot LEARN | 62 610 s | 97 379 s | W-S 10,1 mises à jour/s, W-M 2,7/s (1 fil) |
| Évaluation MAIN, EXT, COMBO, SIZE12 | inclus dans EVAL | inclus | — |

**Palier 2, mises à jour réalisées par graine :**

| Taille | Mises à jour (meilleure) |
|---|---|
| S | +15k (7k), +14k (6k), +14k (6k) |
| M | +14k (6k), +9k (1k), +16k (8k) |

Les deux tailles se sont arrêtées par patience.

## Reste à faire

**SUB32 (F et R1, 384 fichiers, un par futur) : 192 / 384 à 11 h 02.**

| Mesure | Valeur |
|---|---|
| Durée d'une tâche | moyenne 202 s CPU ; p90 256 s ; maximum 276 s |
| Débit sur la dernière heure | 68 fichiers/h (4 processus) |
| Coût par fichier | ≈ 52 s de mur comptabilisé et ≈ 190 s de CPU |

Le budget de lancement est de 200 s depuis le dépassement #677, d'où des commandes d'environ 320 s.

**Livraison** (coûts mesurés pendant la répétition du reçu, #624–#648) :

| Élément | Durée |
|---|---|
| Archive | 22 s |
| Reçu : mise en place | 29 s |
| Reçu : tests | 7 s |
| Reçu : chargement | 62 s |
| Reçu : analyse | 56 s |
| Reçu : régénérations | 195 s |
| Reçu : réajustements | 48 s |
| Analyse gelée | 4 s |
| Enveloppe | ≈ 10 s |

S'y ajoutent la rédaction et les vérifications, hors registre.

## Projection

| Étape | Calendaire | Mur comptabilisé | CPU |
|---|---|---|---|
| SUB32 restant (192 fichiers) | **2,6–3,3 h** (58–75 fichiers/h) | 9–11,5 ks | 33–40 ks |
| Analyse finale, rapport § 9 | 0,3–0,5 h | < 0,1 ks | — |
| Archive, reçu neuf, enveloppe | 0,5–1 h | 0,5–0,9 ks | 0,6–1 ks |
| **Total restant** | **3,4–4,8 h** → fin vers **14 h 30–16 h UTC** | **≈ 10–12,5 ks** | ≈ 34–41 ks |

## Totaux projetés en fin de campagne

| Grandeur | Projection | Plafond | Part |
|---|---|---|---|
| Mur comptabilisé | 130–133 ks | 259,2 ks | 50–51 % |
| CPU | 286–293 ks (79–81 h) | 288 h | 28 % |

Le CPU au 18 novembre à 11 h 02 était de 251,6 ks, dont 2,6 ks de corrections déclarées. La réserve de 7 h n'est
pas utilisée ; le coût est de 0 €.

**Calendaire total :** de la genèse (17 nov. 15 h 43) à la fin, environ 23–24,5 h.

## Chemin critique

**SUB32**, borné par le CPU :

- 4 cœurs ;
- décision F ≈ 15 s CPU à Md = 16, R1 ≈ 9 s ;
- 7 décisions par futur.

Ensuite : analyse gelée finale → § 9 du rapport → archive finale → reçu (il exige l'archive finale) → enveloppe.
Rien d'autre ne peut avancer en parallèle, sauf la rédaction.

## Risques et effet sur la fourchette

| Risque | Effet |
|---|---|
| Relance de la chaîne à chaque créneau d'arrière-plan de 2 h (une relance prévue) | + 0–10 min |
| Nouveau dépassement de 540 s | improbable avec 200 s + 276 s maximum ; + 5–10 min, travail en vol recalculé |
| Redémarrage du conteneur | reprise sans perte, hors tâches en vol ; + 10–20 min |
| Échec d'une section du reçu final | correction puis nouvelle section ; + 15–30 min |
