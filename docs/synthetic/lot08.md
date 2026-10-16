# Lot 08 — ruptures organisationnelles datées

Le simulateur applique maintenant des fermetures de lits, des changements de capacité
de service et des absences supplémentaires à des heures déclarées. Les changements
peuvent être temporaires ou durer jusqu'à la fin de l'année. Ils sont compatibles avec
les dynamiques du lot 07, les trois organisations de ressources et la boucle de politique.

Le calendrier complet appartient à la vérité du simulateur. Il n'est pas fourni au
recommandeur : celui-ci observe les conséquences à travers les états d'unité retardés,
avec les mêmes absences, corrections et doublons qu'au lot 06. Aucun modèle adaptatif
n'est entraîné ou évalué dans ce lot.

## Configuration et sémantique

La liste `changes` est facultative. Sans changement, la physique, les tirages et les
empreintes de configuration existantes sont conservés. Chaque entrée a un identifiant
unique et un intervalle **début inclus, fin exclue**, en heures entières UTC+01:00 fixe.
Cette convention est celle du moteur ; ce n'est pas l'heure légale de Paris avec été/hiver.

| Type | Cible | Effet durant l'intervalle |
|---|---|---|
| `bed_closure` | Une unité | Ajouter `additional_closed_beds` à la demande de fermeture de référence, dans la limite des lits standards physiques |
| `service_capacity` | Un service hospitalier : nettoyage, imagerie, transport ou avis | Multiplier la capacité de référence, puis arrondir à l'entier inférieur ; zéro permet une panne complète |
| `staffing_shortage` | Une unité | Ajouter `additional_absent` au nombre d'absents, plafonné à l'effectif prévu ; garder les remplacements existants |

```json
{
  "changes": [
    {
      "change_id": "C_BEDS_APRIL",
      "kind": "bed_closure",
      "unit_id": "U_MED",
      "additional_closed_beds": 8,
      "starts_at": "2025-04-01T07:00:00+01:00",
      "ends_at": "2025-04-29T07:00:00+01:00"
    }
  ]
}
```

Omettre `ends_at` maintient l'effet jusqu'à la borne d'extraction. Le début doit être
compris dans la période enregistrée ; la chauffe reste commune. Une fin à la borne
est valide mais ne produit pas d'événement postérieur dans les exports.

Les absences commencent et finissent aux frontières des postes du moteur hérité :
**00 h, 07 h ou 15 h**. Le lot conserve ces horaires, y compris leurs durées inégales,
pour ne pas modifier les cohortes de référence. Il n'introduit pas un planning de
salariés individualisés. Les autres changements peuvent commencer à toute heure entière.

Le validateur rejette les unités ou services inconnus, les dates non ordonnées,
les dates sans décalage explicite +01:00, les minutes/secondes, les dépassements de période,
les doublons d'identifiant et les chevauchements de même type sur la même cible.
Des changements adjacents sont admis ; la fin précédente est journalisée avant le début
suivant. Des types différents ou des cibles différentes peuvent être simultanés.

### Fermeture des lits

