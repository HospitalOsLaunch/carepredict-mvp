# Lot 12 — charge observée, prévisions de sortie et besoins d’aval

Ce lot ajoute une vue documentaire par séjour, jointe aux lignes patient du
lot 11. Elle expose les évaluations de charge, dates de sortie prévues,
destinations demandées, demandes d’aval et aides à domicile **telles que connues
à l’heure de décision**. Elle ne détermine pas la présence du patient et ne change
ni la physique, ni les recensements, ni les cibles de sortie.

## Informations disponibles

| Groupe | Valeurs observées | Limite d’interprétation |
|---|---|---|
| Évaluation de charge | Minutes de soins de base sur 24 h, dépendance 1–4, mobilité autonome/aide/brancard | Proxy synthétique non SIIPS ; ni charge horaire effective, ni soins réellement délivrés |
| Sortie prévisionnelle | Jour prévu relatif au début de l’année enregistrée, jours restants, dépassement de la date | Prévision de l’équipe, pas date de sortie réalisée |
| Destination demandée | Domicile, SMR, EHPAD ou transfert | Orientation documentée, pas destination finale |
| Aval | Demande, annulation ou confirmation ; destination SMR/EHPAD ; identifiant de demande | Une confirmation ne clôture que sa demande identifiable |
| Aide à domicile | Demandée ou organisée | Pas de délai d’attente inventé si la demande manque |

Chaque valeur sélectionnée conserve son événement, sa version, sa source,
son unité déclarante, sa date de fait, sa disponibilité et son ancienneté.
Le masque `stale` s’applique séparément à chaque groupe. Une prévision récente
ne rafraîchit donc pas une ancienne évaluation de charge.

Un groupe manquant vaut `null`, pas zéro ni faux. En particulier, l’absence
de demande d’aval reçue n’indique pas l’absence de besoin. Les groupes ne sont pas
tous attendus pour tous les patients : leur taux de présence ne constitue pas
un score de qualité clinique.

## Source et génération des observations

L’adaptateur sélectionne huit types déjà émis par le journal physique :
`EVALUATION_CHARGE`, `DATE_SORTIE_PREVISIONNELLE`, `DESTINATION_DEMANDEE`,
`DEMANDE_AVAL`, `DEMANDE_AVAL_ANNULEE`, `PLACE_AVAL_CONFIRMEE`,
`AIDE_DOMICILE_DEMANDE` et `AIDE_DOMICILE_ORGANISEE`.

Le contrat fermé `CareDelivery` n’accepte que les champs nécessaires. Il ne
projette ni date médicale latente, ni départ réalisé, ni destination finale.
Le champ `revision` du staff n’est pas utilisé pour déduire des messages qui
n’auraient pas été reçus : les compteurs de mises à jour viennent exclusivement
des événements disponibles. Les événements du pas `[h,h+1)` deviennent des faits
à sa borne `h+1`, comme dans les autres flux.

`OnlineCare` reçoit les lots horaires du journal, sans lire les structures
internes des patients ni les événements futurs. Il attribue les identifiants
de demandes d’aval à la source, avant les éventuelles pertes de transmission.
L’événement de demande fournit son propre identifiant ; les confirmations et
annulations ultérieures sont reliées à la dernière demande correspondante.
Une confirmation de type incompatible reste sans lien certain.

L’observation utilise des tirages indépendants de la physique, des mouvements et
des recensements, mais les paramètres d’observation du même établissement :
pertes, délais, bruit de charge, corrections, doublons et fenêtres de panne.
Le bruit multiplicatif de charge reste présent après une correction. Les erreurs
de saisie simulées portent sur la charge (+20 % avant correction) ou sur la date
prévue (+1 jour avant correction). Les corrections ne remplacent jamais une
prévision par la date de sortie réalisée. Annulations et autres corrections
acceptées par le contrat sont également testées avec des messages construits.

## Reconstruction et demandes d’aval

`CareAsOfCursor.advance(hour, deliveries)` valide tout le lot avant de modifier
son état : horloges, hôpital, unité, source, identité et contenu des versions.
Les faits sont ensuite reconstruits selon leur date et leur ordre source.

- Une correction tardive d’une ancienne prévision ne remplace pas une nouvelle
  prévision plus récente. Une annulation restaure, si elle existe, la précédente
  valeur encore valide. Les lignes déjà produites restent inchangées.
- Une correction de saisie ne compte pas comme une nouvelle révision du staff.
  `plan_updates_known` et `destination_updates_known` comptent les événements
  valides distincts après le premier ; `corrected_events_known` compte les
  événements dont une version corrective est connue, annulations comprises.
- Une prévision dépassée reste négative dans `planned_days_remaining`, avec
  `plan_overdue=true`. Une prévision au-delà du 31 décembre est autorisée :
  c’est une annonce disponible, pas une révélation du devenir d’un séjour censuré.
