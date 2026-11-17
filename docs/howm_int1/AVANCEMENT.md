# HOWM-INT-1 — tableau d'avancement (mis à jour en continu)

**Décision** n° 9. Mandat : `docs/howm2/inputs/MANDAT_HOWM2_DECISION_9_HOWM_INT_1.md`.

**Protocole** : `docs/howm_int1/PROTOCOLE_INT1.md`, consigné avec son plan réalisable (note `int1_protocol`).

**Registre :** `evidence/howm_int1/LEDGER_INT1.jsonl`.

- Runner : `scripts/howm_int1_run.py` (verrou fcntl depuis l'incident #38).
- Statut : `python3 scripts/howm_int1_run.py --status`.
- 540 s par commande ; lots `INT.L0`, `INT.DATA`, `INT.LEARN`, `INT.EVAL`, `INT.REST`, `INT.RESERVE`.

**Chemins.** Venv, corpus, runs et évaluation sont dans le scratchpad :
`/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad/{venv_howm,int1_corpus,int1_runs,int1_eval}`.

**Enchaînements reprenables.**

- `scripts/int1/chain.py` relance les commandes de moins de 540 s jusqu'à l'arrêt du run ou à la cible de corpus.
- Échéance propre à 6 600 s, à cause des créneaux d'arrière-plan de 2 h. Relancer la même commande pour reprendre.
- Scripts : `scratchpad/chain_data.sh` (VAL puis palier 2) et `scratchpad/chain_learn_t1.sh` (W-S puis W-M, palier 1, 3 graines).

**Aucun push** (consigne de l'utilisateur), même si un hook automatique le demande.

## Construit, appris, évalué, incertain

| Élément | État | Preuve |
|---|---|---|
| Monde N unités (M1–M8), engagements, budgets, boucle fermée, vue publique propre | construit, testé (I1–I9, 21 tests) | #11, #17 |
| Qualification des régimes, puis révision (intensité k = n/2, action d'aval) | fait avant toute comparaison | `QUALIFICATION_DEV.json` (#13, #19) |
| Vue publique en graphe, règles (historique, robuste, exploratoire) | construit | `features.py`, `policies.py` |
| Corpus palier 1 (`INT_TRAIN` 0–999), VAL (300, K = 4) | palier 1 fait ; VAL en cours | `int1_corpus/` |
| Corpus palier 2 (1 000–9 999) | en cours (`chain_data.sh`) | — |
| W `GraphWM` S (317 460 paramètres) et M (1 899 540) | construit ; palier 1 en apprentissage | `int1_runs/W_t1_{S,M}_s{0,1,2}` |
| D (Ridge, HGB, DSet) | code prêt ; à lancer | `train_d.py` |
| Planificateur commun ; F et R1 adaptés (2 unités) | construit, essai de fumée fait | `planners.py` (#26, #28) |
| Campagne finale et analyse | code prêt (à geler) | `eval_campaign.py`, `analyse.py` |
| Incident : course d'écriture sur le registre | réparé, archivé, verrou ajouté | `LEDGER_INT1.broken_at_line38.jsonl`, note `incident` |

## Prochaines étapes

1. Palier 2 : empaquetage memmap ; continuation S et M ; D au palier 2.
2. D au palier 1 (Ridge, HGB, DSet) ; ablations (sans historique, sans messages).
3. Diagnostic SF1 ; propagation (DEV).
4. Panel VAL en boucle fermée : choix de B\* et de la taille de W.
5. Tests complémentaires ; gel `FREEZE_INT1.json`.
6. Campagne finale (MAIN, SUB32, EXT, COMBO, SIZE12) ; analyse.
7. Démonstration rejouable ; rapport ; archive ; reçu neuf ; enveloppe.
