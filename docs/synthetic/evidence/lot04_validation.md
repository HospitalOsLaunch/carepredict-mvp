# Validation du lot 04 — mécanismes opérationnels

Exécution locale du 15 octobre 2026. Données exclusivement synthétiques ;
aucun modèle ajusté, aucune trajectoire du test réservé générée.

## Contrôles logiciels

- **129 tests du socle passent**, dont 33 ajoutés dans ce lot.
- **54 tests historiques passent**, y compris les mutations de fuite et de fusion.
- Lint du dépôt, format de 17 fichiers et typage strict de 16 fichiers réussis.
- Les états, événements, décisions et tâches du mode historique sont identiques
  à ceux du moteur publié au commit `3e9f765`, sur 7 jours après 14 jours de chauffe.
- L'identité de la configuration v041 annuelle du lot 01 est préservée.
- Cas contrôlé : avec deux créneaux d'imagerie et trois demandes, dont les deux
  premières du même pôle, la file commune sert ces deux demandes ; la réservation
  locale sert une demande de chaque pôle, à capacité totale inchangée.
- Les routes dirigées, la priorité locale, le délai, les budgets entiers, les poids
  invalides et le dépassement volontaire d'un budget sont vérifiés.
- Comparaison d'une configuration avec elle-même : cinq effets nuls aux trois niveaux.
  Un changement d'aléas ou un horizon débordant est refusé.
- Le contrat de réservation par mécanisme accepte une structure commune mais refuse
  une famille partagée entre partitions.
- Les commandes ajoutées à la CI sont exécutées localement : génération locale,
  registre de mécanismes et comparaison à 72 h.
- Les deux CI du lot 03 ont réussi au commit parent `3e9f765`. Les CI de cette PR
  sont distinctes et leur état se lit sur GitHub.

## Trois réalisations annuelles de développement

Même hôpital, 2 pôles, 4 unités, 102 lits standard, même graine `20261015`,
même année 2025, mêmes 61 jours de chauffe et même capacité totale horaire.
Chaque organisation est appliquée dès le début de sa propre chauffe.

| Organisation | Lignes unité-heure | Événements, chauffe incluse | Lignes de groupes de ressources |
|---|---:|---:|---:|
| Partagée v041 | 35 040 | 147 592 | 0 — export global historique |
| Locale | 35 040 | 146 143 | 70 080 |
| Mixte | 35 040 | 147 290 | 52 560 |

Au total : **30 672 heures d'hôpital contrôlées**, dont 26 280 enregistrées ;
183 960 lignes de variables, autant de cibles avec censures, et 123 699 livraisons
d'observation. Aucune violation des lits, des flux ou des budgets des groupes.
Les empreintes des **63 fichiers** référencés par les manifestes annuels,
contrefactuels et du registre ont été vérifiées après l'exécution.

L'attente annuelle aux urgences vaut respectivement 6 609, 7 589 et 7 316
patients-heures. Cela montre que les mécanismes modifient les trajectoires.
Ce n'est pas le même estimand que les changements à 72 h ci-dessous : ici,
chaque organisation a aussi modifié toute la chauffe et l'histoire antérieure.
Une seule graine ne permet pas de conclure qu'une organisation est meilleure.

## Huit changements à 72 h sur quatre dates fixées

Chaque comparaison repart de l'état v041 à 9 h les jours 0, 90, 180 et 270 de
l'année enregistrée. La variante est appliquée sur les 72 heures suivantes,
la politique habituelle continuant dans les deux branches. Les tableaux d'aléas
sont partagés et leur empreinte est vérifiée après chaque branche.

| Heure de décision | Variante | Delta lits-heures occupés | Delta minutes non couvertes | Delta transferts internes |
|---|---|---:|---:|---:|
| 9 | Locale | +1 | 0 | 0 |
| 9 | Mixte | +1 | 0 | 0 |
| 2 169 | Locale | 0 | −185,88 | −1 |
| 2 169 | Mixte | 0 | +17,47 | 0 |
| 4 329 | Locale | +22 | −74,44 | −2 |
| 4 329 | Mixte | +22 | −5,14 | 0 |
| 6 489 | Locale | 0 | 0 | 0 |
| 6 489 | Mixte | 0 | 0 | 0 |

Dans ces huit cas, le delta d'attente aux urgences et celui des orientations externes
sont **nuls**. Les résultats complets par unité et pôle sont conservés, sans
rechercher a posteriori des dates donnant un effet favorable. Les 16 branches
représentent 1 152 heures contrôlées, sans violation.

Un résultat nul ici n'annule pas les différences annuelles ; il décrit l'effet
local de l'intervention, depuis ces états, sous ces aléas, pendant cet horizon.

## Preuves et portée

- [lot04_results.json](lot04_results.json) : mesures annuelles, références à 24 h,
  comparaisons détaillées aux trois niveaux, contrôles et empreintes.
- [lot04_v041_manifest.json](lot04_v041_manifest.json),
  [lot04_local_v1_manifest.json](lot04_local_v1_manifest.json),
  [lot04_hybrid_v1_manifest.json](lot04_hybrid_v1_manifest.json) : manifestes annuels.
- [lot04_mechanism_registry.json](lot04_mechanism_registry.json) et
  [son manifeste](lot04_mechanism_registry_manifest.json) : 12 configurations
  réservées, dont 4 hybrid_v1 en test ; aucun de ces mondes de test matérialisé.

Les trois familles sont des variantes d'organisation des ressources et du
routage, avec la même base clinique. La diversité des sorties, des arrivées,
des absences et des politiques comportementales reste à développer. Les essais
techniques de développement, y compris mixtes, ne doivent pas devenir des
entrées d'apprentissage/sélection d'un modèle évalué sur la famille mixte réservée.

La reproductibilité est testée sur les exports contrefactuels et sur les cohortes
courtes des lots précédents. Les trois simulations annuelles sont exécutées une
fois chacune. Aucun résultat n'est une validation clinique, un gain réel mesuré
ou une preuve de généralisation du world model.
