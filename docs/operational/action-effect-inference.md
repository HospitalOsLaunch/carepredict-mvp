# Prédire les effets d’une action sur l’hôpital

L’entrée correspond aux 72 variables renvoyées par `public_features` dans `run.py`. Leur ordre et leur transformation font partie du modèle. Le prototype utilise quatre unités synthétiques et une décision à minuit. Les actions `cleaning` et `transport` ajoutent chacune 16 heures-agents entre 6 h et 14 h. Les écarts sont cumulés à H6, H12 et H24 par rapport au même scénario sans renfort supplémentaire. Une valeur négative indique moins d’attente ou moins de charge non couverte. La commande de démonstration rejoue le premier exemple réservé au test avec NumPy. Les résultats du [banc synthétique existant](../../scripts/action_effects/RESULTATS.md) précisent les limites du classement des interventions. Ces scripts de recherche s’exécutent indépendamment du cockpit.

```sh
python scripts/action_effects/predict.py --demo --action transport
python scripts/action_effects/predict.py --features features.json --action cleaning
```

Le protocole d’origine a choisi la régularisation sur DEV. Pour réajuster la régression avec cette valeur gelée sur les 48 épisodes TRAIN, installer aussi scikit-learn. Le test de parité vérifie le résultat sur les 32 épisodes TEST. Passer le fichier produit à la commande de prédiction avec `--weights` pour utiliser les nouveaux coefficients.

```sh
python scripts/action_effects/fit.py --examples evidence/action_effects/examples.json.gz --output /tmp/hospitalos-refit.json
python -m unittest discover -s tests/action_effects
```

## Prédire un clic avec un modèle externe

Le client `scripts/computer_use/predict_click.py` interroge [Qwen-AgentWorld-35B-A3B](https://github.com/QwenLM/Qwen-AgentWorld) via son serveur compatible avec l’API de chat. Il prend l’arbre d’accessibilité observé et l’identifiant du contrôle ciblé. Il restitue le prochain écran prédit comme texte inerte. L’option `--demo` utilise un formulaire fictif avec deux cases à cocher. Le second exemple accepte un arbre fourni par l’appelant. Lancer ces commandes sur une instance du modèle déjà en service.

```sh
python scripts/computer_use/predict_click.py --demo --base-url http://localhost:8000/v1
python scripts/computer_use/predict_click.py --page page.txt --bid 2 --base-url http://localhost:8000/v1
```

Une prédiction d’écran est une hypothèse. Dans le circuit du cockpit, l’équipe peut modifier, valider ou refuser la proposition. Après validation, la relecture du logiciel établit que la demande a été enregistrée. Le départ, la remise à disposition du lit et l’évolution de l’attente ont chacun leur propre observation horodatée. Cette distinction permet de mesurer le délai entre demande et exécution, et de comparer ensuite les effets au fonctionnement habituel de l’équipe.
