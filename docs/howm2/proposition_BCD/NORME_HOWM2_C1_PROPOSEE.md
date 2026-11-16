# NORME HOWM2-C1 (proposée, non adoptée)

Cette norme ne s'applique que si l'accord `ACCORD_HOWM2_C1_A_ADOPTER.md` est adopté tel quel. Une
fois adoptée, elle est consignée dans le registre `BUDGET_LEDGER_HOWM2_C1` avant toute mesure.

**N1. Espaces de clés**
- Partitions enregistrées à l'exécution : `HOWM2_CTRAIN` (REF, 10 000), `HOWM2_CVAL` (REF, 48) et
  `HOWM2_CEVAL` (REF, 200).
- Clés `key("HOWM1", part, i)`.
- Disjonction testée contre G0 et contre HOWM2_REF et HOWM2_DIAG.
- Aucun fichier gelé (G0, F1) n'est modifié.

**N2. Origines.** `range(24, 166, 3)` pour toutes les partitions de C1, soit 48 origines par
établissement. Elles sont fixées ici.

**N3. Un passage**
- Chaque établissement de `HOWM2_CTRAIN` contribue à au plus une époque.
- Les points d'échelle N ∈ {100, 1 000, 10 000} utilisent le préfixe [0, N).
- Le journal des clés consommées est versé aux preuves.

**N4. Entraînement**
- Comme R1 : Adam, lot de 32 origines, lr 3e-4, échelles s_f de R1, têtes de R1.
- Évaluation sur `HOWM2_CVAL` tous les 500 pas (et à la fin), patience de 6, on garde le meilleur.
- Perte d'entraînement par famille journalisée à chaque évaluation.
- Checkpoints toutes les 400 s au plus, reprise exacte.

**N5. Systèmes**
- C.1 : H1 gelé (W = 24 h).
- C.2 : H1-long, défini dans `src/hospitalos/howm2/`. Contexte = tout le passé public filtré par
  `available_at`. Les entrées de fenêtre locale sont celles de L2. Têtes et dimensions sont
  inchangées.
- Aucun autre système.

**N6. Gel F-C1**, avant toute lecture de `HOWM2_CEVAL`. Il consigne :
- le hash du code ;
- les hash des poids retenus ;
- le point d'échelle retenu ;
- les graines.

**N7. Critère principal**
- Sur `HOWM2_CEVAL`, ΔC(h) = L(L2) − L(modèle), où le modèle est la moyenne des prédictions des
  graines au point retenu (mélange équipondéré).
- Agrégation R1 : moyenne non pondérée des NLL moyennes des familles présentes, autorisation
  exclue ; établissements équipondérés.
- Bootstrap par grappes d'établissements, B = 2 000, graine `key("HOWM2", "C1", "bootstrap") mod 2^31`.

| Verdict | Condition |
|---|---|
| `C1_BAT_L2` | borne basse de l'IC à 95 % > 0 à H6 **et** à H24 |
| `C1_NE_BAT_PAS_L2` | borne haute < 0 à H6 et à H24 |
| `C1_INDETERMINE` | sinon |

Le verdict est rendu par système (C.1, C.2). Le verdict de la tranche est le meilleur des deux,
choisi selon `HOWM2_CVAL` et non selon `HOWM2_CEVAL`.

**N8. Ambition**
- ρ(h) = (L(L2) − L(modèle)) / (L(L2) − L(L4)), sur les familles validées en A (ready,
  confirmation, présence, arrivées, soins).
- Libellé `AMBITION_ATTEINTE` si l'estimation ponctuelle est ≥ 0,5 à H6 et à H24, sinon
  `AMBITION_NON_ATTEINTE`. L'IC est toujours rapporté.

**N9. Loi d'échelle.** L(modèle, N) pour N ∈ {100, 1 000, 10 000} sur `HOWM2_CEVAL`, avec la
moyenne des graines disponibles. Ajustement a + b·N^(−c) par moindres carrés, descriptif.

**N10. Transfert (D)**
- Sur `HOWM2_DIAG` (100), les poids gelés F-C1 sont réutilisés sans réentraînement.
- ΔC et ρ sont rapportés, de façon descriptive, sans verdict.

**N11. Interdits**
- Réserve HOWM-1, DEVTEST, DIAG-DEV.
- v6, P5, `mvp/computer-use`, résultats R1 et A livrés.
- Toute décision, JEPA, boucle fermée, P6, AJ-H.
- Push, merge, rebase.

**N12. Arrêt**
- Si un point est infaisable, contradictoire avec un gel, ou si un dépassement est projeté : arrêt
  et question avec options.
- L'échelle de réduction du plan de calcul est la seule adaptation permise sans question.
- Aucun seuil, aucune population et aucun verdict n'est redéfini.
- Résultats favorables et défavorables livrés de la même façon.
