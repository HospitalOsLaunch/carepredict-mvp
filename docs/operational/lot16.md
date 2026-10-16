# Lot 16 — aval SMR fini et comparaison du premier prévisionniste

Ce lot suit la PR #19. Le périmètre accepté est une première tranche SMR partagée
entre plusieurs unités, dont la gériatrie, avec demande extérieure et trois niveaux
de capacité. Le reste des filières d'aval et le world model complet restent ouverts.

## Ce que change le moteur

`HospitalConfig.smr.mode=finite_v1` remplace le délai exogène SMR par une ressource
physique. Toutes les unités du périmètre utilisent la même file et le même stock.
Les demandes extérieures consomment aussi ces places ; elles ne sont pas des
patients MCO fictivement ajoutés à l'unité zéro. Leur origine est explicite dans
le journal, dont le routage technique conserve une unité d'ancrage.

Le besoin SMR du scénario est révélé lorsque le patient est actuellement sortant
médical, sans examen/avis bloquant. La demande passe par un délai de préparation,
puis une revue les jours ouvrés. L'allocation est FIFO parmi les demandes
compatibles : un dossier incompatible n'empêche pas de servir le suivant.
La compatibilité couvre seulement oxygène/isolement ; elle ne prétend pas encoder
les critères cliniques complets d'admission en SMR.

Une offre réserve une place. Elle ne fait sortir le patient qu'après disponibilité
médicale, échéance de départ et transport hospitalier effectif. La place reste
occupée jusqu'à la fin du séjour SMR simulé. Un retrait de disponibilité médicale
ou d'orientation annule la demande et restitue la réservation. Son expiration
libère aussi la place et remet la demande en attente avec délai de nouvelle revue.
La demande extérieure peut se retirer après un délai borné. La file elle-même
n'est pas artificiellement tronquée pour masquer des patients non servis.

La durée SMR future reste dans l'état interne ; le journal émet seulement la
libération lorsqu'elle arrive. Réservations, occupations, files et tirages indexés
sont compatibles avec le clonage d'un état et les rejeux sans journal. Les ressources
ne sont pas conservées dans un objet documentaire partagé entre branches.

Les caractéristiques et politiques historiques autres que SMR restent en place.
L'action « accélération de l'aval » n'a plus de réduction en pourcentage sur les
patients SMR dans cette variante. Aucun nouveau bénéfice d'action ou gain de temps
n'est inventé : préparation active, relances et coûts de coordination restent à
implémenter. Les majorations de charge liées au départ SMR requièrent une offre
valide, au lieu d'être prolongées indéfiniment par une échéance théorique passée.

## Correction du mécanisme de destination

`clinical.destinations=conditional_survival_v1` sépare la probabilité de décès de
la distribution des destinations des survivants. Augmenter le poids du SMR/EHPAD
ne fait donc plus mécaniquement baisser la mortalité. Par défaut, le coefficient
de dépendance de la mortalité est nul : aucune taille d'effet clinique nouvelle
n'est présentée comme mesurée. Les coefficients sont typés, versionnés et inclus
dans l'empreinte de configuration. Le mode historique reste disponible et ses
empreintes de configuration sont préservées quand les options sont inactives.

## Protocole exécuté

Deux bras appariés partagent la correction de mortalité et les mêmes configurations
hors SMR : même cohorte entrante, structures, calendrier, paramètres d'observation,
architecture, graine d'entraînement et budget. Les observations bruitées et les
trajectoires peuvent différer ; ce n'est pas une expérience causale de lits ajoutés.

- Contrôle : délai SMR historique.
- Variante : capacité SMR égale à 70 %, 40 % ou 15 % des lits MCO simulés, arrondie
  au supérieur. Ce sont des hypothèses de ressources desservant le périmètre, pas
  des ratios nationaux ni une classification empirique des établissements.
- Demande extérieure : 0,005 demande par lit MCO et par jour ; mêmes critères
  techniques et même file. Séjours SMR : médiane hypothétique 21 jours, dispersion
  logarithmique 0,45, bornes 1–180 jours. Préparation 24 h, revue 10 h les jours
  ouvrés, réservation 48 h, nouvelle revue au plus tôt 24 h après expiration.
