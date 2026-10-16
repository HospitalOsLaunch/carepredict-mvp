# Preuves locales — lot 14

Exécution du 15 octobre 2026. Deux structures de développement, une graine par
structure, une année chacune. Aucun test réservé ouvert. Les sorties vérifient
les empreintes de leur source et réconcilient indépendamment chaque unité-heure.

| Mesure | Référence deux pôles | Périmètre médical GHT-600 |
|---|---:|---:|
| Unités / pôles | 4 / 2 | 9 / 3 |
| Admissions dans l’année | 4199 | 11918 |
| Sorties dans l’année | 4192 | 11903 |
| Admissions antérieures sorties dans l’année | 67 | 219 |
| Admis dans l’année encore présents à la fin | 74 | 234 |
| DMS des sorties, jours | 6.580 | 6.836 |
| Heures-lits occupées | 661662 | 1953167 |
| Heures-lits ouvertes | 891982 | 2145829 |
| Occupation pondérée par la capacité ouverte | 74.18 % | 91.02 % |
| Heures-patients en file d’urgence | 6542 | 45199 |
| Heures après première disponibilité médicale | 173781 | 519180 |
| Sorties sans événement de disponibilité médicale | 490 | 1510 |

Les 250 lits standard du profil GHT-600 incluent 60 lits de CSG ; les renforts
peuvent modifier la capacité physique. Les 600 lits du nom sont un contexte, pas
la capacité simulée. Les 350 autres lits ne sont pas représentés activement.

La présence après disponibilité médicale ne prouve pas un blocage causé par
l’aval. Le temps de coordination et l’absentéisme brut ne sont pas mesurables
dans ces exports. Les délais terminés sont conditionnels à la sortie/admission ;
les séjours et demandes encore ouverts figurent séparément dans le JSON.

## Vérifications

- 24 nouveaux tests de mesure ; 457 tests du socle synthétique réussis au total.
- 54 tests historiques de régression et mutation réussis, soit 511 tests locaux.
- Ruff, formatage et mypy strict passent sur les périmètres de la CI concernés.
- Les invariants du générateur passent sur les 10 224 heures de chaque source,
  chauffe de 61 jours comprise ; les mesures portent sur les 8 760 heures de l’année.
- Occupation et files réconciliées unité par unité et heure par heure sur les deux années.
- Empreintes des entrées, de la mesure, des références et des rapports dans le JSON.

## Reproduction

Utiliser la CLI décrite dans [lot14.md](../lot14.md) pour chaque configuration.
La référence réutilise le fichier du lot 13 : ce lot ne réécrit pas son historique.
Les chemins des sources et rapports figurent dans le JSON ; les grandes sorties
de simulation restent hors Git. Les tests utilisent Python 3.11.9 et les rapports
annuels Python 3.12.14, avec NumPy 2.3.5. Les nombres sont descriptifs : aucun seuil
de réalisme hospitalier ni résultat d’entraînement n’est déclaré atteint.
