# HospitalOS · Effet d’une affectation et relecture de la journée

Le cockpit reprend **J7-CF-2026.11.21** et étend les interventions dans **MIDI5-v1**. Les résultats scientifiques ci-dessous portent sur le catalogue du protocole initial. Les nouvelles actions de personnel, de SMR et de lit utilisent le modèle physique. Le modèle d’état projette le nombre de patients en attente d’un transfert dans chaque unité. Le réseau JEPA prédit une correction à partir du même état public et de l’action envisagée. Après réception des données de l’option validée, l’application peut estimer ce que la file aurait été sous une autre affectation. Les prévisions sont calculées en ligne sur des établissements synthétiques.

Le cockpit de midi propose aussi des combinaisons chiffrées de ressources et de mouvements de patients. Son simulateur d’actions conjointes réutilise le noyau de dynamique hospitalière, avec un registre des dossiers connus, un calendrier et des contraintes partagées. Les résultats JEPA du tableau se rapportent aux actions du protocole J7. [Parcours de démonstration des plans composés](../../web/README.md#simuler-le-plan-de-midi)

## Ce que les essais ont établi

| Question | Population | Résultat |
|---|---|---|
| Quel aurait été le stock à 16 h sous une autre affectation de midi ? | 64 hôpitaux indépendants, deux épisodes, trois flux, deux décisions par épisode | Sur flux complet, l’erreur absolue par unité du JEPA passe de 0,174 patient avant relevé à 0,031 après correction. La simple copie du relevé donne 0,099 et le modèle d’état corrigé 0,025. |
| Une hiérarchie choisit-elle un meilleur renfort à 8 h ? | 1 152 situations, 382 unités | À 72 h, le gain face au planning horaire vaut −0,033 heure-patient, avec un intervalle à 95 % de −0,156 à +0,071. Le cockpit prend le planning horaire comme référence. |
| La correction respecte-t-elle les capacités ? | 32 nouveaux hôpitaux, test complémentaire | Les reconstructions JEPA incohérentes passent de 22,93 % à 0 %. L’erreur de transfert passe de 0,0283 à 0,0285 patient par unité. |

Le résidu commun à toutes les actions améliore les niveaux reconstruits après observation. Avant projection sur les capacités, il conserve leurs différences. Les valeurs ci-dessus portent sur des flux continus synthétiques. [Méthode contrefactuelle](https://arxiv.org/abs/2611.24778) · [H-JEPA](https://arxiv.org/abs/2610.06805)

## Modèle servi et parité

Le code opérationnel, le noyau natif C++17 de l’essai, les poids JEPA de graine 19 et les entrées des trois contextes se trouvent dans [world_model](../../src/hospitalos/world_model). Le modèle JEPA comporte 24 dimensions latentes et utilise les descriptions publiques des unités et des actions. Chaque requête réutilise la prévision du même contexte tant que ses entrées restent identiques. Le noyau ne simule l’issue factuelle qu’après validation humaine et au moment prévu pour la publication. L’API conserve le choix, les valeurs et leur version dans SQLite. Les deux autres graines JEPA et les poids du planificateur hiérarchique sont fournis ici pour la recherche.

Les trois sites de démonstration ont été choisis parmi les prévisions publiques pour illustrer des écarts entre options et trois niveaux de disponibilité des données. Les moyennes scientifiques ci-dessus portent sur les panels complets. La démonstration n’exécute aucune action dans un établissement.

- [Parcours produit et lancement](../../web/README.md#simuler-le-plan-de-midi)
- [Contrat et contrôles d’horloge](cf/PROTOCOLE.md)
- [Planification hiérarchique et ablation](hierarchie/HIERARCHIE.md)
- [Projection sur les capacités](contraintes/PROTOCOLE.md)
- [Revue indépendante des résultats](revue/REVUE.md)
- [Régressions API et parité avec les trajectoires scellées](../../tests/world_model)

## Reproduction

Depuis la racine du dépôt, les tests de la démo s’exécutent sans l’archive de recherche, avec les dépendances indiquées dans le guide du cockpit.

```bash
PYTHONPATH=src:. python -m pytest -q tests/world_model
```

Les dossiers `cf`, `hierarchie`, `contraintes`, `revue`, `publication`, les trois verdicts JSON et les empreintes conservent le code et les résultats scellés de l’expérience. Le rejeu exhaustif utilise également le simulateur de base et les trajectoires dans l’archive d’étude `HospitalOS_Balestriero_Code_Poids_Resultats.zip` (SHA-256 `ff8251b29c1db6e2d2eeafdd23f3a9ef04c7214bc88faefea5e9d952b0a8e039`). Extraire cette archive puis, **depuis son dossier HospitalOS_Balestriero**, exécuter `python rejouer.py --regenerer --workers 6`. Le script restaure la livraison J7 et vérifie les trois verdicts. Le dépôt Git contient tous les fichiers nécessaires au fonctionnement en ligne du cockpit. L’archive de recherche complète fournit les données brutes des campagnes.

Pour régénérer les entrées des démos depuis l’étude restaurée, revenir à la racine du dépôt puis exécuter les commandes ci-dessous. Le second export prépare uniquement un témoin de test.

```bash
python research/balestriero/export_demo.py /chemin/vers/HospitalOS_Balestriero
python research/balestriero/fixture_demo.py --help
```
