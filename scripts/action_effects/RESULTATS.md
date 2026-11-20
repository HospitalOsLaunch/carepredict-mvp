# Apprentissage des effets des interventions

Le modèle reste expérimental. Le test de promotion demandait une réduction de l’attente à 24 h et une absence de hausse des soins non couverts face à l’ensemble GraphWM physique, sous un plafond de 16 heures-agents.

## Revue du commit 981c414

Deux corrections touchent le banc d’évaluation. L’erreur d’effet exclut maintenant l’abstention comparée à elle-même. Les anciens scores incluant cette comparaison étaient inférieurs d’un tiers à l’erreur moyenne sur les deux interventions. Le test d’actions mensuel fournit désormais uniquement les canaux de ressources utilisés à l’apprentissage. L’ancien test injectait une marque de frontière de décision à partir du deuxième intervalle.

Les dix cycles ont été rejoués pour les deux variantes et les trois graines. Les métriques mensuelles et les résultats par cycle sont identiques au calcul initial. La comparaison décisionnelle corrigée à 24 h donne 25,92 patients-minutes d’attente supplémentaires avec JEPA en moyenne. L’intervalle exploratoire croisé sur les graines et les structures va de −27,00 à +90,75. Le rapport de la campagne précédente intègre le recalcul. Les archives du commit parent permettent de reproduire la version initiale.

## Expérience appariée

Le protocole utilise 24 structures d’apprentissage, 8 de sélection et 16 pour le test, avec deux épisodes par structure. Depuis chaque état de décision à minuit, quatre futurs synthétiques sont partagés entre l’abstention, le nettoyage et le transport. Chaque renfort mobilise 16 heures-agents de 6 h à 14 h. Les deux cibles sont les différences cumulées d’attente et de soins non couverts face à l’abstention, mesurées à 6, 12 et 24 h. Les effets à 6 h sont nuls par construction.

Une régression ridge apprend ces effets à partir de l’état public filtré et des estimations des trois modèles physiques gelés. Le coefficient de régularisation est choisi sur les huit structures de développement. Les résultats du simulateur sont utilisés pour les étiquettes et l’évaluation. La règle expérimentale minimise l’attente prédite parmi les actions dont l’augmentation prédite des soins non couverts est inférieure ou égale à zéro face à l’abstention. C’est une hypothèse de recherche.

| Horizon | Erreur sur l’effet d’attente, GraphWM | Modèle apparié | Erreur sur l’effet de soins, GraphWM | Modèle apparié |
|---|---:|---:|---:|---:|
| 12 h | 11,60 | 18,58 | 2,15 | 4,17 |
| 24 h | 103,77 | 92,46 | 33,24 | 33,47 |

Erreurs absolues moyennes sur les deux interventions. L’attente est en patients-minutes et les soins en minutes de charge non couverte. À 24 h, prédire partout un effet nul donne respectivement 104,00 et 33,13.

| Écart à 24 h face au planificateur physique | Moyenne par épisode | IC 95 % par structure |
|---|---:|---:|
| Attente | +127,15 patients-minutes | +7,38 à +299,30 |
| Soins non couverts | −60,03 min | −111,40 à −18,76 |
| Renfort engagé | −4,50 heures-agents | −7,50 à −2,00 |

Le plafond est identique entre politiques. Un diagnostic impose aussi une dépense identique en choisissant entre les deux renforts uniquement sur l’attente. L’écart moyen d’attente vaut alors zéro et celui des soins vaut +0,46 minute pour le modèle apparié. Les résultats décrivent une décision unique à minuit, dans des structures synthétiques de quatre unités avec un retard de déclaration de trois heures. L’incertitude est estimée sur les 16 structures. Le seuil de soins est une contrainte sur la prévision moyenne, sans garantie pour un épisode individuel.

## Reproduction

Depuis la racine, extraire les poids et le filtre du lot 981c414 dans evidence/filter_pipeline. Exécuter python scripts/action_effects/run.py avec PyTorch CPU, SciPy, Pandas, NumPy et scikit-learn. Le protocole, le modèle ajusté, les exemples et les décisions par épisode sont conservés avec le résumé. Les poids de GraphWM sont ceux de la campagne précédente. La régression et le planificateur sont expérimentaux.
