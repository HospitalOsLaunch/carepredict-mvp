# Lot 10 — parcours patient tels que connus

Le socle expose maintenant les mouvements individuels à travers un contrat fermé,
un flux retardé et une reconstruction horaire par séjour. Les observations et les
cibles de sortie sont écrites dans des fichiers séparés. Le moteur physique et
les observations d’unité des lots précédents restent inchangés.

Le périmètre est opérationnel : demandes d’admission, admissions, transferts
internes, départs de l’hôpital et demandes closes sans admission. Les notes,
évaluations de charge, sorties prévisionnelles et besoins d’aval ne sont pas
encore raccordés à ce contrat. Aucun encodeur de séjour n’est entraîné ici.

## Ce que le modèle peut observer

| Type | Informations autorisées |
|---|---|
| Demande d’admission | Mode d’entrée, tranche d’âge, besoins d’isolement et d’oxygène, unité de rattachement |
| Admission | Unité, lit et unité de rattachement |
| Transfert interne | Unités de départ et d’arrivée, lits d’origine et d’arrivée |
| Départ | Destination enregistrée : domicile, SMR, EHPAD, décès ou transfert extérieur |
| Non-admission | Orientation hors périmètre, déprogrammation ou transfert entrant refusé |

L’âge exact est remplacé par `<65`, `65–74`, `75–84` ou `85+`. La dépendance latente,
les dates médicales futures, le séjour final et les autres champs privés ne sont
pas projetés. `stay_id` identifie un séjour synthétique ; aucun lien longitudinal
entre réadmissions d’une même personne n’est créé.

Chaque réception possède quatre horloges ordonnées, un identifiant d’événement,
un ordre source, une version et une provenance hospitalière. Le schéma interdit
les champs supplémentaires. Les consommateurs utilisent les champs autorisés,
pas les identifiants techniques ou les manifestes comme variables prédictives.

## Horloges et qualité des flux

Comme pour les états d’unité, les événements du pas `[h, h+1)` sont traités comme
des faits à la borne `h+1`, avant les délais de saisie et de livraison. Le fuseau
reste UTC+01:00 fixe. L’ordre du journal départage plusieurs mouvements d’un même
séjour pendant la même heure. Il n’est pas remplacé par l’ordre d’arrivée des messages.

Le nouvel adaptateur `patient_movements_v1` utilise un flux aléatoire indépendant
des mouvements physiques et des observations d’unité. Avec une configuration
`site_v1`, il reprend la probabilité de perte, les délais, les corrections, les
doublons et les fenêtres de panne du site. Les paramètres de charge et de
sous-documentation des agrégats ne s’appliquent pas aux mouvements ; aucune tension
privée n’est injectée pour déterminer leur perte.

Avec le profil historique `v041`, les observations d’unité gardent leur comportement
précédent. Le nouveau flux patient utilise un profil explicite : saisie lognormale
de médiane 25 minutes, autres paramètres par défaut de `site_v1`, sans panne implicite.
Il ne prétend pas reproduire l’ancien module `v041/parcours.py` octet pour octet.

Les pannes touchent l’unité déclarant le mouvement, donc l’unité d’arrivée pour
un transfert interne. Ingestion et disponibilité sont bloquées pendant les fenêtres,
y compris pour les corrections et doublons. Une reprise conserve les dates source
et ne limite pas encore le débit du retard accumulé. Les réceptions postérieures
à l’extraction restent exclues.

## Reconstituer un séjour sans réécrire son passé

`PatientAsOfCursor` accepte uniquement des réceptions déjà disponibles. Il garde
la version la plus élevée connue de chaque événement et reconstruit les événements
touchés dans l’ordre où ils ont eu lieu. Les contrôles d’identité, de topologie et
de contenu portent sur tout le lot de messages avant modification de l’état.

- Un transfert reçu avant son admission permet de connaître la localisation,
  avec une admission et une durée écoulée explicitement manquantes.
- Une correction de lit remplace la version précédente ; elle n’ajoute pas un transfert.
- Une correction tardive de l’admission ne ramène pas le patient avant un transfert
  plus récent. Les doublons ne rafraîchissent pas l’ancienneté de l’information.
- Une sortie disponible tardivement ferme le séjour à sa réception. Les lignes
  déjà produites aux heures précédentes restent inchangées.
- Une version `voided` peut annuler un événement erroné. Une annulation de sortie
  restaure l’état issu des autres événements connus à partir de cette réception.
  Les horloges d’événement, le séjour, le type et l’unité déclarante restent immuables.

Le générateur de bruit introduit actuellement des erreurs de lit sur admissions
et transferts, puis leurs corrections. Le contrat d’annulation est testé avec des
messages construits ; il ne génère pas automatiquement de fausses sorties.

Les lignes horaires exposent les statuts `awaiting_admission` et `admitted`, la
localisation, la durée depuis l’admission connue, le nombre de transferts uniques,
les masques d’information manquante et les sources. Une clôture connue retire le
séjour des lignes actives ; son historique demeure dans le flux de mouvements.

