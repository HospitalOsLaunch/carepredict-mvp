# HOWM-INT-1 — tableau d'avancement (mis à jour en continu)

**Décision** n° 9. Mandat : `docs/howm2/inputs/MANDAT_HOWM2_DECISION_9_HOWM_INT_1.md`.

**Protocole** : `docs/howm_int1/PROTOCOLE_INT1.md`, consigné avec son plan réalisable (note `int1_protocol`).

**Rapport** : `docs/howm_int1/RAPPORT_INT1.md`. **Démonstration** : `docs/howm_int1/DEMO.md`.

**Registre :** `evidence/howm_int1/LEDGER_INT1.jsonl`.

- Runner : `scripts/howm_int1_run.py` (verrou fcntl depuis l'incident #38).
- Statut : `python3 scripts/howm_int1_run.py --status`.
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
| Sous-panel SUB32 (F, R1) | en cours (384 fichiers, un par futur) | `int1_eval/SUB32` |
| Propagation selon W (VAL), tables post-hoc MAIN | faites, descriptives | `PROPAGATION_W_VAL.json`, `POSTHOC_MAIN.json` |
| Démonstration rejouable | faite | `DEMO.md`, `DEMO.json` |
| Archive, reçu en environnement neuf, enveloppe | scripts prêts ; répétition du reçu faite (défauts corrigés) | `REHEARSAL_SUMMARY.json` |

## Résultats (évaluation finale, avant SUB32)

| Mesure | Valeur |
|---|---|
| B\* − W (MAIN) | **+1 244** [405 ; 2 226] → `GAIN_W_ETABLI` |
| Gain relatif | 3,5 % [1,2 ; 6,0] ; cible de 5 % non atteinte |
| W-M face à D-HGB (meilleure référence, post-hoc) | +142 [13 ; 260], soit 0,4 % |
| Garde-fous face à B\* | soins non couverts +572, heures-agents +12,9 ; ruptures −52 min |
| EXT / COMBO / 12 unités | −30 [−50 ; −11] / +6 [−35 ; 52] / −22 [−54 ; 26] |
| Anticipation | AUC 0,92, Brier 0,031 (surconfiance dans le décile haut) |

## Prochaines étapes

1. Fin de SUB32 ; analyse gelée finale.
2. Rapport (§ 9 et chiffres finaux) ; archive ; reçu en environnement neuf ; enveloppe.
