# Lot 02 — observations telles que connues et référence à 24 h

SOC-002 raccorde les états horaires du générateur multi-pôles à une couche
d'observation versionnée, un rejeu aux instants de décision et une prévision de
persistance à 24 h. Les cibles futures restent dans un fichier séparé. Ce lot
porte sur les états d'unité et leurs agrégats ; les trajectoires individuelles et
les notes ne sont pas encore raccordées à ce nouveau pipeline.

## Exécuter

Depuis la racine du dépôt, avec les dépendances légères du [socle](README.md) :

```bash
# Seulement si le run de vérité n'existe pas encore.
PYTHONPATH=src python -m hospitalos.synthetic \
  --config configs/synthetic/hospital_two_poles.json \
  --output runs/synthetic/annual

PYTHONPATH=src python -m hospitalos.synthetic.learning \
  --source runs/synthetic/annual \
  --output runs/synthetic/asof-annual
```

Le deuxième appel vérifie les empreintes des fichiers d'entrée, conserve la vérité
en lecture seule et crée une nouvelle sortie complète. Il ne modifie pas la physique
et ne réexécute pas le simulateur. Un répertoire existant n'est jamais écrasé. Les
horloges restent en UTC+1 fixe, sans changement d'heure, comme dans le socle.

## Séparation des fichiers et responsabilités

| Sortie | Rôle |
|---|---|
| `observed/unit_states.jsonl.gz` | Livraisons des états d'unité : quatre horloges, versions, corrections et doublons |
| `features/asof.jsonl.gz` | Informations disponibles à chaque décision, provenance et masques de manque/ancienneté |
| `targets/occupancy_load_queue_24h.csv` | Vérité à la cible, avec censure en fin de période ; réservée à l'évaluation ou à la supervision |
| `evaluation/persistence_24h.csv` | Prévisions à 24 h calculées uniquement à partir des variables disponibles |
| `evaluation/metrics.json` | MAE, RMSE, biais et couverture par entité et variable |
| `manifest.json` | Empreintes du code, des sorties et du manifeste source, versions d'exécution et réglages |

Le calcul des prévisions précède la lecture des cibles. `replay()` ne reçoit aucune
vérité et `predict()` ne reçoit aucun label. Les schémas refusent les colonnes
inconnues ; les 17 valeurs admises sont déclarées dans `ObservedState`.
Les identifiants, la partition et la provenance servent aux jointures et à l'audit,
pas à devenir des variables permettant au modèle de mémoriser l'établissement.

## Horloges et convention de fin d'heure

Un état du lot 01 étiqueté `h` décrit la **fin** de l'intervalle `[h, h+1)`.
Il ne peut donc commencer à être observé qu'à `h+1`. Les délais sont ajoutés à cet
instant, puis chaque livraison impose :

`event_h ≤ recorded_h ≤ ingested_h ≤ available_h`.

Une décision à la frontière `t` n'utilise que les livraisons dont `available_h ≤ t`.
La cible à 24 h est l'état à la frontière `t+24`, donc la ligne de vérité `t+23`.
Exemple : une décision au début du 1er janvier cible la fin de sa 24e heure,
ligne de vérité `h=23`. C'est cette convention qui évite une avance ou un retard
silencieux d'une heure. Les dernières 23 décisions horaires sont censurées, car
leur cible dépasse la dernière frontière disponible.

La chauffe fournit des observations à horloges négatives pour initialiser le rejeu.
Les livraisons disponibles après la fin de l'extraction sont exclues. Un horizon
de prévision appartient au **futur de la décision**, pas au futur d'un vieux relevé.

## Observation et rejeu

L'adaptateur réutilise les mécanismes d'observation v0.4.1 sur les seuls événements
`ETAT_UNITE` : manque, délais de saisie et d'ingestion, panne SI, corrections,
doublons, bruit sur la charge et documentation partielle des attentes.
Les tirages sont indépendants de la physique. Ce profil est nommé et versionné ;
les livraisons ne sont pas une reproduction octet pour octet de l'ancien corpus,
qui observait aussi d'autres événements avec sa propre séquence de tirages.

