# Point de reprise

État : P0–P4 livrés ; V5-R01 **clos** par l'audit indépendant v6 (voir `CLOSURE_RECEIPT_v6.md`).
Référence conservée : paquet v6. Statut global **`PARTIAL_WITH_CHECKPOINT`** : portes ouvertes =
Python 3.11.9 exact, rejeu React/navigateur indépendant. Registre : 175 enregistrements,
421,325 s, reliquat 178,675 s. P5 et P6 **fermés** (protocole et budget distincts).

## Reprise exacte

```bash
# depuis le paquet : vérifie les SHA-256, restaure la branche dans un dossier neuf, rejoue tests + export
sh restore.sh --verify-only                   # deux manifestes + registre terminal
sh restore.sh /chemin/vers/dossier_neuf
# depuis un clone existant à a5e737e : appliquer les patchs
git checkout -b claude/hospitalos-auto-first-p0-p4-s2dywn a5e737eec2cfdf0f52a68f41b523f928181c03e6
git am patches/*.patch
python3 scripts/ds_budget_run.py --status     # DANS le dossier restauré : registre le plus récent
                                              # du paquet installé, prolongé par le rejeu
```

Le registre `evidence/decision_support/BUDGET_LEDGER.jsonl` est chaîné : toute modification
d'un enregistrement bloque le compteur (aucun contournement par remise à zéro).

## Prochaines étapes possibles (chacune sur accord distinct)

1. (Fait en P4b : route React « Plan 24 h », 71/71 Vitest, e2e 17/17.) Éventuellement découper le
   bundle (données de démonstration en import dynamique) pour lever l'avertissement de taille.
2. Exécuter `mypy --strict` sur `hospitalos.decision_support` et corriger.
3. Revue métier des paramètres synthétiques (`UNIT_PROFILE.json`) — aucun entretien n'a eu lieu.
4. P5 (qualification expérimentale bornée) : protocole proposé **`P5_PROTOCOL_v2.md`
   (P5-PROTO-2)** et `P5_PROTOCOL_PARAMS_v2.json`, amendés après revue (changements et décisions
   D1–D12 : `P5_CHANGES_v1_to_v2.md`) ; originaux P5-PROTO-1 conservés. **Non exécuté, non
   autorisé.** Budget distinct proposé, non activé : 1200 s avec échelle de repli (ou 1800 s),
   30 s par commande, 0 € ; devis ≈ 494–1377 s. scikit-learn requis pour P5b (installation à
   autoriser séparément). Aucun budget P0–P4 ni AJ-H antérieur n'est réutilisable.
   **D1–D12 approuvées** selon les recommandations (`P5_DECISIONS_v2.md`) : protocole approuvé,
   exécution **non autorisée** ; restent à accorder : (i) mise en œuvre + pilote P5.0–P5.2,
   installation de scikit-learn, (ii) évaluation P5a, (iii) ajustements et évaluation P5b.
   **P5.0–P5.2 exécutés** (`P5_LOT_REPORT_P5_0-2.md`) : registre P5 8,383 s / 1200 s ; 24/24 tests ;
   pilote partiel (ajustements non chronométrés, scikit-learn absent). Prochaine décision : D4
   (installation), puis fin du pilote (chronométrage de 2 ajustements) avant (ii)/(iii).
   **Reprise après revue** (`P5_LOT_REPORT_P5_0-2_REPRISE.md`) : contrôles P5L-01..03 corrigés,
   42/42 tests sous E1, registre P5 13,769 s / 1200 s ; P5-PROTO-3 proposé (non approuvé).
   Décisions attendues : D13 (v3), D14 (= D4), D15 (banc de 6 ajustements), D16 (option).
   **Finalisation** (`P5_FINALISATION_REPORT.md`) : P5-PROTO-3.1 proposé, couple (Python, gel)
   contrôlé, refus journalisés, 52/52 tests sous E2, registre P5 18,645 s / 1200 s (23 enr.).
   Accords demandés : D13 (v3 + v3.1 par empreintes), D14 (= D4), D15 (banc A5).
   **D13–D15 adoptés et exécutés** (`P5_A5_REPORT.md`) : scikit-learn 1.8.0 installé isolément
   (P5.I 8,557 s), banc A5 6/6 (M_agg ~1,8 s, M_ent ~4,6 s par ajustement), condition L2 satisfaite
   sur ce banc ; registre P5 53,917 s / 1200 s. Arrêt après A5. Suite : (ii), (iii) sur accords distincts.
   **(ii) P5a adopté et exécuté** (`P5_P5a_REPORT.md`) : dev 10×10, F_a, réservé 30×10 R1/R2 K=3 ;
   gain R1 217,1 [187,3 ; 248,0] min-soignant/épisode, part capturée 96,6 %, 0/30 structure dégradée ;
   verdict `exploratory` (précision projetée 33,9 > 7,5 déclarée avant F_a). Arrêt après P5a. (iii) fermé.
   **Contrôle d'isolation 50 épisodes (adopté, postérieur au gel)** (`P5_P5a_ISOLATION50_REPORT.md`) :
   47/50 réussis, arrêt au 48ᵉ sur précondition (`no_distinguishable_truth_pair`, pas une fuite) ;
   P5A-D02 non clos ; amendement de procédure = décision distincte.
   **Reprise adoptée (méthode v2, rangs 48–50)** (`P5_P5a_ISOLATION50_RESUME_REPORT.md`) : 50/50 couverts,
   0 vrai échec ; T04-a non informatif au rang 48 ⇒ clôture de P5A-D02 = décision explicite.
   **P5A-D02 clos avec réserve nommée** (décision adoptée ; `P5A_D02_CLOSURE_RECEIPT.md`) :
   T04-a NON_INFORMATIF au rang 48 conservé ; P5.1 exact = 43,770 s ; registre 88 enr., 134,580 s.

## Hors de ce projet

Reprise de A_detached (authentifié à 2000, final 6000 non attesté — pas un échec scientifique),
lots B/C, chargement de poids : mandat distinct, vérification préalable de l'absence de doublon distant.
