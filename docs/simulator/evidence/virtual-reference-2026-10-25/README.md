# Référence exécutée — 25 octobre 2026

30 paires, dix graines fixées 0–9 par établissement, six heures, politique A1 d’acceptation.
Tous les épisodes sont terminés, sans sélection a posteriori des résultats.
Le manifeste identifie les sources et versions suivies ; chaque paire contient les journaux,
primitives, propositions et commandes. `report.json` conserve les mesures par réplication,
la dispersion et les dégradations. Ces sorties décrivent uniquement les hypothèses fictives.

Commande depuis la racine :

```bash
PYTHONPATH=src:. .venv-demo/bin/python -m hospitalos.virtual.campaign --output virtual-campaigns/reference
```

Le répertoire livré est une preuve figée. Rejouer vers un nouveau dossier ; une version
Python différente modifie le manifeste et doit rester explicite. Les métriques physiques
restent déterministes à code, configuration et pile numérique identiques.
