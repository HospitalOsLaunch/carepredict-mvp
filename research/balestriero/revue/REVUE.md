# Contre-revue indépendante du comparatif Balestriero

**Le modèle reconstitue mieux un événement dont l’issue factuelle est déjà connue. La planification hiérarchique, testée avant l’événement, ne réduit pas l’attente.** Les deux expériences portent sur les mêmes 64 hôpitaux synthétiques, avec des décisions, des horizons et des critères différents. La réussite de la première ne valide pas une recommandation prospective.

## Reconstituer une autre action après observation

Le critère principal part de midi avec des données complètes. On évalue à 16 h, pour chaque alternative distincte du plan réellement tiré, le nombre de patients en attente de transfert dans chaque unité. Il s’agit d’un stock à un instant donné. L’issue factuelle de 16 h entre uniquement dans la reconstruction après cet instant.

| Estimation, mêmes situations et poids JEPA | Erreur absolue moyenne du stock par unité, IC95 par hôpital |
|---|---:|
| Prévision disponible à midi | 0,1739 patient [0,1606 à 0,1876] |
| Recopie du stock observé à 16 h pour toutes les options | 0,0995 [0,0829 à 0,1168] |
| Correction par le résidu observé dans le même épisode | **0,0307 [0,0257 à 0,0360]** |
| Même correction, en prenant le résidu de l’autre épisode | 0,2506 [0,2266 à 0,2748] |

L’ancrage enlève **0,0688 patient d’erreur par unité** par rapport à la simple copie [0,0552 à 0,0829]. La physique structurée avec le même ancrage atteint **0,0250**, soit 0,0056 de mieux que les poids JEPA [0,0021 à 0,0091]. Les valeurs sont fractionnaires car le simulateur représente des flux en continu.

Le résidu factuel est commun à toutes les options d’un événement. L’ajouter place plus justement chaque prévision dans le système de coordonnées réel. Les différences prévues entre actions restent identiques à moins de 2 × 10⁻¹⁵ patient sur le critère principal. Le classement par minimisation du stock total de transfert reste identique. En revanche, la distance à une *cible de file* peut changer. Pour des cibles de file atteignables et distinctes du factuel, la part de cibles rétrospectivement retrouvées passe de **64,8 %** à **79,4 %**. Cette cible et le relevé n’étaient pas connus lorsque l’équipe a pris la décision.

