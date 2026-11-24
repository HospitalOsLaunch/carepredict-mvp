# Plan par unité · résultats synthétiques du 24 novembre 2026

**J+3 et J+7 restent en NO-GO dans les quatre unités.** Les distributions
d’arrivées des urgences dépassent le seuil de précision. Les occupations
projetées à la relève échouent dès J+1. Le cockpit garde le plan à 24 heures
et affiche les informations connues dans la perspective à plusieurs jours.

| Cible | Horizon | MAE moteur | MAE persistance | MAE hebdomadaire | Gain sur la meilleure référence [IC 95 %] |
| --- | --- | ---: | ---: | ---: | ---: |
| Lits occupés | J+1 | 1,452 | 1,227 | 1,585 | −18,3 % [−26,4 ; −10,7] |
| Lits occupés | J+3 | 2,917 | 1,530 | 1,572 | −90,6 % [−114,1 ; −71,8] |
| Lits occupés | J+7 | 3,466 | 1,556 | 1,556 | −122,7 % [−147,3 ; −98,4] |
| Arrivées aux urgences | J+1 | 0,958 | 1,557 | 1,454 | +34,1 % [+28,1 ; +39,3] |
| Arrivées aux urgences | J+3 | 0,952 | 1,547 | 1,438 | +33,8 % [+28,3 ; +39,0] |
| Arrivées aux urgences | J+7 | 0,954 | 1,513 | 1,410 | +32,3 % [+28,0 ; +36,4] |

Les valeurs sont des nombres de patients ou de lits en erreur absolue. La ligne
de panel donne le même poids à chaque unité. Le fichier [metrics.csv](metrics.csv)
contient également les 24 cellules par unité. Sur 1 120 relèves (8 univers ×
4 unités × 35 dates), 6 669 observations de séjour sur 6 669 possédaient une
estimation de sortie à jour. Un même séjour peut compter à plusieurs relèves.
Cette couverture de 100 % est construite par l’adaptateur synthétique.

Le banc compare à chaque origine la trajectoire sans action du moteur aux
occupations futures d’une file à capacité finie et aux arrivées réalisées.
Les demandes programmées sont annoncées avant la relève. Les annulations non
annoncées, délais réels et urgences réalisées appartiennent uniquement aux
résultats. La distribution ED publiée dans ce banc bénéficie d’un signal
calendaire informatif par construction. Le gain mesure son utilité synthétique.

Dans la projection, une personne nouvellement admise sans autorisation ultérieure
observée peut occuper un lit jusqu’au terme. Dans le générateur d’évaluation,
son séjour peut se terminer. Ce mécanisme mérite un test d’attribution avant
tout nouveau gel. Une estimation probabiliste du départ devra rester distincte
de l’autorisation nécessaire pour proposer un transport réel.

## Reproduction

Depuis la racine du dépôt avec l’environnement Python verrouillé :

```sh
PYTHONPATH=src:. python -m scripts.unit_planning.benchmark
```

Le programme reproduit metrics.csv et le reçu versionné chargé par le moteur.
Il utilise quatre tirages de dynamique par relève et 2 000 bootstrap appariés,
par univers et par blocs hebdomadaires. Les seuils et les deux références sont
définis dans [le protocole](../unit-planning-gates.md).
