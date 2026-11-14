# Point de reprise

État : P0–P4 livrés, corrigés après trois audits indépendants (P2/P3bis ; v5 : V4-R01/R02/R03,
V4-D01 ; v6 : V5-R01) : **`PARTIAL_WITH_CHECKPOINT`**. P5 et P6 **fermés**. Portes ouvertes :
ré-audit indépendant de la v6, niveau exact Python 3.11.9 (3.11.18 : suite verte), rejeu
navigateur indépendant du cockpit.

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
4. P5 (qualification expérimentale bornée) : soumettre protocole, budget, graines, règle d'arrêt.
   Aucun budget AJ-H antérieur n'est réutilisable.

## Hors de ce projet

Reprise de A_detached (authentifié à 2000, final 6000 non attesté — pas un échec scientifique),
lots B/C, chargement de poids : mandat distinct, vérification préalable de l'absence de doublon distant.