Le modèle de base possède une information sur les effets. Pour les cellules où l’action change réellement le stock d’au moins 0,05 patient, l’erreur du contraste est de **0,215 patient**, contre **0,862** si on suppose un effet nul. Ces cellules représentent seulement **11,5 %** des couples option–unité du critère principal. Le R² de niveau de la simple copie atteint déjà **90,7 %**, celui de l’ancrage **99,4 %**. L’article contre-factuel écarte de ses comparaisons fortes les environnements où la copie dépasse 60 % de R². L’article évalue des scènes physiques à partir d’images. Ici, la copie bénéficie de stocks hospitaliers souvent peu sensibles à un changement logistique de quatre heures. [Article sur les contrefactuels](https://arxiv.org/html/2611.24778v1).

L’incertitude porte sur les établissements entiers. Les poids 19, 37 et 71 sont trois initialisations testées dans les mêmes mondes. Ils ne fournissent pas trois populations indépendantes. Le comparateur JEPA avait déjà utilisé, lors de son entraînement historique, des contrastes entre plans simulés. Sa correction rétrospective ne demande aucun nouvel apprentissage. Sur l’espace EMA de 24 dimensions, l’erreur quadratique moyenne primaire passe de 0,0640 à 0,0101, contre 0,0120 pour la copie du latent. Un meilleur niveau de représentation peut à nouveau coexister avec les mêmes différences prédites entre options.

**Limite physique reproductible.** Dans le test original, 22,81 % [20,55 à 25,21 %] des états reconstruits « alternative × unité » contiennent au moins un stock négatif ou dépassent le nombre de lits. Même un très bon R² sur une file ne suffit donc pas à assurer la cohérence des cinq stocks. Le prochain contrôle traite explicitement la rétroprojection de ces états.

## Choisir à J7 avant de connaître les issues

Chaque architecture utilise les données publiées à 08 h, le même catalogue de personnel et de logistique, et le même filtre de disponibilité. La version hiérarchique choisit d’abord une famille, puis une unité ou un donneur pour atteindre un sous-objectif opérationnel à 24 h. Le bras plat choisit directement une option dans un espace latent commun. Les deux modèles utilisent des effets appariés synthétiques, des projections de rang réduit et 16 sorties prédictives. Ils adaptent l’idée hiérarchique à des tableaux opérationnels. L’article H-JEPA utilise des encodeurs et objectifs latents appris à plusieurs échelles sur des scènes visuelles. [Article H-JEPA](https://arxiv.org/html/2610.06805v2).

| À 72 h, comparaison avec le calendrier horaire | Gain d’heures-patients de transfert, IC95 | Choix actifs sur 1 152 | Contextes hors marge | Unités hors marge sur 382 |
|---|---:|---:|---:|---:|
| Modèle hiérarchique calibré | −0,033 h [−0,156 à +0,071] | 119 | 8 | 4 |
| Modèle plat calibré | +0,229 h [−0,007 à +0,570] | 208 | 14 | 7 |
| Système J7 précédemment livré avec contrôle de disponibilité | 0 h [0 à 0] | 0 | 0 | 0 |

Le modèle hiérarchique perd **0,262 heure-patient** face au modèle plat [−0,595 à −0,039 de gain]. Les enveloppes de budget, les créneaux exclusifs et le plancher du donneur sont respectés. Les quatre dépassements d’unité du modèle hiérarchique touchent le délai du lit ou les minutes AS, selon l’unité. Un agrégat par établissement aurait masqué ces effets.

Sur 119 actions hiérarchiques, 114 sont des bionettoyages et cinq des transports. Les équipes utilisent la ressource pendant au moins une heure dans 78 cas. Dans **45 cas**, le créneau diffère du plan horaire et la ressource est utilisée. Onze choix modifient au moins un coût unitaire à 72 h. **Un seul** réduit l’attente totale de transfert tout en respectant les trois gardes dans chaque unité de son contexte. Le gain réel, la présence d’une action dans l’interface et l’exécution d’une tâche sont trois observations distinctes.

Les deux politiques examinent en moyenne 24,9 options, dont 5,3 sont admissibles au filtre public. La hiérarchie évalue 3,0 familles et compare en moyenne 1,32 candidat au sous-objectif de la famille choisie. Les projections fines ont néanmoins été calculées en amont sur l’ensemble des offres. Ce comptage établit une différence de recherche au sein de la famille. Il ne mesure aucune accélération du calcul.

## Contrôles d’intégrité

Les trois stades du contrefactuel ont été archivés dans l’ordre des informations disponibles. J’ai rejoué les 768 situations depuis leur première semaine, regénéré la vue publiée, les trois prédictions gelées et l’intégralité des trajectoires sous les mêmes événements exogènes. Le choix factuel est indépendant des issues. Les alternatives partageant le même plan sont dédupliquées, et le plan factuel est écarté des scores. Les 768 contrôles à 1 h et 4 h après l’ouverture du matin retrouvent une absence exacte d’effet physique avant la prise de poste des ressources. Les flux retardés permettent la correction seulement à l’heure effective de réception.

Côté planification, j’ai reproduit les **9 216 affectations** des huit bras, les familles admissibles, les destinations et les sous-objectifs, puis les seuils séparés appris sur les 32 hôpitaux de calibration. Seize contextes prédéclarés des huit hôpitaux espacés dans le panel ont fait l’objet d’un recalcul physique de toutes les alternatives, avec les mêmes coûts à l’arrondi exact. Les 1 200 estimations ou bornes comparées dans les 120 strates du volet rétrospectif et les six contrastes de transfert du volet prospectif concordent avec les programmes d’origine.

Un défaut du raccordement J7 a été reproduit sur développement. Un checkpoint emprunté à l’autre épisode pouvait changer une coordonnée du point de départ de 4,06 patients. Le correctif contrôle le site, l’épisode, le flux, l’historique et l’identité du préfixe, et l’empreinte couvre toutes les caractéristiques de la vue. Le test de régression a réussi avant l’ouverture du panel.

## Corriger les états impossibles sur 32 autres hôpitaux

Ce correctif a été choisi après avoir constaté des stocks impossibles dans le premier test. Le nouvel essai utilise 32 hôpitaux inédits, 384 situations, les mêmes modèles gelés et les mêmes cinq horizons. Après l’addition du résidu, on remplace chaque état par l’état le plus proche dont les cinq stocks sont non négatifs et dont les quatre catégories de lits occupés ou indisponibles respectent la capacité de l’unité. Pour l’action réellement exécutée, les cellules déjà publiées sont conservées à leur valeur mesurée. Seules les cellules manquantes sont ajustées sur les lits restants.

| Midi vers 16 h, flux complet, même graine 19 | Avant correction | Après correction |
|---|---:|---:|
| États « alternative × unité » hors domaine, IC95 par site | 22,93 % [18,95 à 27,14 %] | **0 % [0 à 0 %]** |
| Erreur absolue sur le stock de transfert, patients par unité | 0,02830 [0,02282 à 0,03483] | 0,02852 [0,02310 à 0,03494] |
| Erreur quadratique moyenne sur les cinq stocks | 0,008350 | 0,008247 |

La différence appariée d’erreur de transfert, avant moins après, est de **−0,00021 patient [−0,00141 à +0,00058]**. Le correctif rétablit la cohérence physique. Le transfert seul ne bénéficie d’aucun gain établi. Sur le vecteur complet des stocks, la distance euclidienne à un état réel admissible ne peut augmenter. Cette propriété ne garantit pas une amélioration de chaque composante ni du classement des actions.

La projection est non linéaire. Le contraste de transfert prévu se déplace d’au plus **0,310 patient** dans une situation primaire. La moyenne des maxima par situation vaut 0,0120. On observe **37 inversions parmi 3 654 comparaisons de rang non ex æquo**, réparties dans **10 des 64 situations primaires**. La relation d’invariance démontrée pour l’addition seule cesse donc de s’appliquer à la sortie corrigée.

J’ai vérifié toutes les sorties avec une projection indépendante par dichotomie, ainsi que les conditions d’optimalité, l’idempotence et les 48 relectures physiques intégrales annoncées avant le test. Aucune reconstruction ne sort de la capacité dans les 120 combinaisons d’heure, de flux, d’horizon et de modèle. L’écart maximal entre une cellule factuelle publiée et sa reconstruction est nul. Une projection qui oublierait de fixer les cellules connues les aurait déplacées de **2,97 patients** dans le cas le plus marqué des flux incomplets. Avant l’arrivée d’un relevé retardé, l’écart maximal imputable à sa disponibilité future reste inférieur à 2 × 10⁻¹⁵ patient.

Les autres métriques et données utilisées pour la contre-revue figurent dans `contrefactuel_independant.json`, `hierarchie_independant.json` et `projection_independante.json`. Dans ce dernier fichier la clé `state_rmse` contient l’erreur quadratique moyenne avant racine. La clé `mae_copy` utilise la copie factuelle intégralement observée. Pour les flux partiels ou retardés, le comparateur limité aux variables effectivement publiées est disponible dans `projection_verifications.json` sous `observable_copy_mae`. Le choix de comparateur n’affecte aucun des critères primaires, mesurés sur flux complet.
