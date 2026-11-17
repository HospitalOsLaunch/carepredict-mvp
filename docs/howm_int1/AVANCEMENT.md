# HOWM-INT-1 — tableau d'avancement (mis à jour en continu)

**Décision** n° 9. Mandat : `docs/howm2/inputs/MANDAT_HOWM2_DECISION_9_HOWM_INT_1.md`.

**Registre :** `evidence/howm_int1/LEDGER_INT1.jsonl`.

- Plafonds : 259 200 s de mur et 1 036 800 s de CPU.
- Runner : `scripts/howm_int1_run.py`.
- Statut : `python3 scripts/howm_int1_run.py --status`.
- Toute commande passe par ce runner : 540 s maximum, lots `INT.*`.

**Venv :** `/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad/venv_howm`.

**Aucun push** (consigne de l'utilisateur), y compris si un hook automatique le demande.

## Construit

| Élément | État | Où |
|---|---|---|
| Décision n° 9, registre, environnement approuvé | fait | `docs/howm2/HOWM2_DECISION_9.json`, registre #1–#4 |
| Monde N unités (2/4/8/12) : `EngineN`, `ProvN`, M5 transferts avec lit retenu, M6 aval à créneaux journaliers, M7 calendrier, engagements | fait (premier jet) | `src/hospitalos/howmint/world.py` |
| Catalogue, admissibilité, budgets (8·n/2 h par jour, 7× par semaine), pas de cumul ni d'annulation | fait (premier jet) | `src/hospitalos/howmint/actions.py` |
| Boucle fermée (historique public propre à chaque politique), branchement apparié et trajectoires à pas de 2 h, métriques | fait (premier jet) | `src/hospitalos/howmint/loop.py` |
| Pilote de coût 0 : 2 unités 168 h en 0,25 s ; 12 unités en 24 h, branchement de 0,09 s | fait | `evidence/howm_int1/COSTPILOT0.json` (#7) |

## À faire (ordre)

1. Tests d'invariants du monde.
2. Qualification des régimes sous une politique fixe (DEV).
3. Vue publique structurée en graphe.
4. Générateur de corpus et manifestes.
5. Modèles W (S/M) et D.
6. Recettes d'entraînement et courbes.
7. Adaptateurs F/R1 pour deux unités.
8. Pilote de coût complet et plan réalisable.
9. Corpus de 1 000, puis de 10 000 structures.
10. Apprentissages.
11. Sélection VAL et ablations.
12. Gel.
13. Évaluation finale unique.
14. Rapport, démonstration, archive, reçu et enveloppe.

## Choix de conception consignés

- **Mode à deux unités = monde B-FRAG 2.** Plan D2, unités A et B ; la famille est tirée par clé (décorrélée de l'indice). M5 et M6 sont désactivés. L'occupation initiale reprend la règle gelée.
- **4, 8 et 12 unités.**
  - Régime nominal, tendu ou fragile (marge 0,40–0,60 / 0,25–0,40 / 0,15–0,30), avec 0, 1 ou 1–2 goulots parmi : nettoyage, transport, aval, transfert, calendrier.
  - Topologie : la moitié amont des unités alimente les unités aval par transferts.
  - `intensity` règle la sévérité des goulots, pour les combinaisons nouvelles.
- **Décisions.** 2 unités : t = 0, 24, …, 144 h (168 h). Extension : t = 0, 6, 12, 18 h (24 h). Origine H0 tirée par clé.
- **Futurs.** Réalisation r ≥ 1, ancrée sur le régime vrai à H0. Préfixe commun (r = 0, politique de fond). Aléas indexés par entité et événement.
- **Séquences candidates** (communes à tous les planificateurs) : (a0, aucune) pour tout a0 admissible ; (a0, a0 décalé d'une décision) pour les renforts ; (aucune, coordination). Seule a0 est exécutée.