Le rejeu applique les règles suivantes :

- Une version corrigée devient visible à sa propre disponibilité, sans réécrire
  les états tels qu'ils étaient connus auparavant.
- Une correction portant sur un ancien état ne remplace pas un état plus récent.
- Un doublon identique n'a aucun effet et ne rafraîchit pas l'ancienneté. Un doublon
  divergent, une identité d'événement modifiée ou un mauvais hôpital provoque un échec.
- Une unité encore jamais observée reste manquante. Un agrégat ne reçoit aucune
  valeur si un de ses membres manque ; les unités manquantes ne valent pas zéro.
- L'ancienneté est calculée depuis l'événement, pas depuis sa dernière retransmission.
  Au-delà de six heures, la référence s'abstient. Les valeurs historiques et leur
  masque restent présents. Le seuil se règle avec `--stale-after-hours` et est tracé.
- Un pôle ou l'hôpital somme les derniers états disponibles de ses unités. Ce sont
  des relevés éventuellement asynchrones, pas un accès à un état global de vérité.

Les erreurs d'observation peuvent rendre les comptes de lits incohérents. Le rejeu
ne les « répare » pas en consultant la vérité. Une livraison d'état demeure un
relevé agrégé du simulateur : ce lot ne reconstruit pas encore l'occupation à partir
des messages d'admission, sortie et transfert d'un SI réel.

## Référence et métriques

La persistance prédit à 24 h la dernière valeur connue pour trois variables :
lits occupés, patients en attente aux urgences et minutes de soins **par heure**.
Elle n'est pas une prévision du cumul de charge sur les prochaines 24 heures.
Elle ne possède aucun poids appris et ne consulte pas les prévisions du staff.

Le rapport donne, séparément pour chaque unité, pôle et hôpital :

- `mae` : erreur absolue moyenne ; `rmse` : racine de l'erreur quadratique moyenne ;
  `bias` : moyenne de prévision moins vérité.
- `eligible` : décisions dont la cible existe ; `n_scored` : prévisions effectivement
  évaluées ; `coverage = n_scored / eligible`.
- `censored`, `missing`, `stale` : raisons distinctes d'exclusion. Les abstentions
  restent dans le dénominateur de couverture mais pas dans les erreurs.

Les MAE des entités sont moyennées à poids égaux **au sein de chaque niveau** pour
la synthèse. Les niveaux ne sont jamais mélangés dans une seule métrique.

Le run d'exemple appartient à `development`. Il n'entraîne et ne sélectionne aucun
modèle, ne découpe pas artificiellement un même hôpital entre apprentissage et test,
et ne tient pas lieu de test final. Le registre des mondes et les mécanismes réservés
restent le lot suivant. Les résultats n'ont pas d'intervalle de confiance : une seule
année d'un seul hôpital synthétique n'établit pas une généralisation ou un transfert.

## Preuves et suite

Les tests couvrent le décalage de fin d'heure, la censure, les horloges invalides,
les versions disponibles, les corrections tardives, les doublons, les agrégats
incomplets, les observations anciennes et la mutation de provenance future. L'ajout
d'une livraison future ne change ni les variables ni les prévisions du passé.
Modifier les labels change les scores mais pas les prévisions.

```bash
PYTHONPATH=src python -m pytest -q tests/synthetic
```

La CI rejoue aussi la génération annuelle et cette évaluation, puis conserve les
manifestes et les métriques. Les [preuves locales](evidence/lot02_validation.md)
rapportent l'exécution effectivement observée.

**Après SOC-002 :** GEN-003, registre de cohortes et séparation des établissements,
structures et familles de mécanismes. Les références saisonnières et apprises puis
leur évaluation comparative viendront sur des ensembles explicitement réservés.
