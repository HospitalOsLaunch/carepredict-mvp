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
4. P5 (qualification expérimentale bornée) : protocole proposé `P5_PROTOCOL.md` (P5-PROTO-1) et
   `P5_PROTOCOL_PARAMS.json`, **non exécuté, non autorisé**. Budget distinct proposé : 1200 s,
   30 s par commande, 0 €. scikit-learn requis pour P5b (installation à autoriser).
   Aucun budget P0–P4 ni AJ-H antérieur n'est réutilisable.

## Hors de ce projet

Reprise de A_detached (authentifié à 2000, final 6000 non attesté — pas un échec scientifique),
lots B/C, chargement de poids : mandat distinct, vérification préalable de l'absence de doublon distant.
