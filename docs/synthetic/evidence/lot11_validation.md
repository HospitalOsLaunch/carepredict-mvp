# Lot 11 — preuves de réconciliation

Validation locale du 15 octobre 2026. Données exclusivement synthétiques ; aucune
partition de test réservée ouverte, aucun modèle entraîné.

## Périmètre mesuré

La comparaison réutilise exactement la réalisation physique du lot 10 : année
2025, 365 jours, 61 jours de chauffe, graine 41, 2 pôles et 4 unités, profil
`hospital_observation_intermittent_v1.json`, partition `development`.
Les deux reconstructions reçoivent les mêmes 14 462 messages de mouvements.
Seule la seconde reçoit les recensements observés supplémentaires.

La source physique vérifiée contient 4 925 séjours/demandes avec chauffe, dont
74 séjours admis encore ouverts à la borne finale. Ses contrôles portent sur
10 224 heures, sans violation des invariants. La physique n’a pas été relancée
pour ce rapport local ; son manifeste et ses empreintes sont conservés dans le
[rapport machine](lot11_validation.json). La commande sans `--source` régénère
le même scénario dans un nouveau répertoire, notamment en CI.

## Résultats sur les mêmes heures physiques

| Mesure | Mouvements seuls | Avec recensements |
|---|---:|---:|
| Lignes patient–heure actives | 1 808 744 | 672 009 |
| Lignes déclarées admises | 1 698 365 | 662 088 |
| Lignes déclarées en attente | 110 379 | 9 921 |
| Heures admises fantômes | 1 073 133 | 10 105 |
| Heures de présence physique sans ligne déclarée admise | 36 423 | 9 672 |
| Lignes avec conflit de lit | 1 387 489 | 3 372 |
| Lignes dont la dernière information dépasse 96 h | 1 447 595 | 0 |

Le dénominateur physique commun est de **661 655 patient–heures**. Une heure
fantôme correspond à une ligne déclarée admise pour un séjour physiquement absent.
Une heure manquée correspond à un patient physiquement présent sans ligne déclarée
admise ; il peut encore apparaître dans les demandes en attente.

Les heures fantômes diminuent de **99,06 %** et les heures de présence manquées
de **73,45 %** sur cette réalisation. Ce ne sont pas des scores prédictifs, des
estimations de généralisation ni des performances mesurées en hôpital réel.
Les retards et pertes continuent à produire des erreurs de présence.

Le pipeline réconcilié exporte 1 655 réceptions de recensement, dont 1 375 déclarées
complètes, 39 versions correctives et 11 doublons. Quatre réceptions après la borne
d’extraction restent en attente et ne sont pas exportées. Il produit 37 942 lignes
de changements d’état et 228 passages vers une absence locale. **221 séjours restent
à présence hospitalière inconnue** au dernier instant de décision ; aucune sortie
n’est créée pour les fermer.

Les 672 009 lignes actives ont toutes leur cible jointe et vérifiée. Parmi elles,
13 365 ne correspondent pas à un séjour physiquement présent : ce nombre comprend
les patients fantômes et les attentes hors hospitalisation ; il ne doit pas être
interprété comme un nombre de fantômes. Les 612 874 lignes dont la localisation
repose sur un recensement conservent cette provenance.

## Contrôles exécutés

- **366 tests du socle synthétique**, dont 33 nouveaux cas de recensement et une
  variante supplémentaire du test de cohorte avec recensement ; **54 tests
  historiques**, soit **420 tests** au total.
- Ruff : lint et format validés ; mypy strict validé sur le socle, ses tests,
  le nouveau contrat et le script annuel. Un cache mypy local corrompu a été
  contourné avec un répertoire de cache neuf, sans changer le contrôle de types.
- Chaque réception de mouvement et de recensement, chaque ligne active, chaque
  changement de réconciliation et chaque cible sont identiques entre les exports
  hors ligne et le traitement incrémental.
- Les 1 375 recensements complets sont vérifiés contre l’occupation du journal
  physique agrégé ; les recensements partiels ne dépassent pas cette occupation.
- Les 13 fichiers référencés par les deux manifestes sont vérifiés par SHA-256.
  Les empreintes du code de reconstruction et du script correspondent aux fichiers
  ayant produit le rapport.
- Les tests construits couvrent les absences partielles, la portée par unité,
  les présences sans admission, les versions hors ordre, doublons, annulations,
  corrections de complétude, transferts/départs postérieurs, contradictions,
  mutations de fuite et refus atomique d’un lot invalide.
- Le pipeline est reproductible, la source reste immuable et l’option de cohorte
  conserve les partitions et le garde-fou d’ouverture du test.

Runtime local : Python 3.12.14, NumPy 2.3.5, pandas 2.2.3, Pydantic 2.13.5.
La CI utilise Python 3.11 et recalcule ses résultats ; son statut est suivi dans
la PR et la roadmap, séparément des preuves locales.

## Reproduire et interpréter

```bash
PYTHONPATH=src python scripts/validate_synthetic_census.py \
  --source runs/synthetic/lot10/annual/truth \
  --output runs/synthetic/lot11/annual
```

Le répertoire de sortie doit être nouveau. Omettre `--source` pour régénérer la
réalisation physique avant la comparaison. Le rapport machine contient les
manifestes, versions, paramètres, empreintes et compteurs détaillés.

La complétude des recensements est honnête par construction : les omissions
non signalées dans une liste dite complète ne sont pas encore simulées. Les
demandes non admises n’appartiennent pas au périmètre d’un recensement de lits.
Un consommateur doit conserver les états inconnus du journal, sans assimiler
leur absence des lignes actives à une sortie. Cette année ne suffit donc pas
à qualifier un corpus pour le préentraînement ou un transfert vers le réel.

La phase 0 et la porte SYN restent ouvertes. Prochain lot proposé : charge
observée, sorties prévisionnelles et besoins d’aval, avec provenance et censure.
