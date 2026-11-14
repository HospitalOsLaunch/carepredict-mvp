# P5 — P5-PROTO-3.1 : révision de raccordement de P5-PROTO-3 (proposition, non approuvée)

**Version :** P5-PROTO-3.1, 14 novembre 2026. **Statut : `PROPOSED_NOT_APPROVED`.**
Paramètres concordants : `P5_PROTOCOL_PARAMS_v3_1.json`. Base : P5-PROTO-3
(`P5_PROTOCOL_v3.md` `dbf517ca…6ab6`, `P5_PROTOCOL_PARAMS_v3.json` `653a426a…18ac`), conservé
intact. P5-PROTO-3.1 = P5-PROTO-3 + les révisions R1 à R5 ci-dessous, qui remplacent les passages
cités. Rien d'autre ne change : question scientifique, métriques, δ = 15, seuils, tailles, grille,
plafonds (1200 s au total, P5.4 = 470 s, 30 s par commande, 0 €), P6 fermé, moteur v6 inchangé.
Aucune approbation antérieure (D1–D12 sur v2) n'est transférée à v3 ou v3.1.

Origine : revue statique de la reprise (R-P5-01 à R-P5-03, note éditoriale) et prompt de
finalisation du 14 novembre 2026.

## R1 — Couple (version Python, gel) (remplace A9.1 et précise D3)

L'environnement approuvé est un **couple** : Python **3.11.18** et le gel `bf540981…b6da`.
- **Avant lancement**, le compteur compare le chemin exact de l'interpréteur, puis le couple
  (version déclarée par l'environnement virtuel, empreinte du gel).
- **Dans le processus exécutant**, avant toute opération scientifique (pilote, futur
  chronométrage), un contrôle compare le couple réel (`sys.version`, distributions installées).
- Un écart entraîne un refus.
- Une approbation post-installation (note `environment_approved`) doit nommer **les deux**
  éléments. Une note sans version Python est ignorée : approuver des dépendances ne change jamais
  Python implicitement.

## R2 — Refus journalisés (complète A9.1)

Tout refus du compteur est consigné au registre à 0 s, avec le lot demandé et la raison : lot non
autorisé, interpréteur non autorisé, couple non approuvé, plafond atteint. Le registre est validé
d'abord. Un registre absent ou corrompu bloque l'exécution et ne relance jamais la genèse.

## R3 — Abstentions et arrêts (remplace v2 § 3 « Abstentions », A9.4 et le JSON `population.abstentions`)

- **Évalués comme HABITUAL-1 et comptés** :
  - `NO_ACTION_PREFERRED` (le plan habituel est choisi) ;
  - `INSUFFICIENT_DATA` ;
  - `HYPOTHETICAL_ONLY` ;
  - `INVALIDATED` ;
  - une infaisabilité pour une raison absente de la liste d'arrêt ci-dessous (par exemple un
    horizon non supporté).
- **Arrêt avec reçu d'échec, jamais une abstention** :
  - `habitual_practice_invariant_failure` signalé par la v6 ;
  - toute violation d'admissibilité ou d'invariant sous la vérité ;
  - un univers modifié entre réalisations ;
  - un plan recommandé hors de l'univers public.

## R4 — Pilote P5.2 complété et L2 (remplace le contenu normatif de `budget.lots.P5.2_timed_pilot` et le texte L2)

- **Déjà exécuté, compté une seule fois** : pilote de chronométrage sur 20 parents de
  développement, sans ajustement (registre n° 9, 2,024 s). Il n'est pas relancé.
- **Reste du pilote (normatif)** : le banc A5 seul, soit **6 ajustements de chronométrage**
  (M_agg et M_ent × `random_state` 0, 1, 2), configuration `max_depth` 5, `learning_rate` 0,1,
  `max_iter` 400, sur 1440 lignes de développement tuilées, `OMP_NUM_THREADS=1`, modèles jetés.
  Il se tient dans le reliquat de P5.2 (37,476 s), à 30 s par commande, et exige D13, D14 et D15.
  La mention historique de v2, « 2 ajustements les plus coûteux », est remplacée ; elle n'a
  jamais été exécutée.
- **L2**, si le banc A5 montre l'identité entre graines pour les deux familles : **28
  ajustements P5b**, soit 24 de sélection avec `random_state` 0 et 4 contrôles inter-graines
  (graines 1 et 2 sur la configuration retenue de chaque famille). Les 6 ajustements du banc A5
  ne sont **pas** comptés dans ces 28. Sans L2 : 72 ajustements.

## R5 — Note éditoriale

Le README du paquet de reprise précédent annonçait « 3 commits » : il contenait deux patchs
(`[PATCH 1/2]`, `[PATCH 2/2]`) sur la base `97c23a0e73ad6b3a332deb1ea14508f5f720b5b8`. Le paquet
précédent n'est pas modifié ; le nouveau paquet donne le nombre exact de patchs et la base.

## Décisions demandées (aucune n'est prise ici)

D13 (approuver P5-PROTO-3 + 3.1 par leurs empreintes), D14 (= D4, installation isolée), D15 (banc
A5). D16 ne s'applique pas avant le résultat A5. (ii) et (iii) restent séparées, après F_a et
F_b.