- Une nouvelle demande d’aval remplace le contexte de demande courant et remet
  son ancienneté à zéro. Une ancienne confirmation, une destination incompatible
  ou un message non relié ne peut pas clôturer cette nouvelle demande.
- Une confirmation reçue sans sa demande conserve une demande manquante et une
  durée d’attente `null`. Si la demande arrive ensuite, la reconstruction peut
  rétablir le lien. Les événements non appariés sont comptés explicitement.
- Une annulation ou confirmation met fin à l’attente documentée. L’annulation
  n’affirme pas que le patient n’aura plus besoin d’aval ; une nouvelle demande
  peut suivre. Un changement de destination seul n’annule pas une demande.

L’aide à domicile utilise le dernier statut connu ; le moteur actuel ne décrit
pas plusieurs épisodes concurrents d’aide pour un même séjour.

## Jointure avec les présences et cibles

`CareAsOfCursor.for_patient(patient_row)` enrichit uniquement une ligne active
déjà reconstruite, au même instant, dans le même hôpital et la même partition.
Une évaluation reçue n’ouvre pas un séjour, ne rétablit pas une présence inconnue,
ne relocalise pas un patient et ne contourne pas les recensements.
L’unité déclarante d’un document peut ainsi différer de l’unité actuelle.

Les fichiers ajoutés sont :

| Fichier | Rôle |
|---|---|
| `observed/care.jsonl.gz` | Toutes les réceptions documentaires disponibles avant la borne d’extraction |
| `features/patient_care_asof.jsonl.gz` | Une ligne d’enrichissement pour chaque ligne de `patients_asof`, même si tous les groupes sont manquants |

La clé `sample_id` est identique dans les deux vues et dans les cibles de départ.
La vue documentaire contient également `run_id`, hôpital, séjour, partition et
heure pour contrôler la jointure. Les identifiants techniques servent au suivi
et aux jointures ; ils ne doivent pas être utilisés comme variables prédictives.

Les documents de séjours sans ligne active demeurent dans le flux observé.
Le compteur correspondant inclut des séjours de chauffe clos avant l’année :
il ne mesure pas seulement des patients manqués pendant l’année enregistrée.
Les inconnues de présence et les clôtures restent dans le journal du lot 11.

Les cibles restent dans `targets/`, avec les dates réalisées et la censure du
lot 10. La charge de base observée n’est pas ajoutée comme une cible de charge
réellement délivrée. Aucun modèle ou estimateur d’effet d’action n’est entraîné.

## Exécution

```bash
PYTHONPATH=src python -m hospitalos.synthetic.patient_learning \
  --source runs/synthetic/annual --output runs/synthetic/patients-enriched \
  --with-census --with-care

PYTHONPATH=src python -m hospitalos.synthetic.cohort generate \
  --registry runs/synthetic/registry --output runs/synthetic/cohort-enriched \
  --with-learning --with-patients --with-census --with-care
```

`--with-care` est optionnel et indépendant de `--with-census`, mais nécessite
`--with-patients` dans une cohorte. Les sorties restent atomiques, reproductibles
et empreintées. Les paramètres, sources, versions du runtime et hypothèses de
génération sont enregistrés dans le manifeste. Le test réservé n’est pas ouvert.

## Ce qui reste à éprouver

Ce branchement corrige le contrat d’accès aux informations ; il ne valide pas leur
réalisme. Les prévisions du staff reposent sur le cours clinique latent courant
du simulateur, bruité, sans lire la sortie finalement réalisée. Les confirmations
d’aval du moteur historique sont déclenchées lorsque le patient est médicalement
prêt et que l’heure courante atteint le seuil « départ programmé moins 18 h ».
Ce couplage peut rendre la confirmation artificiellement prédictive de la sortie.

Ces hypothèses sont conservées et déclarées, pour comparer les vues sur la même
réalisation physique. Elles doivent être diversifiées et éprouvées avant d’affirmer
un gain prédictif transférable. Les erreurs de complétude des recensements, les
attentes non réconciliées et les limites du proxy de charge restent ouvertes.
Les notes de consultation, extractions Nabla, encodeur appris et raccordement
patient à `PolicyContext` sont hors du lot.

## Validation et suite

```bash
PYTHONPATH=src python scripts/validate_synthetic_care.py \
  --source runs/synthetic/lot10/annual/truth --output runs/synthetic/lot12/annual
```

Omettre `--source` pour régénérer la réalisation physique de développement.
La campagne annuelle compare chaque réception, présence, réconciliation,
enrichissement et cible entre flux incrémental et export. Les tests vérifient
séparément l’absence d’effet de l’option sur les présences et cibles.

Preuves : [résultats](evidence/lot12_validation.md) et
[rapport machine](evidence/lot12_validation.json).

Prochain lot proposé : diversifier les mécanismes de prévision du staff et de
confirmation d’aval, avec des variantes réservées à l’évaluation, pour limiter
l’apprentissage de particularités du simulateur. Phase 0, porte SYN et calendrier
global restent inchangés.
