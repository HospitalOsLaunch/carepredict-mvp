# S0c — Registre d'exposition synthétique pour le pré-entraînement

**10 novembre 2026. Statut : code de registre + tests hors ML, aucune génération ni entraînement.**
**G1 : non figé ; G2 : NO-GO ; aucune promotion scientifique.**

## But

Construire une vue **métadonnées uniquement** à partir du registre de cohortes existant
(`src/hospitalos/synthetic/cohort.py` et `registry.py`), sans créer de deuxième
système de génération ou mélanger des mondes incompatibles.

Le registre canonique contient déjà des mondes `train`, `validation` et `test`,
séparés selon un axe de génération déclaré : `structure`, `mechanism`,
`arrivals`, `discharges`, `staffing`, `staff_forecasts` ou
`downstream_confirmation`. S0c utilise l'axe enregistré par le registre ;
il ne prétend pas démontrer l'OOD en général.

## Contrat de partitions pour les agents

| Vue exposée | Origine | Usage |
|---|---|---|
| `train` | Mondes de la partition canonique `train` | Intervalles d'origines admissibles pour un futur pré-entraînement autorisé |
| `development_temporal` | Même monde que `train`, mais autre plage temporelle avec embargo | Vérifier le transfert temporel **non indépendant du site** |
| `development_ood` | Mondes de `validation` séparés selon l'axe réservé | Validation OOD **dans la famille de scénarios prévue par le plan** |
| `test` | **Non exposé** au worker | Évaluation finale séparée, hors adaptation des hyperparamètres |

Le registre canonique d'origine contient des métadonnées `test` et les
plans de cohortes existent dans GitHub. La vue S0c **ne cache donc pas
cryptographiquement les paramètres des mondes réservés à un agent qui
conserve aussi accès au dépôt ou à la source canonique**. Le vrai verrou
des trajectoires/labels réservés exige un exécuteur à droits minimaux,
qui ne reçoit que l'index redigé et pas le répertoire canonique.

## Séparation des fenêtres

Soit `C=history_steps`, `H=max(horizons_hours)`, `E=embargo_hours`,
et `D` le début de la plage de développement temporel.

Les dernières origines d'entraînement sont limitées à
`t_train_max = D - C - H - E`, de façon que
`[t_train - C + 1, t_train + H]` et
`[t_dev - C + 1, t_dev + H]` ne se chevauchent pas.

Pour le protocole d'exemple, `C=168 h`, `H=24 h`,
`E=24 h` et la validation temporelle occupe les 28 derniers jours.
Les plages sont calculées dans chaque monde entraînable, sans ouvrir
les trajectoires ni charger de labels. Si les plages sont vides, S0c refuse.

Les mondes OOD ont des identifiants hospitaliers distincts,
des graines distinctes et un axe de génération disjoint.
Le lecteur réévalue ces invariants à chaque chargement.

## Artefacts et niveaux de preuve

Entrée, **produite et vérifiée préalablement** par le code canonique :

```text
<registry-source>/registry.json
<registry-source>/manifest.json
```

Sortie S0c, sans fichier de trajectoires :

```text
<private-s0c-exposure>/index.json
<private-s0c-exposure>/manifest.json
```

Lors de `freeze`, l'outil appelle `hospitalos.synthetic.cohort.load_registry`.
Ce validateur vérifie notamment le plan déterministe, les collisions de
structures et de graines, le runtime et l'empreinte du code source.
Le gel ne génère aucune simulation.

`index.json` contient seulement les trois vues de développement, leurs
empreintes de configuration, dimensions temporelles et états de sécurité.
`manifest.json` contient l'engagement sur le registre canonique, le SHA-256
de l'index et le **nombre agrégé** de mondes réservés, sans leurs identifiants.

Le lecteur `inspect` exige une empreinte d'index **épinglée indépendamment**
par l'opérateur. Un manifeste et un index conservés ensemble ne forment
pas à eux seuls une preuve de non-altération contre un acteur disposant
d'accès en écriture sur les deux fichiers.

Ce gel de métadonnées ne qualifie ni réalisme clinique, ni labels
futurs, ni cohérence de l'adaptateur observations/actions, ni validité
des poids. `training_allowed=false`, `simulation=false` et
`model_forward=false` sont des engagements explicites.

## Vérifier sans PyTorch, simulation, ni GPU

```bash
cd "$HOME/hospitalos-research-lab"
git pull --ff-only
python3 -m research_lab.s0c_registry_smoke
python3 -m pytest -q tests/test_s0c_synthetic_registry.py
```

Ces tests construisent un **registre fictif**, pas un registre canonique
validé pour l'entraînement. Résultat attendu du smoke :
`PASS_S0C_METADATA_ONLY_SMOKE`.

## Geler un registre canonique existant (uniquement si celui-ci est disponible)

La commande suivante **ne génère aucun hôpital** mais demande les dépendances
Python nécessaires au validateur canonique `hospitalos.synthetic` :

```bash
python3 - <<'PY'
import json
from pathlib import Path
from research_lab.integrated_full_model_v1_contract import make_v041_synthetic_spec
Path('v041_model_spec.json').write_text(
    json.dumps(make_v041_synthetic_spec(), indent=2) + '\n',
    encoding='utf-8',
)
PY

python3 -m research_lab.s0c_synthetic_registry freeze \
  --canonical-registry /CHEMIN/PRIVE/registre-fixe \
  --model-spec v041_model_spec.json \
  --output /CHEMIN/PRIVE/s0c-exposure \
  --temporal-dev-days 28 --embargo-hours 24
```

Une fois l'empreinte SHA-256 de l'index examinée et **stockée hors
du répertoire S0c dans une configuration contrôlée par l'opérateur**,
la vérification du worker se fait ainsi :

```bash
python3 -m research_lab.s0c_synthetic_registry inspect \
  --index /CHEMIN/PRIVE/s0c-exposure \
  --expected-index-sha256 "$SHA256_EPINGLE_PAR_OPERATEUR"
```

Il n'est pas sûr d'extraire ce SHA uniquement du manifeste adjacent à
l'instant de l'inspection et de qualifier cela de preuve indépendante.

## Bloquants avant le pré-entraînement

1. Geler un véritable registre canonique et qualifier les sources
   observations/actions **du même monde** et leurs horodatages as-of.
2. Définir la perte et les trajectoires d'action **futures factuelles**
   sans scorer un scénario hypothétique `no_op` comme s'il avait été observé.
3. Valider séparément les formes numériques/gradients du modèle intégré.
4. Autoriser explicitement une enveloppe d'essais synthétiques et un
   worker persistant sécurisé, avec limites de calcul vérifiables.
5. Garder les trajectoires/labels `test` hors d'accès du worker pendant
   l'adaptation et les expériences répétées.

**Décision : `S0C_SOURCE_IMPLEMENTED_FIXTURE_TESTED` ;
`CANONICAL_SOURCE_FREEZE_NOT_PERFORMED` ; `G2_NO_GO`.**
