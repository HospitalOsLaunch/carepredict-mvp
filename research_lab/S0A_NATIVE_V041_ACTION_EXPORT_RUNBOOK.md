# S0a — Exporteur d'actions du même univers hospitalier synthétique (V0.4.1)

**10 novembre 2026 — code implémenté, tests fictifs sans ML. G2 NO-GO.**

## Périmètre et distinctions

L'univers hospitalier V0.4.1 enregistre quatre leviers binaires demandés par unité à 09 h : anticipation_sorties, lits_supplementaires, renfort_soignant, acceleration_aval. Le simulateur RS-JEPA Phase A produit deux variables continues différentes, staffing_delta et discharge_delta. Ces deux contrats ne sont jamais mélangés. Pour V0.4.1, make_v041_synthetic_spec() expose quatre canaux et Stage1Config(action_dim=4) sera nécessaire ultérieurement.

L'exporteur research_lab/synthetic_action_export_v041.py lit les fichiers archivés manifest.json, config.json et truth/events.jsonl.gz d'une simulation déjà existante. Aucune simulation ou inférence n'est lancée. Il vérifie les SHA-256, la partition (train/development/validation), l'identité de l'établissement et les comptes d'événements; puis exige exactement une décision par unité et par jour à 09 h, avec quatre valeurs binaires et un horodatage cohérent.

Après cette preuve de complétude seulement, il produit un vecteur hospitalier par heure : quatre **nombres de décisions demandées**. Les autres heures sont explicitement à zéro parce que la règle de décision du simulateur et sa grille complète ont été vérifiées; une décision absente à 09 h provoque un refus. Les actions demandées ne valent ni exécution réussie, ni dose effective, ni effet causal identifié.

Les décisions au début de l'heure h sont attribuées à l'intervalle [h,h+1) et considérées disponibles **conservativement à h+1**, avec la même horloge fixe UTC+01 que les observations V0.4.1. Cette convention est une hypothèse d'observation du système synthétique, pas une latence SIH mesurée.

## Artefacts et origine commune

L'exporteur écrit dans un nouveau répertoire privé : manifest.json et actions/intervals.jsonl.gz. Le manifeste contient le SHA-256 exact du manifeste de vérité physique, le profil des actions et la preuve de couverture. L'adaptateur synthetic_adapter_v1_files rapproche cette empreinte de celle de l'export des observations hospitalières du **même run**. Les fichiers de vérité initiaux ne sont ni modifiés ni rejoués.

## Test hors ML

Depuis la branche research/lab-runtime-2026-11 :

    python3 -m research_lab.synthetic_action_export_v041_smoke

Le test fabrique uniquement deux événements de décision en mémoire, vérifie 24 intervalles et ne charge ni moteur hospitalier, ni modèle, ni GPU. La CI dédiée inclut tests/test_synthetic_action_export_v041.py, qui contrôle la complétude, les duplications, les incohérences d'horodatage, les valeurs non binaires, le refus du holdout et le rapprochement d'archives fictives.

## CLI pour une ancienne vérité synthétique déjà archivée (non lancée ici)

    python3 -m research_lab.synthetic_action_export_v041 --truth /CHEMIN/VERITE_SYNTHETIQUE --output /CHEMIN/NOUVEL_ARCHIVE_ACTIONS

Ce traitement documentaire ne doit jamais cibler des données hospitalières réelles ou un jeu de test réservé.

## Limite à lever avant le pré-entraînement intégré

L'adaptateur prépare des observations et des actions historiques, mais ne fournit **pas** un calendrier d'actions futures réellement connu au moment D. Les cibles futures factuelles peuvent incorporer des décisions prises après D. Elles ne doivent pas être utilisées comme vérités contrefactuelles sous action_mode=no_op. Le verrou supervision_alignment.training_loss_authorized=false est maintenu. Il faudra définir un apprentissage conditionnel sur les futures actions factualisées (teacher forcing limité à l'entraînement) ou des scénarios contrefactuels synthétiques appariés, séparément évalués.

**Verdict : S0a code + fixtures; aucune campagne synthétique réelle exécutée; G2 NO-GO; pas de modèle pré-entraîné.**