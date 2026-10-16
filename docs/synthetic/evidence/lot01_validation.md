# Vérification locale — lot 01

Environnement : Python 3.12.14, NumPy 2.3.5, pandas 2.2.3, Pydantic 2.13.5.
Les commandes suivantes ont été exécutées depuis la racine du dépôt.

| Commande | Résultat |
|---|---|
| `python -m ruff check .` | Succès, dépôt entier |
| `python -m ruff format --check src/hospitalos/synthetic tests/synthetic` | 6 fichiers conformes, import historique exclu |
| `python -m mypy --strict src/hospitalos/synthetic/config.py src/hospitalos/synthetic/engine.py src/hospitalos/synthetic/generate.py src/hospitalos/synthetic/__main__.py tests/synthetic` | Succès, 5 fichiers |
| `PYTHONPATH=src python -m pytest -q tests/synthetic` | 31 tests passent |
| `PYTHONPATH=src python -m hospitalos.synthetic.v041.tests` | 54 tests passent, dont les mutations de fuite et de fusion |
| `PYTHONPATH=src python -m hospitalos.synthetic --config configs/synthetic/hospital_two_poles.json --output runs/synthetic/annual-validation` | Succès, manifeste ci-joint |

Le run annuel contient 2 pôles, 4 unités, 8 760 heures enregistrées,
35 040 lignes unité-heure et 146 347 événements en incluant la chauffe.
Les 10 224 heures simulées (426 jours avec la chauffe) passent les contrôles :
aucune double affectation, incompatibilité de lit, divergence de registre,
violation de partition des lits ou rupture de conservation des flux.

[Manifeste du run annuel](lot01_annual_manifest.json) : empreintes de la configuration,
du code exécuté et des fichiers produits. Les fichiers de données volumineux ne sont
pas versionnés ; ils sont régénérables par la commande ci-dessus. La nouvelle CI
rejoue ses propres tests sous Python 3.11 et conserve son manifeste comme artefact.
Ce relevé local ne préjuge pas de l'état des jobs GitHub ni de la suite applicative
complète, qui n'a pas été exécutée localement pour ce lot isolé.

Ces vérifications établissent les contrats du logiciel et un cas de concurrence
entre pôles dans le simulateur. Elles ne mesurent ni l'erreur d'un modèle appris,
ni le réalisme clinique, ni la généralisation à des mécanismes inconnus.
