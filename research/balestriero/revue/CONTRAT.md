# Comparatif HospitalOS, contre-revue prospective

## Deux horloges

L’expérience rétrospective compare des actions dans un même hôpital, au même instant de décision, avec le même état initial et le même ruban d’événements exogènes. La trajectoire factuelle observée à l’horizon évalué peut être utilisée pour corriger rétrospectivement la prévision. Une décision prospective ne peut lire cette trajectoire. Elle utilise seulement les variables publiées à la date d’engagement, les plans candidats, les contraintes et les poids scellés. À chaque horizon, l’ancre partielle n’utilise que les composantes alors publiées.

## Identités et contrôles négatifs

Pour un prédicteur gelé donnant `m(a)`, une action factuelle `f`, une observation `Y(f)` et une alternative `a`, l’estimateur après observation est `Y(f) + m(a) − m(f)` dans les coordonnées retenues. Quand le canal factuel n’est pas publié, le résidu de ce canal vaut zéro. Les quatre contrôles distinguent la prédiction `m(a)`, la persistance de l’observation factuelle, la réutilisation d’un résidu d’un autre événement et la réutilisation correcte. Une comparaison utilisant des chocs indépendants est une expérience de rupture de couplage. Elle ne fournit aucune vérité contrefactuelle individuelle.

L’action factuelle est exclue des mesures de performance des alternatives. La réinjecter au même horizon vérifie l’identité sur les canaux publiés. En l’absence d’action effective avant sa prise de poste, la cible de contraste est nulle. Une différence entre des prévisions d’alternatives survit exactement à l’addition du même résidu. Un gain de précision du niveau absolu ou d’un taux de réussite à une cible non linéaire peut donc coexister avec une erreur d’effet et un ordre linéaire inchangés. Toute projection de l’estimation sur un domaine admissible est déclarée séparément, car elle peut rompre cette identité. Une MAE d’effet est évaluée contre le contraste réel issu du même état et du même événement. Le modèle « effet nul » est un comparateur obligatoire pour situer l’apport de l’action. Les cas effectivement non nuls sont comptés et isolés dans une analyse secondaire.

La comparaison présente les erreurs dans les unités propres aux cibles. L’erreur absolue sur un résultat ne doit pas être appelée erreur de politique. L’effet d’une action modifiant plusieurs unités est contrôlé unité par unité, avant agrégation. Les graines d’entraînement, modalités d’information, horizons et actions d’un même établissement ne créent pas de réplications indépendantes. Lorsque les résultats le permettent, les incertitudes sont obtenues en rééchantillonnant les hôpitaux entiers sur des différences appariées ; les dénominateurs faibles sont explicités.

## Expérience H-JEPA prospective

Le candidat hiérarchique et la référence plate doivent disposer du même menu, du même budget de requêtes d’évaluation, de la même vue publiée et des mêmes conditions sur les unités de départ. Les prévisions et choix sont archivés avant l’ouverture des issues de toutes les alternatives. Aucun changement d’un résultat futur, d’un rapport non publié ou d’un identifiant destiné à l’audit ne doit changer ce que le modèle savait au moment d’agir. Le nom de l’architecture est qualifié selon les éléments réellement implémentés, notamment représentations aux échelles distinctes, objectifs intermédiaires, gradient de la cible, planification descendante et recours éventuel à la supervision sur coûts appariés.

Les audits distinguent le gain moyen de transfert, les gardes de +1 % sur l’attente de lit et les minutes IDE/AS pour chaque unité physique, les violations de budget/donneur/disponibilité et les actions réellement utilisables. Un maintien partout à égalité avec l’ordonnancement habituel fournit un contrôle négatif. Les effets du nouveau banc restent propres au simulateur, aux options testées et à l’information publiée.

## Provenance scientifique

Les trois poids du prédicteur JEPA de la livraison 28 jours, graines 19, 37 et 71, ont déjà vu des différences de conséquences entre des plans appariés pendant leur ajustement. L’expérience réutilise les fichiers gelés et peut mesurer la valeur de l’ancrage à modèle identique. Cette branche n’est pas une démonstration que la seule supervision factuelle permet d’apprendre les actions hospitalières. La physique structurée, les seuils de rappel et les changements de créneau sont documentés séparément.

Références originales. [Contrefactuels et transport de résidu, Balestriero, LeCun et Varaku](https://arxiv.org/abs/2611.24778). [H-JEPA et planification hiérarchique, Zhang et al.](https://arxiv.org/abs/2610.06805).
