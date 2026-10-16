# Lot 09 — profils d’observation par établissement

Un hôpital peut maintenant produire des états d’unité avec ses propres délais,
pertes d’information, sous-documentations, corrections et doublons. Des pannes
de transmission affectent tout l’hôpital ou une liste d’unités. Le même profil
s’applique au rejeu hors ligne et au recommandeur dans la boucle.

Ces profils sont des hypothèses de simulation, non calibrées sur un SI réel.
Ils préparent les essais de robustesse et de transfert ; ce lot n’entraîne aucun modèle.

## Configuration

Le champ facultatif `observation` appartient à `HospitalConfig` et `StructureSpec`.
Sans ce champ, le mode `v041` conserve les tirages, observations et empreintes de
configuration précédents. Les paramètres personnalisés nécessitent `mode: site_v1` :
le validateur refuse les options qui seraient ignorées par le moteur historique.

```json
{
  "observation": {
    "mode": "site_v1",
    "missing_probability": 0.05,
    "recording_delay_median_minutes": 30.0,
    "outages": [{
      "outage_id": "OUTAGE_MED",
      "starts_at": "2025-10-01T00:00:00+01:00",
      "ends_at": "2025-10-03T00:00:00+01:00",
      "unit_ids": ["U_MED"]
    }]
  }
}
```

| Paramètres de `site_v1` | Sens |
|---|---|
| `missing_probability`, `load_missing_multiplier` | Perte définitive d’un état horaire complet ; probabilité multipliée sous tension, plafonnée à 1 |
| `recording_delay_median_minutes`, `recording_delay_sigma`, `load_delay_multiplier` | Délai de saisie lognormal, multiplié sous tension ; médiane nulle pour une saisie immédiate |
| `ingestion_delay_min_minutes`, `ingestion_delay_max_minutes` | Délai uniforme entre saisie et ingestion prévue |
| `availability_delay_minutes` | Latence après ingestion avant utilisation |
| `ready_documented_probability`, `downstream_documented_probability` | Part binomiale des sortants médicaux et patients en attente d’aval documentés |
| `charge_noise_sigma` | Bruit multiplicatif lognormal sur la charge observée |
| `revision_probability`, `revision_delay_min_h`, `revision_delay_max_h` | Erreur de ±1 lit occupé en version 1, puis correction version 2 après un délai uniforme depuis la saisie initiale |
| `duplicate_probability` | Nouvelle réception de la version 1, au contenu source identique, ingestion prévue deux minutes plus tard |
| `outages` | Intervalles de blocage de l’ingestion et de la disponibilité |

La tension est définie, côté simulateur, par des minutes de soins non couvertes.
Elle peut rendre l’information moins complète et plus lente : la perte n’est donc
pas supposée indépendante de l’état hospitalier. Ce signal privé ne devient pas
une nouvelle colonne observée.

La correction porte seulement sur l’erreur d’occupation introduite en version 1.
Elle ne rétablit ni les patients sous-documentés ni la charge vraie. Comme dans
le contrat précédent, un état observé peut être incohérent avec la conservation
physique des lits : cette conservation est vérifiée sur la vérité du simulateur.

## Temps, pannes et provenance

Les quatre horloges conservent l’ordre **événement ≤ saisie ≤ ingestion ≤ disponibilité**.
L’état physique étiqueté `h` décrit la fin de l’intervalle `[h, h+1)` ; son événement
observable commence à `h+1`. Les observations arrivant après l’extraction sont exclues.

Une panne utilise un intervalle **début inclus, fin exclue**, en heures entières
UTC+01:00 fixe. Les unités omises signifient « tout l’hôpital ». Les unités inconnues,
dates hors période enregistrée, identifiants répétés et chevauchements sur une même
unité sont rejetés. Deux fenêtres adjacentes se prolongent sans reprise intermédiaire.
La chauffe précède les pannes déclarées.

Les messages dont l’ingestion ou la disponibilité tombe pendant une panne sont
retenus jusqu’à sa fin. Cela inclut les versions initiales, corrections et doublons,
ainsi que les messages ingérés juste avant la panne mais pas encore disponibles.
La date de l’événement et la date de saisie d’origine restent conservées. La reprise
vide le retard sans limitation de débit dans cette version ; un engorgement du SI
au redémarrage n’est pas encore simulé. Une panne ne supprime pas les messages :
la perte définitive relève de `missing_probability`.

