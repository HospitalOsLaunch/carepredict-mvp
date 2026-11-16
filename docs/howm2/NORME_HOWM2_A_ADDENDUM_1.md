# HOWM-2 A — Addendum 1 à la note normative (consigné avant toute mesure de l'échelle)

1. **Famille « autorisation ».** Calculée pour L0, L1 et L2 seulement. Pour L3 à L5, elle n'est pas
   calculée : sa loi exacte (8 jours, recalage diurne, retard en minutes, intervalles de 60 min) est
   trop coûteuse par élément.
   - Elle est hors critère, comme en R1 : l'agrégat L exclut l'autorisation.
   - Le verdict n'en dépend pas.
2. **Éléments en cours dans L4.**
   - La censure des éléments encore en cours à t n'entre pas dans l'inférence des paramètres et du
     régime.
   - Elle sert uniquement à leur propre prédiction, conditionnée par T ≥ e.
   - La prédiction reste propre, sans double comptage. L4 peut perdre un peu d'information : c'est
     une approximation prudente du plafond, déclarée.
3. **Charge m3 publique figée.** La charge publique utilisée pour une sortie prête déjà observée est
   celle connue à la disponibilité de cet événement, et reste figée ensuite.
4. **Exactitude (c)** : deux contrôles.
   - Énumération directe de tous les chemins de régime sur des préfixes de 12 h (2^13 chemins).
   - Implémentation indépendante de l'avant-arrière, en boucles simples et en log, sur 200 éléments
     de l'échelle.
5. **Cohortes et labels.** Ils sont extraits par une version allégée de `dataset.build`, sans les
   tables de graphes. Un test vérifie l'égalité exacte des cohortes, labels, masques et fenêtres
   avec `dataset.build` sur un établissement VAL.
