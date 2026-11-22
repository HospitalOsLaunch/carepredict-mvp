# Grille prospective du modèle AJ-H

Le réglage par défaut de l’assemblage calendrier v0.4.1 est défini dans sa spécification. Chaque appel peut choisir 15, 30 ou 60 minutes. Les trois réglages emploient le même jeu de poids. La séquence historique de l’adaptateur et les cibles de supervision gardent leur cadence source. Le pilote 014 fournit des cibles à H1, H6 et H24, avec H72 à certaines origines.

```python
from research_lab.integrated_full_model_v1_contract import make_v041_synthetic_spec
from rs_jepa.integrated_full_model_v041 import assemble_v041_untrained

spec = make_v041_synthetic_spec(future_step_minutes=30)
model = assemble_v041_untrained(stage1=config, spec=spec).model
forecast = model(**inputs, future_step_minutes=30, return_grid_forecasts=True)
# forecast.grid.end_offsets_minutes = (30, 60, ..., 1440)
# forecast.grid.means et forecast.grid.scales : [lots, 48 créneaux, cibles]
```

À H24, le plan reçoit 48 créneaux de 30 minutes. Une demande datée de 18 h 30 se place au début du deuxième créneau d’un plan démarré à 18 h. Un créneau porte le nombre de demandes pour chacun des quatre leviers natifs. La cellule récurrente emploie une horloge interne fixe de 15 minutes et applique les demandes une seule fois au début du créneau. Les états sortent aux bornes de fin. Les estimations intermédiaires optionnelles utilisent la même tête probabiliste. Elles restent sans mesure de référence à la demi-heure dans 014. Un plan partagé entre deux grilles donne les mêmes états aux heures communes. Pour une demande entre deux bornes, choisir une grille qui représente son heure exacte. Le choix de grille est consigné dans la sortie. L’ancienne spécification garde ses poids, son architecture et sa cadence.

Le canal calendrier provient de la date de décision et des règles du simulateur français v0.4.1 (UTC+01 fixe). Il encode l’heure, le jour de semaine, les parts ouvrées et fériées de chaque intervalle et sa durée. Les pannes, présences futures et plannings locaux révisables restent hors de ce premier canal. Une heure territoriale réelle avec changement d’heure demanderait une règle propre au site.

```bash
PYTHONPATH=src:. python -m research_lab.future_calendar --origin '2026-11-20T18:00:00+01:00' --step-minutes 30 --horizon-hours 24
```

## Contrôle exploratoire sur le pilote 014

Protocole fixé avant l’exécution de ce contrôle. Réutiliser le découpage par épisode et la recette de boosting déjà fixée dans le pilote. Entraîner deux références avec la même recette CPU sur les seules données train. Ajouter à la seconde l’encodage du jour de semaine à l’origine et le nombre d’heures ouvrées et fériées sur les 24 h à venir. Le vecteur de référence comporte déjà l’heure de la journée. Pondérer les expositions par durée pour que 30 et 60 minutes donnent les mêmes entrées sur ces origines. La physique source reste horaire.

Le critère principal est le regret moyen de la décision à H24, en patients dans la file des urgences. Pour chaque demande candidate du développement, appliquer la demande si le contraste prévu « avec demande moins témoin » est strictement négatif. Le regret est la file de l’option choisie moins la meilleure file de la paire. Une égalité prédite conduit à maintenir le plan. Les paires ayant réellement le même résultat restent au dénominateur du regret. Mesures secondaires : erreur absolue du contraste et nombre de choix corrects sur les seules paires ayant des résultats distincts. Calculer la différence calendrier moins référence avec 2 000 rééchantillonnages appariés par épisode. Les huit structures sont communes aux partitions. Ce contrôle de référence ne constitue pas une qualification d’AJ-H et ne décide pas du passage G2.

```bash
PYTHONPATH=src:. python -m research_lab.calendar_pilot_014 /chemin/HospitalOS_Corpus_014_Pilote_et_Rectificatif_013.zip
```

La comparaison scientifique d’AJ-H demande deux assemblages entraînés avec les mêmes données, la même horloge interne et les mêmes budgets, en passant `use_civil_calendar=False` à la fabrique de spécification pour le témoin. Ce mode garde les poids de la même dimension, la durée du pas et l’horloge interne. Qualifier d’abord l’historique d’observations et ses horodatages pour AJ-H. Une affirmation sur les résultats d’une action à la demi-heure nécessitera des observations ou une physique de référence à cette résolution.

## Résultat exploratoire du 22 novembre 2026

Sur 864 décisions d’entraînement et 683 paires demande/témoin évaluables dans 72 épisodes de développement, 65 ont une file différente à H24. Sur ces 65, le boosting de référence choisit la meilleure branche 54 fois, le boosting avec calendrier 55 fois. Sur les 683 paires, le regret moyen passe de 0,01757 à 0,01464 patient et l’erreur absolue du contraste de 0,19892 à 0,19506 patient. Différence de regret de −0,00293 patient, intervalle exploratoire à 95 % par épisode [−0,01201 ; +0,00436]. Le pilote ne permet pas d’établir un gain. Le temps ouvré ou férié cumulé à H24 est identique aux grilles 30 et 60 minutes pour les 1 728 origines examinées. Version de scikit-learn : 1.8.0. Aucun entraînement neuronal dans cette comparaison.
