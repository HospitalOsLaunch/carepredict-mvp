# Planifier une intervention hospitalière à deux horizons

**La planification hiérarchique n’améliore pas l’attente des transferts sur les 64 hôpitaux synthétiques réservés.** À 72 h, elle ajoute en moyenne 0,033 patient-heure d’attente par situation par rapport au planning horaire. Le modèle plat obtient un meilleur résultat que la hiérarchie dans ce comparatif apparié. Quatre unités sur 382 dépassent au moins une marge avec la hiérarchie. L’essai ne justifie pas de remplacer le sélecteur opérationnel J7. [Verdict chiffré](resultats/verdict.json)

## Le scénario

À J7, à 08 h, un établissement peut conserver ses affectations, prêter une IDE à une unité voisine pour le poste de 18 h à 04 h, ou réserver une équipe de transport ou de bionettoyage de 14 h à 02 h. Les deux sens du prêt sont possibles. Le modèle voit les files, la charge et la dotation disponibles à cette heure, les informations datées de la semaine précédente et les réservations connues. Il reçoit une projection physique construite à partir de ces informations. Une confirmation reçue à 08 h 20 appartient à la suite de la simulation. Chaque branche conserve les trois autres familles de ressources et reprend les décisions horaires habituelles sur son propre état à partir du lendemain.

Une patient-heure mesure l’intégrale horaire de la file des patients prêts à un transfert. Les effets sont mesurés à 24, 72 et 168 heures. Chaque unité conserve trois mesures distinctes, l’attente de lit en patient-heures et les minutes de soins IDE et AS non couvertes. La limite de 1 % est calculée sur le résultat effectivement simulé pour le même établissement, la même unité et le même scénario horaire de référence.

## Résultats à 72 heures

Un gain positif représente une réduction de l’attente de transfert par rapport au planning horaire. Les 1 152 situations couvrent deux épisodes, trois régimes de disponibilité des données et trois profondeurs d’historique par établissement. Les intervalles à 95 % rééchantillonnent 20 000 fois les 64 établissements, en conservant ensemble leurs situations et leurs unités.

| Politique | Commandes actives | Gain moyen en patient-heures [IC 95 %] | Situations dépassant une marge | Unités dépassant une marge en moyenne |
|---|---:|---:|---:|---:|
| Planning horaire | 0 | 0 | 0 | 0 |
| Sélecteur J7 livré, avec veto d’exécution | 0 | 0 | 0 | 0 |
| Projection physique seule | 171 | −1,649 [−3,021 ; −0,552] | 66 | 30 |
| Modèle plat calibré | 208 | +0,229 [−0,007 ; +0,570] | 14 | 7 |
| Modèle hiérarchique calibré | 119 | −0,033 [−0,156 ; +0,071] | 8 | 4 |
| Meilleure option réellement admissible connue après coup | 326 | +4,832 [+3,311 ; +6,644] | 0 | 0 |

Le contraste primaire hiérarchie moins modèle plat est de **−0,262 patient-heure par situation**, IC 95 % **[−0,595 ; −0,039]**. Pour la hiérarchie, huit situations dépassent la marge d’au moins une unité. Les dépassements concernent l’attente de lit dans sept situations, les soins IDE dans une et les soins AS dans quatre, avec recouvrement. En moyenne sur les 18 situations de chaque établissement, les dépassements concernent deux couples unité–lit et trois couples unité–AS, répartis dans quatre unités de trois établissements. Les budgets, l’unicité des réservations et le plancher de dotation du donneur sont respectés.

La hiérarchie propose 114 bionettoyages et cinq transports. Sur ses 119 commandes, 108 laissent identiques les quatre coûts de chaque unité à 72 h. Cinq raccourcissent l’attente de transfert et six l’allongent. Dans 78 commandes, l’équipe fournit un travail supplémentaire mesurable pendant au moins une heure. Dans 45 commandes, l’unité indiquée est déjà celle que le planning horaire retient à midi. Ces deux comptages peuvent se recouvrir. L’oracle peut choisir entre 27 504 alternatives sur le panel. Sous les limites locales, il choisit 225 transports, 48 bionettoyages, 53 prêts IDE et 826 maintiens. Cet écart indique quelles occasions restent à identifier.

Les résultats à court et long terme vont dans le même sens. Le gain de la hiérarchie face à l’horaire vaut +0,002 patient-heure à 24 h [−0,016 ; +0,020] et −0,137 à 168 h [−0,360 ; +0,036]. Avant le filtre de prudence par établissement, la hiérarchie propose 190 commandes, avec un gain moyen à 72 h de −0,072 [−0,218 ; +0,060] et 16 situations en dépassement. Son contraste avec le modèle plat à ce même stade vaut −0,356 [−0,887 ; +0,089].

Dans une lecture descriptive par régime de données, la hiérarchie recommande une action dans 25 des 384 situations avec données complètes, 40 avec données partielles et 54 avec données retardées. Les gains moyens respectifs sont −0,037, −0,130 et +0,069 patient-heure. La politique horaire, l’état atteint à J7 et les commandes admissibles peuvent également varier avec les informations reçues. [Détail descriptif à H72](resultats/strates_descriptives.json)

## Adaptation de H-JEPA

