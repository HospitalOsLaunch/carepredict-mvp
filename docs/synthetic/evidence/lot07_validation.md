# Lot 07 — vérifications et diagnostics annuels

Exécution locale du 15 octobre 2026, exclusivement synthétique. Sept réalisations de développement de 365 jours après 61 jours de chauffe, 2 pôles et 4 unités, graine 41. Aucun modèle entraîné ni test final consulté.

- 219 tests du socle passent, dont 34 nouveaux ; 54 tests historiques passent (273 au total).
- Ruff global, format (25 fichiers) et mypy strict (24 fichiers) passent.
- 71 568 heures vérifiées ; zéro violation de lits, patients, conservation stock–flux ou transferts.
- 42 empreintes de fichiers annuels vérifiées ; les sources du rapport correspondent au code livré.
- Trois registres figés, chacun avec 12 mondes dont 4 de test. Aucun de leurs 36 mondes n’est matérialisé par cette campagne ; les sept simulations ci-dessous sont des diagnostics séparés.

| Variante | Lits occupés moyens | Patients en attente urgences moyens | Soignants présents moyens | Sorties annuelles |
|---|---:|---:|---:|---:|
| reference | 75.53 | 0.747 | 19.50 | 4192 |
| shared_bursts_v1 | 76.53 | 1.087 | 19.44 | 4184 |
| appointments_v1 | 80.36 | 0.865 | 19.53 | 4266 |
| daily_rounds_v1 | 80.91 | 0.939 | 19.53 | 4143 |
| rolling_v1 | 72.36 | 0.714 | 19.46 | 4200 |
| persistent_absence_v1 | 75.54 | 0.746 | 19.11 | 4193 |
| shared_float_v1 | 75.53 | 0.746 | 19.68 | 4194 |

Ces chiffres vérifient que les mécanismes s’exécutent et modifient les dynamiques. Une seule graine par variante, sans intervalle d’incertitude, ne permet aucun classement robuste ou conclusion causale. Les arrivées alternatives changent aussi la population et les tirages ultérieurs de politique. Les soignants présents incluent les renforts décidés par la politique historique.

Les variantes de test sont inspectées sur des fixtures et diagnostics de développement pour valider leur implémentation. Leur réservation signifie qu’elles sont absentes de l’apprentissage dans leur plan ; ce n’est pas un mécanisme conçu à l’aveugle par un évaluateur indépendant. Les trajectoires des identités de test restent non générées.

Reproduction : `PYTHONPATH=src python scripts/validate_synthetic_dynamics.py --output runs/synthetic/lot07/diagnostics` dans un répertoire de sortie neuf. Les données volumineuses sont régénérables ; [rapport et empreintes](lot07_validation.json) et configurations sont versionnés.

Limites : hypothèses d’ingénierie non calibrées, clinique héritée, pas de ruptures datées, pas de modèle appris, pas de preuve G1–G4. Phase 0 toujours ouverte.
