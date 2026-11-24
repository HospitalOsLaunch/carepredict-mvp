# Sources du plan d’unité · version 1

Les quatre schémas JSON sont exportés depuis les modèles utilisés par l’API.
Chaque reçu identifie l’hôpital, l’unité bénéficiaire, le logiciel, sa révision,
la provenance synthétique ou hospitalière, le fuseau et la période semi-ouverte
couverte. Les instants doivent porter un décalage UTC. La publication précède
la première réception, elle-même antérieure ou égale à la synchronisation.
Les corrections portent une révision supérieure ; le calcul à la relève D
ne voit que les révisions reçues et synchronisées à D.

Une liste vide d’entrées est exploitable dans un export complet couvrant la
période. Le champ prepared_bed décrit un engagement déjà connu. Les dates
de sortie sont des estimations par séjour et restent distinctes de
l’autorisation. Les effectifs sont vérifiés par compétence sur chaque morceau
de poste et toute double affectation est signalée. Chaque valeur de counts
est un tirage équiprobable de la demande quotidienne issue des urgences,
déjà affectée à l’unité selon allocation_rule. Les entrées programmées
figurent dans un flux distinct.

Les seuils sont fixés dans docs/operational/unit-planning-gates.md. Lors d’une
panne, publier un reçu outage, avec une révision supérieure, dans la même série.
Le calcul sert des projections en observation seule.

Le planning déclare aussi les affectations externes des professionnels proposés
(external_shifts, liste vide si le contrôle confirme leur absence). Un prêt
confirmé peut provenir du donneur déclaré dans les limites de sa réserve.
Une personne déjà comptée dans la capacité de référence n’ajoute aucun lit.