- Pour chaque bras : 12 mondes d'entraînement, six de validation, 120 jours après
  28 jours de chauffe ; deux mondes de test réservés non générés. Deux sites de
  validation par régime ; les nombres d'unités de validation restent inédits.
- Un réseau de 6 755 paramètres par bras, 60 époques, sans modification du modèle
  du lot 15. Moyennes à 24 h, trois granularités, trois références simples.
- Les entrées restent les mêmes observations d'unité/pôle/hôpital : **le réseau
  ne reçoit ni capacité SMR, ni file SMR, ni état patient latent**. L'expérience
  mesure sa prévision sur un monde différent ; elle ne démontre pas qu'il a appris
  une représentation explicite des ressources d'aval.
- Prévisions de validation gelées avant ouverture des cibles. Pas de sélection
  des paramètres du moteur ou du réseau sur les résultats de cette campagne.

```bash
PYTHONPATH=src python -m hospitalos.operational.experiment prepare \
  --plan configs/operational/smr_legacy_delay_v1.json \
  --output runs/operational/lot16/legacy_delay/cohort
PYTHONPATH=src python -m hospitalos.operational.experiment prepare \
  --plan configs/operational/smr_finite_v1.json \
  --output runs/operational/lot16/finite_v1/cohort
# Exécuter pour chacun des deux bras, avec des répertoires de sortie nouveaux :
PYTHONPATH=src python -m hospitalos.operational.experiment run \
  --cohort runs/operational/lot16/finite_v1/cohort \
  --output runs/operational/lot16/finite_v1/result
PYTHONPATH=src python -m hospitalos.operational.experiment run \
  --cohort runs/operational/lot16/legacy_delay/cohort \
  --output runs/operational/lot16/legacy_delay/result
PYTHONPATH=src python -m hospitalos.operational.smr_experiment \
  --root runs/operational/lot16 --output runs/operational/lot16/comparison.json
```

## Preuves et limites

Les [résultats](evidence/lot16/results.md) distinguent les stocks et trajectoires du
moteur des erreurs de prévision. Comparer la MSE brute entre bras ne mesure pas
un progrès du modèle puisque les cibles changent. La comparaison aux références
se fait dans chaque bras ; tous les résultats, y compris défavorables, sont gardés.

La vérification locale compte 564 tests : 478 du socle synthétique, 32
opérationnels et 54 régressions historiques. Ruff, formatage et mypy strict
passent sur les fichiers concernés.

Les tests couvrent conservation, compatibilité, demande extérieure, concurrence
entre unités, restitution, expiration, retrait médical, transport, déterminisme,
clonage, absence de dates futures dans les événements et propagation vers une file
urgente depuis un même état. Un contrôle indépendant reconstruit le stock SMR du
journal exporté, le rapproche de chaque photographie horaire et exige une sortie
MCO pour chaque admission interne en SMR. Des mutations de réservation et des
corruptions de fichiers doivent être refusées.

La première tentative de campagne a été arrêtée par le contrôle des cibles :
un CSV unité de validation était tronqué dans chaque bras, malgré des journaux
complets et une empreinte cohérente avec le fichier tronqué. Une réexportation
isolée n’a pas reproduit le défaut ; sa cause système n’est pas établie. L’export
vérifie désormais les octets écrits contre le contenu attendu avant de publier
un manifeste complet, avec un test de troncature silencieuse. La campagne a été
régénérée ; aucun paramètre d’apprentissage ou de scénario n’a été ajusté.

Cette tranche ne valide pas le réalisme clinique. Les besoins/destinées demeurent
issus du scénario ; il n'y a pas de nouvelle aggravation clinique du seul fait de
l'attente. Le reste de l'hôpital n'est pas simulé individuellement derrière la
demande extérieure. EHPAD, HAD, aides à domicile, ressources humaines d'aval,
coûts de coordination, panne documentaire SMR, calendrier physique Europe/Paris,
politique non privilégiée et JEPA/multi-pas restent ouverts. Les séjours et files
ouverts à la fin ne disparaissent pas des stocks. La chauffe de 28 jours n'établit
pas un régime stationnaire. Aucune porte G1–G4/SYN n'est déclarée franchie et aucune
donnée individuelle réelle n'est utilisée.
