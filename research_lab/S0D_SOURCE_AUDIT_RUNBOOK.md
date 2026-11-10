# S0d — Audit de provenance des univers et des origines `as-of`

**10 novembre 2026 — développement en revue, sans pré-entraînement.**  
**G1 : non figé ; G2 : NO-GO ; aucune promotion scientifique.**

## 1. Ce qui est réellement présent

Le dépôt GitHub contient des **preuves historiques de cohortes synthétiques** :
- `docs/synthetic/evidence/lot03_registry_manifest.json` : registre de cohortes, sans trajectoires.
- `docs/synthetic/evidence/lot04_mechanism_registry_manifest.json` : registre par mécanisme, sans trajectoires.
- `docs/synthetic/evidence/lot05_registry_manifest.json` : registre de cohortes, sans trajectoires.
- `docs/synthetic/evidence/lot05_cohort_manifest.json` : manifeste récapitulatif indiquant **12 mondes** (4 train, 4 validation, 4 test) et un accès au test déclaré fermé.
- `docs/synthetic/evidence/lot06_simulation_manifest.json` : manifeste d'une exécution de vérité synthétique (pas une archive de données d'entrée entraînables).

Ces fichiers ne sont **pas** les répertoires complets `truth/`, `observations/` et `actions/` nécessaires à S0d. Leur présence ne qualifie pas un corpus d'entraînement : les exports natifs quatre leviers et les nouvelles vues `as-of` doivent être matérialisés sur les mêmes mondes, avec correspondance de SHA-256.

Le manifeste historique du lot 05 contient lui-même des identifiants de mondes réservés. L'inventaire de recherche **ne les retourne pas**, mais cela ne rend pas ces identifiants secrets tant que le fichier source est accessible aux agents GitHub. Les **trajectoires réservées** ne doivent jamais être montées chez les workers.

## 2. Inventaire documentaire sans ouverture des archives

```bash
cd "$HOME/hospitalos-research-lab"
git pull --ff-only
python3 -m research_lab.s0d_legacy_evidence \
  docs/synthetic/evidence/lot03_registry_manifest.json \
  docs/synthetic/evidence/lot04_mechanism_registry_manifest.json \
  docs/synthetic/evidence/lot05_cohort_manifest.json
```

`s0d_legacy_evidence.py` ne rend que les **comptages agrégés**, les rôles et le SHA-256 du manifeste. Statut : `EVIDENCE_ONLY_NO_TRAINING`, et `actual_archive_triplets_verified=0` par conception. Il ne lit aucune trajectoire ni données de test.

## 3. Contrôle d'un monde accessible, sur de vrais exports préexistants

`research_lab/s0d_source_audit.py` accepte :
- un registre `hospitalos.synthetic_world_registry_v1` préalablement gelé par le *data steward* ;
- l'identifiant d'un monde **train** ou **development** uniquement ;
- trois racines d'archives privées : vérité `truth/`, export d'observations, export des quatre actions natives du **même** monde ;
- le contrat `integrated_full_model_v1` contenant **quatre canaux**, les origines D, le cutoff d'étiquetage et la fenêtre historique.

Il exige la concordance des empreintes exactes des trois manifestes S0c, du `source_manifest_sha256`, des identités, des partitions et de l'horloge fixe UTC+01. Il vérifie également plusieurs fichiers de vérité contre leurs empreintes enregistrées, la couverture du journal à quatre leviers et la validité de la configuration de l'encodeur au **niveau des dimensions uniquement**.

Il construit, via `synthetic_adapter_v1.build_window`, les préfixes d'observations et d'actions connus à D, puis sépare les étiquettes disponibles au cutoff L. Les chevauchements entre fenêtres sont **comptés comme corrélations potentielles** ; un recouvrement au sein d'un monde train ne prouve pas une fuite train/dev. La séparation des familles de mondes est assurée séparément dans S0c, sous réserve de la sincérité du lignage déclaré.

Exemple, **uniquement lorsque les quatre chemins existent, avec manifestes vérifiés** :

```bash
python3 -m research_lab.s0d_source_audit \
  --registry /PRIVATE/s0c/world_registry.json \
  --world-id MONDE_TRAIN_APPROUVE \
  --truth /PRIVATE/synthetic/MONDE/truth \
  --observed /PRIVATE/synthetic/MONDE/observed \
  --actions /PRIVATE/synthetic/MONDE/native-actions \
  --spec /PRIVATE/s0c/model_spec_v041.json \
  --origin "2026-10-01T12:00:00+01:00" \
  --label-cutoff "2026-10-03T12:00:00+01:00"
```

Ces dates et ces chemins sont **des placeholders**, pas un jeu de données trouvé ou exécuté. Aucune autorisation implicite de dépense ou de pré-entraînement.

Le résultat reste explicitement : `SOURCE_PREFIXES_CHECKED_NOT_TRAINING_ELIGIBLE`, `trainable_supervision_verified=false`, `training=false`, `model_forward=false`. Les labels observés sous politique réelle ne sont **pas** des résultats contrefactuels sous `no_op`. Sans alignement d'une trajectoire future d'actions, aucune perte d'entraînement opérationnel n'est autorisée.

## 4. Relation avec les deux registres S0c présents dans la PR

Il existe désormais **deux interfaces complémentaires et non interchangeables** :

- `s0c_synthetic_registry.py` gèle un index de cohortes depuis le **registre canonique du générateur**, et applique notamment un embargo temporel train/dev, sans lire les trajectoires test.
- `s0c_world_registry.py` définit un **registre de trois engagements par monde** (manifestes de vérité, observations et actions), avec engagement du blind OOD.

S0d consomme actuellement la seconde interface. Le chemin de **conversion contrôlée entre l'index canonique et les trois engagements vérifiés par monde** reste à réaliser par un responsable de données privé, sans accorder aux agents l'accès aux archives test. Le résultat S0c ne doit pas être relabellisé automatiquement comme certification S0d.

## 5. Tests et limites

Le contrôle complémentaire des métadonnées multi-mondes est décrit dans
[S0D_COHORT_SEPARATION_RUNBOOK.md](S0D_COHORT_SEPARATION_RUNBOOK.md).
Il réconcilie les rôles S0c, les composantes de dépendance et les supports
temporels déclarés, sans ouvrir d'archives. Son succès reste
`CONSISTENT_METADATA_ONLY` : il ne certifie ni le lignage réel, ni les sources,
ni la séparation avec les partitions réservées.

```bash
python3 -m pytest -q tests/test_s0d_source_audit.py
```

Ce test crée un monde synthétique **miniature et fictif** (manifestes, événements, topologie et actions à quatre leviers), valide l'intégrité de la triplette d'archives, détecte les fenêtres corrélées, rejette les falsifications et bloque les mondes de validation/test **avant toute lecture d'archive**.

Limites non résolues : absence de triplets réels vérifiés ici, absence d'audit multi-mondes et de contrôle temporel intrahospitalier sur une vraie cohorte, aucune signature indépendante des reçus, aucune preuve de réalisme, aucune tâche adaptative des agents. Le code S0d lui-même ne lance ni simulation, ni forward, ni entraînement ; les workflows CI préexistants du dépôt peuvent exécuter leurs propres tests.

**Prochaine barrière avant G2 :** matérialiser les trois archives pour au moins un monde train et un monde development, geler leurs engagements via data steward, contrôler les origines et auditer un flux de supervision actionné qui ne confond pas action factuelle et scénario contrefactuel.