**Le silence ne vaut pas sortie.** Un séjour sans nouvelles n’est jamais supprimé
automatiquement. Après 96 h sans nouveau fait, le masque `stale` devient vrai
(seuil configurable). Ce masque indique une information ancienne, pas une sortie
probable ni une mesure d’incertitude calibrée. Si deux séjours semblent occuper
le même lit, `bed_conflict` signale le conflit sans en choisir arbitrairement un.
Une réconciliation avec le SI ou une politique d’incertitude restera nécessaire
avant une utilisation de ces états pour agir.

## Cibles et censure

Les cibles sont dérivées exclusivement des événements physiques émis dans la
période simulée. Aucun `ready_h` ni départ projeté n’est lu dans les structures
internes des patients. Une borne de mouvement peut être égale à la borne finale
si le mouvement appartient à la dernière tranche horaire ; aucune date ne la dépasse.

`targets/stays.jsonl.gz` contient les dates de demande, admission et clôture
effectivement réalisées. Un séjour encore ouvert à l’extraction conserve une
date de départ `null`, la borne de suivi et `right_censored=true`. Cela inclut
les demandes encore en attente, distinguées par une admission `null`.

`targets/departures.jsonl.gz` fournit, pour chaque ligne de variables :

- `at_risk`, présence physique réelle à l’heure de décision, réservée à l’évaluation ;
- départ hospitalier dans `(t, t+24]`, `(t, t+48]` ou `(t, t+72]`, et masque de censure ;
- durée restante réalisée lorsqu’elle est connue, sinon `null`, avec durée de suivi observée.

Un départ comprend ici décès et transfert extérieur : ce n’est pas une cible de
sortie médicale autorisée ni de retour à domicile. Un positif survenu avant
l’extraction reste connu même si l’horizon dépasse la borne. Sans départ observé,
un horizon dépassant la borne est censuré, jamais codé négatif. Un patient qui
n’est pas physiquement présent à la décision — attente réelle ou séjour fantôme
après sortie perdue — reçoit des cibles de départ `null`. Le statut observé et
la présence vraie peuvent différer ; le protocole d’entraînement devra préciser
sa population et traiter la censure. Aucun entraînement n’est réalisé dans ce lot.

## Exécution et intégration

```bash
PYTHONPATH=src python -m hospitalos.synthetic.patient_learning \
  --source runs/synthetic/annual \
  --output runs/synthetic/patient-annual

PYTHONPATH=src python -m hospitalos.synthetic.cohort generate \
  --registry runs/synthetic/registry \
  --output runs/synthetic/cohort \
  --with-learning --with-patients
```

La source est vérifiée par empreintes et reste immuable ; les sorties sont publiées
atomiquement dans un nouveau répertoire. Variables et cibles sont écrites en flux
pour éviter de garder toutes les lignes patient–heure en mémoire. Les manifestes
contiennent les versions du runtime, les paramètres, sources et empreintes.

`OnlinePatients.push/receive` et `PatientAsOfCursor.advance` permettent le même
traitement par pas de temps. La campagne annuelle vérifie leur égalité avec les
exports hors ligne. Le recommandeur à règles du lot 06 conserve ses entrées
d’unité : cette API patient n’est pas encore ajoutée à `PolicyContext`.

L’option de cohorte respecte les partitions existantes et le garde-fou d’ouverture
du test. Le traitement d’une source déjà matérialisée ne génère pas un nouvel
hôpital ; il hérite de sa partition. L’historique de chauffe initialise les séjours
déjà présents au début de l’année. Il n’existe pas de nouveau découpage temporel
à l’intérieur d’un établissement dans ce lot.

## Validation et suite

```bash
PYTHONPATH=src python scripts/validate_synthetic_patients.py \
  --output runs/synthetic/lot10/annual
```

Les tests incluent corrections, annulations, réceptions hors ordre, doublons,
mutations de fuite, censure, sorties perdues et réservation du test. Sans bruit,
le recensement des mouvements reproduit exactement chaque occupation unité–heure
dans les trois organisations de ressources. Une année avec pertes, retards et pannes
vérifie chaque réception, ligne de variables et jointure de cible.

Preuves : [résultats](evidence/lot10_validation.md) et
[rapport machine](evidence/lot10_validation.json).

La campagne annuelle met en évidence l’accumulation d’états anciens et de conflits
lorsque des sorties sont perdues sans source de réconciliation. Le contrat les
signale, mais cette réalisation ne constitue pas un corpus prêt au préentraînement.

La priorité du lot suivant est **la réconciliation à partir de recensements patient
observés**, avec provenance et incertitude explicites, sans consulter la vérité
pour corriger les entrées. L’enrichissement par la charge observée, les sorties
prévisionnelles et les besoins d’aval vient ensuite. Les notes et styles documentaires,
le modèle hybride, le bornage public des paramètres et le protocole final restent
ouverts. Ce lot ne clôture ni la phase 0 ni la porte SYN.
