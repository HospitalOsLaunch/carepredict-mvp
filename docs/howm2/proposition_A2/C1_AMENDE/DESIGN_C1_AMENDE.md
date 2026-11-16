# C1 amendé — Conception (remplace `proposition_BCD/DESIGN_HOWM2_C1.md`)

## Changements par rapport à la proposition C1 non adoptée (§ 6 du programme A′)

1. **C.2 scindé en deux variations, chacune isolée par rapport à C.1.** La proposition précédente
   reposait sur une prémisse fausse : H1 n'utilise **aucune** statistique de fenêtre (fait vérifié
   en A′). Donner à C.2 les statistiques de L2 ajoutait donc des entrées en plus du contexte long.
   - **C.2a, contexte long seul.** Le même encodeur H1 (GRU sur graphes horaires) est appliqué à
     toute la séquence horaire publique depuis l'heure 0, au lieu des 24 dernières heures. Ni
     entrée, ni tête, ni dimension ne change.
   - **C.2b, statistiques explicites seules.** H1 garde W = 24 h. On ajoute en entrée de la tête de
     lecture les 8 intercepts locaux de L2, calculés sur tout le passé public. C'est la
     configuration « correction au-dessus de L2 ». Battre L2 y est **attendu** : la lecture
     principale en est donc ρ, et non le critère (point 3).
2. **Référence du critère** : la meilleure de {L2, L2c}. D'après A2.L2C, c'est L2 à H6 et à H24.
   M_pub vaut 0,099 et 0,141, au-dessus de δ_id : C1 peut départager.
3. **Lecture principale** : ρ par famille, à côté du critère « battre la référence ». ρ_f =
   (L_ref − L_modèle)/(L_ref − L4) sur les familles validées en A (ready, confirmation, présence,
   arrivées, soins) ; transport et nettoyage sont rapportés à titre descriptif.
4. **Budget par paliers.**
   - Palier 1 : 100 et 1 000 établissements, 3 graines par système.
   - Palier 2 : 10 000 établissements, lancé **seulement si** la perte CVAL moyenne baisse entre
     100 et 1 000 de plus que deux fois l'écart-type entre graines, pour au moins un système.
   - Cette règle est une échelle de réduction déclarée, non une question nouvelle.

## Inchangé par rapport à la proposition C1 précédente

- Flux neuf `HOWM2_CTRAIN` vu en un seul passage, avec `HOWM2_CVAL` (48) et `HOWM2_CEVAL` (200),
  clés `key("HOWM1", part, i)`.
- Origines `range(24, 166, 3)` partout.
- Optimiseur, lot, têtes et échelles s_f de R1 ; lr = 3e-4.
- Perte d'entraînement journalisée.
- Gel F-C1 avant toute lecture de CEVAL.
- Transfert sans réentraînement vers `HOWM2_DIAG`.
- Pas de diagnostic décisionnel sur HOWM-1 (A : marge < 15 ; A′ : κ ≈ 0,07).

## Systèmes, une variation à la fois

| Système | Contexte | Statistiques L2 en entrée | Facteur isolé |
|---|---|---|---|
| C.1 | 24 h | non | données |
| C.2a | tout le passé | non | contexte |
| C.2b | 24 h | oui | correction explicite |

## Issues et lecture

| Issue | Lecture |
|---|---|
| C.1 bat la référence, ρ ≥ 0,5 | Le facteur limitant de R1 était la donnée. |
| Seul C.2a passe | Le contexte long (inférence de θ) est nécessaire. |
| Seul C.2b passe | Le réseau apprend une correction résiduelle au-dessus de L2 ; ρ dit ce qu'il capte de la marge structurelle. |
| Aucun ne passe ; perte CVAL plate entre 100 et 1 000 | La famille H1 n'apprend pas ces lois ; le palier 2 n'est pas lancé. |
| Gain en REF, pas en DIAG | Le modèle a appris la population REF, pas le mécanisme commun. |
