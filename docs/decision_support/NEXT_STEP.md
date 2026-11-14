# Point de reprise

État : P0–P4 livrés puis corrigés après audit (P2/P3bis, P4bis) : **`PARTIAL_WITH_CHECKPOINT`**.
P5 et P6 **fermés** (mandat et budget distincts requis). Portes ouvertes : niveau exact
Python 3.11.9 (3.11.18 testé : 153/153 hors test_p1 ; `jsonschema` à autoriser pour ses 10 tests)
et ré-audit indépendant des correctifs.
Branche locale : `claude/hospitalos-auto-first-p0-p4-s2dywn`, base `a5e737e` (`claude/cockpit-web`).
Rien n'a été poussé.

## Reprise exacte

```bash
# depuis le paquet : vérifie les SHA-256, restaure la branche dans un dossier neuf, rejoue tests + export
sh restore.sh --verify-only                   # deux manifestes + registre terminal
sh restore.sh /chemin/vers/dossier_neuf
# depuis un clone existant à a5e737e : appliquer les patchs
git checkout -b claude/hospitalos-auto-first-p0-p4-s2dywn a5e737eec2cfdf0f52a68f41b523f928181c03e6
git am patches/*.patch
python3 scripts/ds_budget_run.py --status     # retrouve les compteurs, jamais remis à zéro
```

Le registre `evidence/decision_support/BUDGET_LEDGER.jsonl` est chaîné : toute modification
d'un enregistrement bloque le compteur (aucun contournement par remise à zéro).

## Prochaines étapes possibles (chacune sur accord distinct)

1. (Fait en P4b : route React « Plan 24 h », 71/71 Vitest, e2e 17/17.) Éventuellement découper le
   bundle (données de démonstration en import dynamique) pour lever l'avertissement de taille.
2. Exécuter `mypy --strict` sur `hospitalos.decision_support` et corriger.
3. Revue métier des paramètres synthétiques (`UNIT_PROFILE.json`) — aucun entretien n'a eu lieu.
4. P5 (qualification expérimentale bornée) : soumettre protocole, budget, graines, règle d'arrêt.
   Aucun budget AJ-H antérieur n'est réutilisable.

## Hors de ce projet

Reprise de A_detached (authentifié à 2000, final 6000 non attesté — pas un échec scientifique),
lots B/C, chargement de poids : mandat distinct, vérification préalable de l'absence de doublon distant.