Zhang, Terver, Rabbat, LeCun et Balestriero apprennent des représentations visuelles à différentes échelles temporelles. L’étage supérieur avance vers un objectif et ses prédictions intermédiaires deviennent des sous-buts pour l’étage inférieur. Les auteurs évaluent ce mécanisme dans des environnements de navigation et de manipulation, ainsi que sur des vidéos de robot pour une évaluation hors ligne. [Article v2](https://arxiv.org/html/2610.06805v2) · [Présentation des auteurs](https://h-jepa.com/)

L’adaptation hospitalière apprend des représentations de vingt grandeurs d’effet, issues des quatre coûts simulés, agrégées au niveau de l’établissement, des unités extrêmes, du donneur et du receveur. La régression de rang réduit apprend les directions de variation prévisibles sous contrainte de covariance. Le blanchiment régularisé et les quatre valeurs propres prédictives positives de l’étage supérieur donnent un contrôle de rang. Le prédicteur apprend l’écart entre l’effet anticipé par le simulateur public et l’effet réellement réalisé dans les trajectoires synthétiques d’entraînement.

- **Étage supérieur.** Une intention regroupe les affectations réalisables d’une même famille de ressources. Elle pondère les lieux à partir de la seule projection disponible à 08 h. Son encodeur projette le latent fin de huit dimensions dans un espace appris de quatre dimensions. L’étage prévoit la position de chaque intention à 72 h et choisit celle qui progresse vers le profil d’amélioration observé dans les établissements d’entraînement. Sa prévision à 24 h fournit le sous-but.
- **Étage inférieur.** Il prévoit l’effet à 24 h de chaque commande élémentaire à partir des informations courantes. Parmi les affectations réalisables dans la famille choisie, il sélectionne celle dont la représentation est la plus proche du sous-but supérieur. Avant le filtre statistique, cet étage dispose en moyenne de 2,92 affectations à départager lorsque l’étage supérieur choisit d’agir.
- **Ablation plate.** Elle utilise un unique espace appris de huit dimensions pour les deux horizons et choisit directement la commande primitive. Les deux programmes partagent les fonctions de description, le catalogue d’actions et 1 536 coefficients appris de prédiction. Leurs encodeurs de résultats ont respectivement 160 coefficients pour le modèle plat et 192 pour le modèle hiérarchique. Ils examinent en moyenne 24,88 options par situation, dont 5,30 franchissent les vérifications publiques initiales, maintien compris. Le nombre d’opérations de calcul des deux architectures peut varier.

Le programme hospitalier commande un seul poste et prévoit des effets opérationnels cumulés sous la politique horaire qui lui succède. Il apprend à partir de contrefactuels synthétiques appariés. L’article entraîne conjointement des encodeurs d’observations et d’actions sur des séquences et emploie une régularisation SIGReg. Une expérience avec plusieurs décisions élémentaires successives sous un même sous-but constituerait un test plus direct de la décomposition temporelle. L’intérêt clinique et la transférabilité sur des données de terrain restent à mesurer.

## Entraînement et vérification

Les mêmes 96 hôpitaux servent à apprendre les encodeurs, les prédicteurs et l’objectif des deux architectures. Trente-deux autres hôpitaux calibrent le seuil à partir des propositions qui dépassent réellement une limite. La calibration prend le maximum par établissement sur toutes les situations, puis le rang 30 sur 32 et une inégalité stricte au moment de proposer. Les seuils appris valent 0,89574 pour le modèle plat et 0,91574 pour la hiérarchie. Le score de sûreté commun provient des poids opérationnels J7. Le développement utilise 32 autres établissements. Le test utilise 64 établissements neufs, avec une graine d’apprentissage fixée avant l’ouverture. [Ajustement et spectres](resultats/ajustement.json) · [Développement](resultats/validation_dev.json) · [Protocole](PROTOCOLE.md)

La vérification du verdict relit les hashes des règles, du modèle et des observations scellées. Les commandes suivantes sont à lancer depuis la racine contenant `base/` et `hierarchie/`.

```bash
export PYTHONPATH=.:base:base/parent
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
python -m unittest hierarchie.test_hierarchie -v
python -m hierarchie.trial verdict \
  --lock d299e1ac6241a2c49aeb6f6ed057ac92ed8c47fd71717f39b8208e4a92098a91 \
  --assign b5df56cd6cb8a55ee80f050ea541baf8c511eea60bda18b2b3612f7d05ff21ba \
  --reveal fbb416389cd2bb899b4ca8ee84f3b7ea5f732e5f8992479dbd3b60436106f8af
```

Pour reproduire l’ajustement dans une copie de travail neuve, exécuter `python -m hierarchie.model` puis `python -m hierarchie.trial dev`. Le cycle prospectif initial exécute ensuite `seal`, `assign`, `reveal` et `verdict`, chaque étape consommant les empreintes indépendamment enregistrées aux étapes précédentes. Le test final comporte cinq contrôles automatisés, dont le calcul effectif du sous-but, l’égalité de capacité prédictive, le caractère daté des entrées, le veto historique et l’abstention en cas d’égalité au seuil.

[Poids entraînés](resultats/poids.npz) · [Scellement](resultats/gel.json) · [Reçu des décisions](resultats/recu_assign.json) · [Reçu des issues](resultats/recu_reveal.json)
