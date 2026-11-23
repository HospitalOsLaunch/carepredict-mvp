# Tranche B — Monde v2 et porte d'identifiabilité (proposition séparée, aucun entraînement)

## Justification, d'après A et A′

| Mesure | Valeur | Conséquence pour v2 |
|---|---|---|
| Régime m2 : part récupérée π | ≤ 0 (A) | Le régime doit laisser **plus de traces publiques** : plus d'événements d'équipe par heure, et des régimes plus longs. |
| État présent masqué : κ | 0,07 (A′), ≈ 1,3 événement en attente par instant | Le retard seul ne crée pas d'état caché utile. Il faut que les **décisions** dépendent d'un état caché persistant. |
| Écart C_full − L4 | ≈ 72, surtout hors état caché (opérateur, convention à t0) | Le monde v2 corrige la convention à t0 et publie les décisions de l'opérateur. L'écart restant y mesure alors un vrai état caché. |
| Marge de prévision M_pub | 0,10 à 0,14 nat, structurelle | v2 garde des lois explicites et recalibrables, pour que la référence explicite reste forte. |

## Leviers (hypothèses d'ingénierie, § 5 B du programme HOWM-2)

1. **Un pôle de 6 unités** avec équipes partagées de transport et de nettoyage : des dizaines
   d'événements d'équipe par jour au lieu de 4 à 6.
2. **Des régimes qui durent un poste ou plus**, avec une durée moyenne de 8 h au lieu d'environ 6 h
   à l'entrée, et qui touchent plusieurs unités à la fois. La matrice de transition est déclarée et
   la chaîne testée comme en A.
3. **Des épisodes de 4 semaines**, avec une dérive lente de θ (marche aléatoire déclarée) et des
   changements d'effectif.
4. **Des actions dont l'effet dépend de l'état caché.** Exemple : un renfort de nettoyage n'a d'effet
   qu'en régime lent ; une coordination de transport réduit l'attente surtout en régime lent.
5. **Convention à t0 corrigée.** L'état vrai d'un instant inclut les événements de t0, comme l'état
   public. Les décisions de l'opérateur sont publiées sans retard.

## Garde-fous

- Le monde est réglé avec le filtre de référence (L4-v2) et les références explicites, **jamais
  avec un modèle appris**.
- Trois itérations de conception au plus, toutes consignées avec leurs mesures.
- Le générateur indépendant G_alt-v2 est écrit avant le gel. Il simule tout le monde v2, pas une
  seule file.
- Gel G0-v2 avant tout entraînement : générateur, a priori, partitions et réserve scellée.

## Porte G_ID, par itération, sur REF-v2 (200 établissements neufs)

1. Borne basse de M_pub ≥ δ_id = 0,02 à H6 et à H24 (règles et validation de A, addendum 2
   compris).
2. Marge décisionnelle accessible ≥ 15, sur au moins 96 instants : U(règle renforcée v2) −
   U(planificateur nourri par L4-N-v2), selon les règles de verdict de A′ (borne basse ≥ 15).
3. Témoin informatif, sans verdict : κ-v2 > 0,3, c'est-à-dire que l'état caché pèse sur la
   décision.

**Si aucune itération ne passe** : verdict `PAS_DE_MARGE_IDENTIFIABLE_A_CETTE_ECHELLE`, arrêt et
décision humaine.
