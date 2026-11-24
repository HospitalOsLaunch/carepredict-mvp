# Planification par unité · protocole gelé avant implémentation

Validé le 24 novembre 2026 sur la base 486b0cb. Le moteur minimise les mêmes
patients-minutes d’attente en moyenne et dans le pire décile, avec une garde
par scénario sur le personnel, le nettoyage, le transport et l’aval. Le témoin
reçoit exactement les mêmes demandes. La simulation conduit à une revue humaine.

| Source | Condition à la relève D |
| --- | --- |
| Entrées programmées | Synchronisation ≤ 2 h, identités, annulations, besoins et fenêtres. Couverture déclarée jusqu’à l’horizon, y compris pour une liste vide. |
| Sorties prévisionnelles | Date valide revue depuis ≤ 24 h pour ≥ 90 % des séjours présents. L’autorisation de sortie est une donnée distincte. |
| Planning soignant | Synchronisation ≤ 24 h, périodes et compétences validées et complètes, aucune affectation simultanée d’une personne. |
| Arrivées urgences | Distribution par unité et jour civil, fuseau et attribution documentés. Émission ≤ 24 h, couverture de chaque jour. |

Pour ouvrir J+3, les deux cibles (lits occupés à la relève suivante et arrivées
urgences du jour cible) doivent chacune réduire leur MAE de ≥ 10 % à J+1 et J+3
par rapport à la meilleure des deux références disponibles à D (dernière valeur
observée et même jour de semaine antérieur). J+7 exige en plus les deux réussites
à J+7. Unités équipondérées, au moins 30 origines quotidiennes évaluables par
unité et échéance, évaluation chronologique distincte du développement. Intervalle
à 95 % apparié par univers indépendants et blocs temporels, borne basse du gain
strictement positive. Si la référence a une MAE nulle, le gain relatif requis
est indémontrable. Publier toutes les cellules, unités et échecs.

Les seuils portent sur le synthétique et sur la version de prévision évaluée.
Une preuve absente, un périmètre différent ou un flux dégradé ferme l’horizon
concerné. Les engagements déjà observés sont conservés entre les journées.

Le banc utilise huit univers, quatre unités, 35 origines par unité et univers
(jours 21 à 55, après une période initiale de 21 jours), quatre scénarios
par projection et 2 000 rééchantillonnages appariés par blocs de sept jours.
Les cibles sont disponibles uniquement pour le score. Pour l’ouverture d’une
unité, le panel équipondéré et la ligne de cette unité doivent satisfaire les
critères. Pour J+7, la référence hebdomadaire des urgences prend le dernier
jour de même phase dont le bilan est complet à D. La cohorte est entièrement
synthétique, sans réglage sur ces 35 dates.
