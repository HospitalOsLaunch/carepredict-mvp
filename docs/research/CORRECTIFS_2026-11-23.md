# Correctifs du 23 novembre 2026 (revue des commits du 20 novembre)

Revue : `50228ee..519220f`. Les correctifs portent sur le code ; **aucune campagne n'a été relancée**.
Les preuves archivées le 20 novembre restent en place comme trace des résultats obtenus avec le code
antérieur.

| Défaut | Fichier | Correctif | Test | Preuves concernées |
|---|---|---|---|---|
| Séjour dont la fin de transport (ou la mise en état de sortie, sans transport) est publique mais pas le départ : lit occupé pendant toute la projection | `src/hospitalos/howmint/world.py` (`to_engine_n`) | départ impliqué au moment connu : lit sale, séjour retiré du service transport ; séjours avec transfert ou attente d'aval inchangés | `tests/howm_int1/test_world.py` I11–I13 | toutes les vues publiques sous retard (filter_validation, filter_correction, filter_pipeline, action_effects, plan48) : files et blocages vraisemblablement surestimés ; ampleur non mesurée |
| Transport inféré sans demande : seconde demande habituelle possible | même fichier | demande et acceptation datées au début inféré | I14 | idem |
| Bras « legacy » n'était pas l'ancien comportement (héritait de la nouvelle reconstruction du transport) | `scripts/filter_validation/correction.py` | `LegacyPublicStream.to_engine_n` = reconstruction d'avant correction | `test_correction.py` | `evidence/filter_correction` : écarts « legacy − public » sous-estimés |
| Tirages de projection identiques entre hôpitaux | `scripts/plan48/sim.py` | clé incluant l'hôpital ; amendement `scripts/plan48/AMENDMENT_A1.md` | `scripts/plan48/test_sim.py` | `evidence/plan48` : sélection DEV à recalculer avant toute lecture TEST |
| `W.ROSTER_HOURS` modifié globalement sans restauration | `scripts/filter_pipeline/longitudinal.py` | valeur restaurée après la création du moteur | — (changement local) | aucune si un seul épisode par processus |
| Docstring de l'ordre intra-tick inexacte | `world.py` (`_bed`) | ordre réel documenté | — | aucune |

**Résultats INT-1** (campagne du 18 novembre) : produits avec le code du commit `7af2e10` (archive
`HOWM_INT1_FINAL`), avant les changements du 20 novembre ; ils ne sont pas modifiés. Pour les rejouer,
se placer sur ce commit.