La fermeture est une demande d'indisponibilité suivant l'ordre historique des lits
(non spécialisés d'abord). Un lit occupé reste compté occupé et ouvert jusqu'à sa
libération ; il devient ensuite indisponible pour une nouvelle admission. Aucun patient
n'est expulsé et aucun lit n'est détruit. Les lits supplémentaires activés par la politique
ne font pas partie de la fermeture des lits standards.

L'augmentation de fermeture peut être plafonnée si des lits étaient déjà fermés.
La quantité demandée n'est donc pas nécessairement la baisse immédiate des lits ouverts.
L'état horaire permet de mesurer l'effet effectivement réalisé.

### Services et effectifs

La capacité des services est modifiée au niveau hospitalier, avant répartition entre
pôles. Les pondérations et règles de partage du lot 04 restent inchangées. Dans les pools
locaux, la capacité entière continue d'être répartie selon les crédits cumulés ; restaurer
le total ne remet pas ces crédits à zéro.

Une baisse du nettoyage bloque les nouveaux démarrages au-delà de la capacité résiduelle ;
les tâches déjà en cours se terminent. Les examens et avis commencés se terminent également.
Il n'y a pas d'annulation ou de préemption des tâches en cours, ni de remise à zéro des files.

Les absences supplémentaires ne diminuent pas les effectifs prévus et ne consomment aucun
tirage aléatoire. Les remplacements et les renforts déjà confirmés demeurent distincts.
Les absences ne réaffectent pas les salariés entre unités. Elles ne recalculent pas les
fermetures historiques faute de personnel : pour coupler les deux perturbations, déclarer
également une fermeture de lits explicite. Cette séparation évite d'inventer une règle
implicite de fermeture à chaque poste.

### Fin d'une rupture

La capacité de référence est celle qui aurait été disponible **à cette heure**, avec
son calendrier, sa maintenance, ses absences et ses facteurs de ressources. La fin restaure
cette capacité ; elle ne restaure pas l'état des patients ou les files du scénario sans
rupture. Les conséquences d'une perturbation peuvent donc persister après sa fin.

## Non-anticipation et audit

Les changements sont appliqués aux seules tranches d'aléas exogènes concernées, après
les tirages de référence et avant la création des pools. Ils ne changent ni patients,
ni calendriers, ni uniformes de politique, ni facteur de confusion `z`.

La simulation journalise `ORGANISATION_CHANGE` uniquement lors du pas correspondant à
un début ou une fin. Le payload donne le type, la cible, la portée et la quantité demandée.
Pour les services, l'événement a une portée hospitalière ; son rattachement technique
à la première unité dans le journal historique ne désigne pas une action locale.

Les exports ajoutent `truth/changes.jsonl.gz` (uniquement si `changes` n'est pas vide),
inclus dans les empreintes du manifeste. Ces événements restent dans `truth/events.jsonl.gz`.
Le calendrier complet reste dans `config.json`, avec le rôle « vérité uniquement » indiqué
au manifeste. Les vues d'apprentissage continuent d'accepter seulement les états d'unité.
Les capacités de service ne sont pas une nouvelle variable directement observée : leurs
conséquences apparaissent dans les files, les lits et la charge.

Les comparaisons vérifient l'égalité du passé jusqu'au début effectif, **borne comprise
pour le contexte de décision de début d'heure**, avant l'exécution physique de cette heure :

- états physiques, événements et décisions historiques ;
- observations reçues, valeurs, masques et provenance temporelle ;
- recommandations de la politique à règles et structure du site présentée au plugin.

Les identifiants techniques `run_id` et `sample_id` diffèrent parce qu'ils identifient des
configurations complètes différentes. Ils sont exclus de la comparaison sémantique du
passé ; aucune annonce ou description de changement n'entre dans `PolicySite`/les valeurs
observées. Le cadre simulé garde son information privilégiée historique, en particulier
le facteur `z` lié aux futures arrivées. Ce lot vérifie l'absence d'anticipation des
**ruptures organisationnelles**, pas la suppression de cette autre limite héritée.

## Exécution et cohortes

Exemple annuel avec fermeture temporaire, panne d'imagerie, pénurie d'effectifs et
baisse durable du transport :

```bash
PYTHONPATH=src python -m hospitalos.synthetic \
  --config configs/synthetic/hospital_dated_changes_v1.json \
  --output runs/synthetic/dated-changes
PYTHONPATH=src python -m hospitalos.synthetic.policy_loop \
  --config configs/synthetic/hospital_dated_changes_v1.json \
  --output runs/synthetic/dated-policy
```

Réduire `--days` sans déplacer les changements devenus hors période provoque une erreur
explicite. Il faut une configuration courte cohérente pour une fixture courte.

`StructureSpec.changes` transmet un calendrier identique aux réplications d'un hôpital
dans les registres. Les unités de ces plans ont les identifiants générés `U_00_00`, etc.
Les gardes de partition et d'ouverture du test restent ceux du lot 03. Aucun plan de
benchmark d'adaptation n'est déclaré dans ce lot : dates, intensités et familles réservées
restent à fixer dans ce protocole. Les contrefactuels de ressources du lot 04 refusent de
changer le calendrier entre leurs deux bras ; leur estimand n'est pas élargi silencieusement.

## Vérification et suite

Les tests couvrent les bornes temporelles, minuit, la restauration, les lits occupés,
les tâches en cours, les règles de composition, les exports reproductibles, l'exclusion
du calendrier des observations et la transmission aux registres.

La campagne annuelle compare une réalisation de référence et une avec quatre ruptures
pour chacune des trois organisations de ressources. Elle ajoute une année complète avec
le recommandeur à règles sur observations. Les trajectoires comparées utilisent le même
hôpital, la même graine et la même période ; ce sont des diagnostics de développement,
pas une mesure de capacité d'adaptation d'un modèle.

```bash
PYTHONPATH=src python scripts/validate_synthetic_changes.py \
  --output runs/synthetic/lot08/diagnostics
```

Preuves : [rapport](evidence/lot08_validation.md) et
[manifestes et empreintes](evidence/lot08_validation.json).

Le prochain lot proposé porte sur **les profils d'observation propres à chaque établissement** :
retards, données manquantes et pannes de transmission, avec les mêmes contrôles temporels.
Les parcours patients tels que connus, le modèle hybride, le bornage des paramètres sur
statistiques publiques et le protocole final restent ouverts. La phase 0 n'est pas clôturée.