Le flux aléatoire de `site_v1` est indexé par graine, unité et heure d’événement.
Il ne dépend ni de l’ordre de traitement, ni des identifiants batch/direct, ni du
calendrier des pannes. Ajouter une panne future ne modifie pas les observations
déjà disponibles. Les corrections tardives ne remplacent pas un état plus récent,
et un doublon ne rafraîchit pas artificiellement l’ancienneté d’un état.

Les paramètres complets et le calendrier sont conservés dans les configurations
et manifestes pour l’audit. Ils ne sont pas transmis dans `PolicySite` ni dans les
valeurs du contexte de décision. Les identifiants `run_id` et `sample_id` changent
avec la configuration complète ; les contrôles de non-anticipation comparent les
valeurs, masques et sources temporelles en excluant ces identifiants techniques.
Les modèles doivent utiliser les seules entrées autorisées, pas les manifestes.

## Physique, politique et cohortes

Le profil ne modifie aucun tirage ou mécanisme physique. À politique indépendante
des observations, changer le profil conserve exactement états, événements, actions
et ressources. Cette propriété est testée pour les trois organisations de ressources.

En boucle fermée, des observations dégradées peuvent changer les recommandations,
puis les décisions et les trajectoires. Il serait incorrect d’exiger l’égalité
physique de ces deux exécutions. Le recommandeur à règles conserve son abstention
sur information manquante ou vieille de plus de six heures. L’évaluation affiche
la couverture et des erreurs nulles au sens JSON (`null`), sans score artificiel
de zéro lorsqu’aucune prédiction n’est disponible.

Dans une cohorte, `StructureSpec.observation` se transmet aux configurations des
hôpitaux et reste identique entre leurs réplications. Des spécifications différentes
peuvent déclarer des profils différents. Les paramètres de qualité ne sont pas
encore tirés dans une distribution propre à chaque hôpital. Ce lot n’introduit
pas d’axe de réservation « observation », ni de nouveau protocole G4. Les réservations
de structures et mécanismes existantes restent inchangées.

## Exécuter

Trois configurations annuelles de développement partagent la même structure,
graine, période et politique physique :

- `hospital_observation_fast_v1.json` : saisie rapide et faible perte ;
- `hospital_observation_delayed_v1.json` : saisie lente, plus de pertes et de sous-documentation ;
- `hospital_observation_intermittent_v1.json` : panne hospitalière de 48 h en avril,
  puis panne de 48 h de `U_MED` en octobre.

Ces exemples sont des scénarios contrastés d’ingénierie, pas trois catégories
d’établissements empiriquement validées.

```bash
PYTHONPATH=src python -m hospitalos.synthetic \
  --config configs/synthetic/hospital_observation_intermittent_v1.json \
  --output runs/synthetic/observation-truth
PYTHONPATH=src python -m hospitalos.synthetic.learning \
  --source runs/synthetic/observation-truth \
  --output runs/synthetic/observation-asof
PYTHONPATH=src python -m hospitalos.synthetic.policy_loop \
  --config configs/synthetic/hospital_observation_intermittent_v1.json \
  --output runs/synthetic/observation-policy
```

Réduire la durée d’une configuration impose de déplacer les pannes devenues
hors période ; le validateur les refuse explicitement. Le profil historique
`v041` garde son ancienne panne et ses anciennes règles. Les garanties nouvelles
de blocage de toutes les réceptions concernent `site_v1`.

## Validation et suite

```bash
PYTHONPATH=src python scripts/validate_synthetic_observations.py \
  --output runs/synthetic/lot09/diagnostics
```

La campagne recalcule indépendamment trois années, vérifie l’égalité des fichiers
de vérité et produit trois jeux d’observations. Une quatrième année utilise la
politique sur observations avec pannes. Les contrôles portent sur les horloges,
la conservation physique, le rejeu direct/hors ligne et les empreintes des fichiers.
Preuves : [résultats](evidence/lot09_validation.md),
[rapport machine](evidence/lot09_validation.json).

Le périmètre reste celui des états d’unité agrégés. Les admissions, mutations,
sorties et notes patient ne sont pas encore exposées par ce nouveau flux. La suite
proposée est **le contrat de parcours patient tel que connu**, avant un encodeur
de séjour. Le bornage sur statistiques publiques, les styles documentaires,
la distribution complète des profils et le protocole final restent ouverts.
La phase 0 et la porte SYN ne sont pas clôturées.
