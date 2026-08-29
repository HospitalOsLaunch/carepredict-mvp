# HFWM-R0 M0 — evidence

## État inspecté

- Dépôt : `HospitalOsLaunch/carepredict-mvp`.
- Travail : branche `hfwm-r0`, HEAD `adc8d8ba59fe464692581141c901ed5813cbb5a3`, parent de baseline officielle `06914578a4e88257ecf44e7fede72a20852f443a`.
- Aucun processus P-0₀, HFWM, entraînement ou test actif observé. Aucun processus tué.
- Aucun subagent démarré. Aucun téléchargement, entraînement, V9, push, merge ou PR.
- Travail non suivi hérité préservé sans l'utiliser comme preuve : `scripts/hfwm/run_bakeoff.py`, `src/hfwm/bakeoff/`, `src/hfwm/baselines/`, `tests/hfwm/baselines/`.

## Gel P-0₀ V8

Les quatre worktrees V8 sont propres et terminaux : verifier `d00062626a85c8bdc5d0dd3b017599ecc14226d3`, closure `eff2b6aee6d6dc689d586d5a186f2ca4541722e1`, contract `aabe8a7d522589742dd95d5fffb1a78fd942122e`, candidate `5593b285a47d7f606a6885e3e25a4f751b73eb72`. Le contrat final est syntaxiquement valide. Le dernier gate complet rapporté sur le SHA final indique 166 tests verts ; le dossier committé précise que ce total est une métadonnée orchestrateur, pas une preuve de run embarquée.

V8 est figé `BLOCKERS_FOUND`, sans correction M0 : la revue hostile relève plusieurs défauts logiciels indépendants, donc aucun défaut unique et borné à corriger ici. Les principaux sont l'absence de `pytest` dans la fermeture TCB alors que les commandes normatives l'appellent, une fenêtre TOCTOU entre préflight et binding, l'absence de liaison canonique entre les octets du contrat et l'objet exécuté, une herméticité Python incomplète, des campagnes cardinalité/mutants partiellement substituées, l'absence de budgets globaux et une mesure de frame incohérente. V8 reste un harness local réutilisable ; il ne constitue pas une chaîne de preuve forte. WORM/PKI externes restent des limites d'assurance pour la revue humaine, pas un blocker de construction D0.

## Commandes et résultats observés

| Commande | Résultat |
|---|---|
| `python -m tools.contract_lint docs/gates/P00_CONTRACT.yaml` dans le candidat V8 | `VALID`, aucun finding |
| `scripts/hfwm/validate_preregistration.py` | valide ; 11 entrées ; main runs autorisés ; manifest `c9d134372d54d174a11f917ba67ebb6b0d0696f445a84f3d80333e250e9fb41d` |
| `PYTHONPATH=src pytest -p no:cacheprovider tests/p0d tests/hfwm/corpus tests/hfwm/evaluation -q` | 38 tests réussis en 0,49 s |
| Ruff ciblé P-0D/HFWM/tests | tous les contrôles réussis |
| Mypy strict ciblé | succès sur 23 fichiers |
| Construction en mémoire `build_temporal_corpus()` | 25 680 événements, 60 épisodes, 240 fenêtres, 60 corrections, 60 silences, split 42/9/9 ; hash `edc3b9e357d766d590e31bd7dec88069362a08091519482ffc122068b47045ed` |

Une première mesure exploratoire sans `PYTHONPATH=src`, puis une requête sur le mauvais attribut d'épisode, ont échoué ; la commande corrigée ci-dessus reproduit le contrat gelé. Aucun artefact n'a été écrit.

## Décision

Le slice `HFWM-R0-D0-SYNTHETIC-PIT` est défini dans `HFWM_R0_REUSE_MATRIX.md`. Les données, primitives point-in-time, splits et gates minimaux nécessaires existent et sont reproductibles. Le prochain changement est exclusivement le builder/CLI/tests du manifest D0 décrits dans la matrice.

`M0_READY_FOR_DATA_SLICE`
