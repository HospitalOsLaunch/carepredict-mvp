# HOWM-INT-1 — tableau d'avancement (mis à jour en continu)

**Décision** n° 9. Mandat : `docs/howm2/inputs/MANDAT_HOWM2_DECISION_9_HOWM_INT_1.md`.

**Protocole** : `docs/howm_int1/PROTOCOLE_INT1.md`, consigné avec son plan réalisable (note `int1_protocol`).

**Rapport** : `docs/howm_int1/RAPPORT_INT1.md`. **Démonstration** : `docs/howm_int1/DEMO.md`.

**Registre :** `evidence/howm_int1/LEDGER_INT1.jsonl`.

- Runner : `scripts/int1/ledger_run.py` (verrou fcntl depuis l'incident #38 ; nommé `scripts/howm_int1_run.py` pendant la campagne, déplacé le 23 novembre pour ne plus entrer dans le motif gelé `scripts/howm_*.py` des tests HOWM-1).
- Statut : `python3 scripts/int1/ledger_run.py --status`.
- 540 s par commande ; lots `INT.L0`, `INT.DATA`, `INT.LEARN`, `INT.EVAL`, `INT.REST`, `INT.RESERVE`.

**Chemins.** Venv, corpus, runs et évaluation sont dans le scratchpad :
`/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad/{venv_howm,int1_corpus,int1_runs,int1_eval}`.

**Aucun push** (consigne de l'utilisateur), même si un hook automatique le demande.

## Construit, appris, évalué, incertain

| Élément | État | Preuve |
|---|---|---|
| Monde N unités (M1–M8), engagements, budgets, boucle fermée, vue publique propre | construit, testé (I1–I10, M1–M7 : 31 tests) | `tests/howm_int1/` |
| Qualification et révision (k = n/2, action d'aval) | faite avant toute comparaison | `QUALIFICATION_DEV.json` |
| Corpus palier 1 et 2 (10 000 structures), VAL (300, K = 4) | fait, manifestes avec empreintes | `MANIFEST_CORPUS.json` |
| W `GraphWM` S et M, 3 graines × 2 paliers ; ablations | appris | `CURVES.json` |
| D (Ridge, HGB, DSet), paliers 1 et 2 | appris | `SYSTEMS_CANDIDATES.json` |
| Diagnostic SF1, propagation DEV | faits | `DIAG_SF1.json`, `PROPAGATION_DEV.json` |
| Panel VAL en boucle fermée, gel | faits (B\* = historique, W = W-M) | `VAL_PANEL.json`, `FREEZE_INT1.json` (#562) |
| Évaluation finale MAIN, EXT, COMBO, SIZE12 | **évaluée** | `RESULTS_INT1.json` |
| Sous-panel SUB32 (F, R1) | **évalué** (384/384) : F − W +861 [4 ; 1 757], R1 − W +624 [308 ; 1 014] | `RESULTS_INT1.json` |
| Propagation selon W (VAL), tables post-hoc MAIN | faites, descriptives | `PROPAGATION_W_VAL.json`, `POSTHOC_MAIN.json` |
| Démonstration rejouable | faite | `DEMO.md`, `DEMO.json` |
| Archive, reçu en environnement neuf, enveloppe | **faits** ; reçu ok sur toutes les sections | `PACKAGE_FINAL.json`, `RESTORE_RECEIPT_INT1.json`, `CLOSURE_ENVELOPE_INT1.json` |

## Résultats (évaluation finale)

| Mesure | Valeur |
|---|---|
| B\* − W (MAIN) | **+1 244** [405 ; 2 226] → `GAIN_W_ETABLI` |
| Gain relatif | 3,5 % [1,2 ; 6,0] ; cible de 5 % non atteinte |
| W-M face à D-HGB (meilleure référence, post-hoc) | +142 [13 ; 260], soit 0,4 % |
| Garde-fous face à B\* | soins non couverts +572, heures-agents +12,9 ; ruptures −52 min |
| EXT / COMBO / 12 unités | −30 [−50 ; −11] / +6 [−35 ; 52] / −22 [−54 ; 26] |
| Anticipation | AUC 0,92, Brier 0,031 (surconfiance dans le décile haut) |

## État

Campagne livrée. Rapport : `docs/howm_int1/RAPPORT_INT1.md`. Aucun push.
