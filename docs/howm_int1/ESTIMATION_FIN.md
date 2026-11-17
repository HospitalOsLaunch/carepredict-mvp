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
