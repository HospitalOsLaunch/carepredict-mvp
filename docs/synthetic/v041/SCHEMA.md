# Dictionnaire des données, v0.4.1

Toutes les données sont fictives. Les horodatages sont en ISO 8601 au fuseau fixe **+01:00** : le changement d'heure n'est pas modélisé. La colonne `h` donne le même instant en heures depuis le début de la simulation, pour faciliter les jointures. Une valeur vide signifie inconnu, pas encore réalisé ou sans objet ; jamais zéro.

## Les vues, et ce qu'on a le droit d'en faire

| Dossier | Rôle | Entrée d'un modèle ? |
|---|---|---|
| `observe/` | Livraisons du système d'information, avec leurs retards, absences, doublons et corrections | Oui, après filtre `h_disponible <= instant`, déduplication et choix de la version la plus récente disponible |
| `apprentissage/variables_asof.csv.gz` | Variables d'unité et de pôle déjà filtrées à chaque heure | Oui |
| `apprentissage/sejours_asof.csv.gz` | Trajectoire de chaque séjour présent, telle que connue à chaque heure | Oui |
| `observe/notes.jsonl.gz` | Notes cliniques versionnées | Oui, après filtre `h_disponible <= instant` |
| `apprentissage/extraction_notes.csv.gz` | Variables extraites des notes par l'extracteur de référence, version par version | Oui, à partir de `h_utilisable` |
| `apprentissage/etat_notes_asof.csv.gz` | État documentaire par variable, sans effacement | Oui, à partir de `h_utilisable` ; c'est la table à joindre à la couche séjour |
| `apprentissage/cibles.csv.gz`, `cibles_sejours.csv.gz` | Vérité future | Uniquement comme étiquette |
| `verite/` | État complet du monde simulé | Non : audit, construction des cibles, analyse |
| `causal/` | Décisions, contrefactuels, estimands | Pour l'évaluation causale et l'apprentissage conditionné aux actions, pas comme variable de prévision |
| `unite_CSG/` | Sous-ensemble exact des vues d'apprentissage pour l'unité focale (séjours : `unite_actuelle == CSG`) | Comme `apprentissage/` |

**Règle absolue** : ne jamais joindre `verite/`, `causal/contrefactuels` ou les colonnes `cible_*` aux variables d'un modèle de prévision.

Découpage, identique dans toutes les vues (`split`) : `train` (janvier-août), `validation` (septembre-octobre), `test` (novembre-décembre). Les 168 heures avant chaque frontière et avant le 31/12 portent `embargo_ou_censure`. Aucune cible ni aucune fenêtre de contrefactuel ne franchit une frontière.

## `structure.json`

Unités (lits installés, lits d'isolement, lits à oxygène) et lits individuels. Les lits d'isolement sont aussi équipés en oxygène. Chaque unité a 2 lits supplémentaires (`supplementaire=true`) qui n'existent que lorsque le levier « lits supplémentaires » est actif, ou tant qu'un patient y reste.

## `verite/etats_horaires.csv.gz` : une ligne par entité et par heure

`niveau` vaut `unite` ou `pole` ; le pôle est la somme de ses unités, sauf `ratio_charge` et `taux_occupation`, qui sont recalculés.

| Champ | Sens |
|---|---|
| `lits_physiques` | Lits installés, plus les lits supplémentaires existants |
| `lits_fermes` | Lits vacants dont la fermeture est demandée (été, Noël, maintenance, manque de personnel). Un lit occupé ne ferme qu'à la sortie du patient |
| `lits_ouverts` | `lits_physiques - lits_fermes` |
| `lits_occupes` | Patients présents dans l'unité, hébergés compris |
| `lits_sales_ou_nettoyage` | Lits ouverts vacants, en attente de nettoyage ou en cours de nettoyage |
| `lits_propres_libres` | Lits ouverts, vacants et propres ; pas forcément compatibles avec un patient donné |
| `lits_supplementaires_actifs` | 2 si le levier est actif, sinon 0 |
| `patients_heberges_presents` | Patients d'une autre unité accueillis ici |
| `attente_urgences_nb`, `attente_urgences_4h_plus` | Patients des urgences orientés vers l'unité et sans lit |
| `programmes_en_attente`, `transferts_entrants_en_attente` | Demandes non urgentes sans lit |
| `entrees_h`, `sorties_h` | Admissions et sorties pendant l'heure (hébergements compris) |
| `transferts_internes_entrants_h`, `transferts_internes_sortants_h` | Rapatriements entre unités du pôle |
| `sortants_medicaux_presents` | Patients médicalement sortants encore présents (aucun examen ni avis en attente) |
| `en_attente_aval` | Sortants attendant une place en SMR ou en EHPAD |
| `en_attente_transport`, `en_attente_imagerie`, `en_attente_avis` | Patients bloqués par un service partagé |
| `en_attente_aide_domicile` | Patients dont l'aide à domicile requise n'est pas encore organisée |
| `charge_soins_min_h` | Minutes de soins requises pendant l'heure. **Indicateur construit, pas un score SIIPS** |
| `capacite_soins_min_h` | Soignants présents × 60 × part du temps consacrée aux soins |
| `minutes_non_couvertes_h` | `max(0, charge - capacité)` ; ce n'est pas un événement indésirable |
| `soignants_prevus`, `soignants_presents`, `ide_presents`, `as_presents` | Effectifs du poste en cours, renfort compris |
| `ratio_charge` | Charge / capacité |
| `ei_attendus_h`, `ei_observes_h` | Événements indésirables : taux attendu et tirage. Mécanisme illustratif |

Invariants vérifiés à chaque heure : `lits_physiques = lits_fermes + lits_ouverts` ; `lits_ouverts = lits_occupes + lits_sales_ou_nettoyage + lits_propres_libres` ; `lits_occupes(h) = lits_occupes(h-1) + entrees + transferts_entrants - sorties - transferts_sortants`.

## `verite/sejours.csv.gz` : une ligne par demande d'admission

Les séjours encore présents ou en attente au 31/12 à 24 h (`issue = censure`) sont reconstruits depuis l'état exact de cet instant : aucune date, aucun drapeau ne vient d'après.

| Champ | Sens |
|---|---|
| `unite_cible`, `unite_sortie`, `lit_sortie` | Unité demandée, unité et lit à la sortie (ou au 31/12) |
| `mode_entree` | `urgences`, `programme`, `transfert_entrant` |
| `issue` | `sortie`, `censure`, `hors_perimetre` (pris en charge ailleurs dans l'hôpital), `deprogramme`, `transfert_refuse` |
| `age`, `tranche_age`, `sexe` | L'âge exact ne figure que dans la vérité |
| `dependance`, `mobilite` | Dépendance 1 (autonome) à 4 ; mobilité `autonome`, `aide`, `brancard` (un patient brancardé a besoin d'un transport, même vers son domicile) |
| `isolement`, `oxygene`, `imagerie_requise`, `avis_requis`, `aide_domicile_requise` | Besoins qui conditionnent le lit ou la sortie |
| `ts_decision`, `ts_entree`, `ts_sortant_medical`, `ts_aide_organisee`, `ts_sortie` | Horloges vraies ; vides si l'instant est postérieur au 31/12 |
| `attente_avant_lit_h` | Patients des urgences : de la décision au lit, ou à l'orientation ailleurs |
| `destination`, `dms_jours` | Destination de sortie et durée de séjour |
| `heberge`, `rapatriements` | Hébergé hors de son unité, nombre de retours |
| `sortie_sous_pression`, `retard_sortie_charge_h`, `aval_accelere`, `sortie_anticipee` | Traces des mécanismes et des leviers (`aval_accelere` couvre aussi l'aide à domicile relancée) |
| `readmission_30j` | Calculée, **non réinjectée** comme nouvelle arrivée |

Ces champs sont privilégiés : aucun ne doit servir de variable d'entrée.

## `verite/politique_cadre.csv.gz`

Une ligne par unité et par jour : l'information cachée du cadre (`confusion_z`, afflux attendu aux urgences dans les 24 h, standardisé et bruité) et les probabilités vraies d'engager chaque levier (`p_action_*`). **Absent de `causal/` à dessein** : dans un vrai service, ces probabilités ne sont pas connues.

## `verite/effectifs_postes.csv.gz` et `verite/taches_services.csv.gz`

Effectifs : `soignants_presents = soignants_prevus - absences + remplacements + renforts`. Les effectifs sont des nombres par rôle, pas un planning nominatif.

Tâches : `NETTOYAGE`, `IMAGERIE`, `AVIS`, `TRANSPORT`, avec demande, début, fin et statut (`EN_FILE`, `EN_COURS`, `TERMINEE`). Les capacités sont partagées par le pôle. Les avis sont rendus 2 h après leur début, les jours ouvrés de 9 h à 17 h.

## `verite/evenements.jsonl.gz` et `observe/livraisons.jsonl.gz`

Événements :
- **Parcours** : `DEMANDE_ADMISSION`, `ADMISSION`, `SORTANT_MEDICAL`, `SORTIE`, `TRANSFERT_INTERNE`, `ORIENTATION_HORS_PERIMETRE`, `DEPROGRAMMATION`, `TRANSFERT_REFUSE`.
- **Services** : `*_DEMANDE`, `*_DEBUT`, `*_FIN` pour le nettoyage, l'imagerie, les avis et le transport.
- **Unité** : `ETAT_UNITE` (instantané horaire), `EVALUATION_CHARGE` (quotidienne à 7 h, par patient : minutes de soins, dépendance, mobilité), `PRISE_DE_POSTE`.
- **Décision** : `RECOMMANDATION`, `DECISION`.
- **Staff et aval** : `DATE_SORTIE_PREVISIONNELLE`, `DESTINATION_DEMANDEE`, `DEMANDE_AVAL`, `DEMANDE_AVAL_ANNULEE`, `PLACE_AVAL_CONFIRMEE`, `AIDE_DOMICILE_DEMANDE`, `AIDE_DOMICILE_ORGANISEE`.

Les événements du staff sont produits les jours ouvrés à 10 h, avec un générateur aléatoire séparé. Ils n'agissent jamais sur la physique. La destination déclarée est corrigée dans les 48 h qui précèdent la sortie médicale prévue ; la place d'aval est confirmée environ 18 h avant le départ. Ce sont des signaux réalistes, mais ils portent une information sur le calendrier : à garder en tête en lisant l'importance des variables.

Livraisons : chaque événement peut être absent, retardé, dupliqué ou corrigé.

| Champ | Sens |
|---|---|
| `ts_evenement` ≤ `ts_saisie` ≤ `ts_ingestion` ≤ `ts_disponible` | Horloges du fait, de la saisie, de la réception, de la première utilisabilité |
| `h_disponible` | `ts_disponible` en heures, pour filtrer |
| `event_version`, `remplace_version`, `qualite` | Une correction porte la version 2 et le drapeau `CORRECTION_SOURCE` |
| `empreinte` | Hachage du contenu, hors horloges de livraison : deux doublons ont la même |
| `source` | `GESTION_LITS`, `DOSSIER_SOIN`, `PLANNING`, `CELLULE_ORDONNANCEMENT`, `HOSPITALOS`, `DPI_STAFF`, `DPI_MOUVEMENTS`, `SERVICE_SOCIAL`, `VIATRAJECTOIRE`, `PRESCRIPTIONS`, `IMAGERIE`, `REGULATION_TRANSPORTS`, `BIONETTOYAGE` |

Ce qui rend l'observation imparfaite :

- 1,5 % d'absences par défaut, deux fois plus en heure de tension ; davantage pour certains types : 8 % des évaluations, 10 % des dates prévisionnelles, des destinations demandées et des confirmations d'aval, 15 % des événements d'aide à domicile ;
- 45 % des statuts « sortant » ne sont jamais saisis ;
- les sorties sont saisies avec retard : en fin de journée dans 12 % des cas, le lendemain dans 3 % ;
- 2 % des instantanés comportent une erreur d'un lit, corrigée 6 à 48 h plus tard ;
- 0,8 % de doublons ;
- une panne du système d'information de 9 h à 17 h, un jour d'octobre ;
- dans les instantanés, les sortants (60 %) et l'attente d'aval (80 %) sont sous-documentés, et la charge est bruitée (±10 %) ;
- dans les évaluations, les minutes de soins sont bruitées (±10 %), la dépendance est décalée d'un niveau dans 10 % des cas, la mobilité est erronée dans 10 % des cas ;
- l'âge est livré en tranche (`<65`, `65-74`, `75-84`, `85+`).

## `apprentissage/variables_asof.csv.gz` et `cibles.csv.gz`

Une ligne de variables par entité (4 unités + pôle) et par heure. Les variables `obs_*` viennent du dernier instantané disponible, avec `age_observation_h` et le lignage (`entree_event_id`, `entree_version`, `entree_disponible`). Les variables du pôle additionnent les dernières observations de ses unités ; l'âge retenu est le maximum. S'y ajoutent les variables calendaires : `heure_locale`, `jour_semaine`, `mois`, `jour_ferie`. Nouvelles en v0.3 : `obs_en_attente_avis`, `obs_en_attente_aide_domicile`.

Cibles : `cible_*` à `h + horizon_h` (12, 24, 48, 72, 168 h), issues de la vérité, pour 9 grandeurs (lits occupés, attente aux urgences, lits propres libres, charge, minutes non couvertes, sortants, attente d'aval, hébergés, ratio de charge).

## `apprentissage/sejours_asof.csv.gz` : une ligne par séjour connu présent et par heure

Liste fermée de colonnes (`parcours.COLONNES_SEJOURS_ASOF`) ; toute colonne ajoutée fait échouer les contrôles.

| Champ | Sens |
|---|---|
| `sample_id`, `h`, `ts`, `sejour_id`, `split` | Clé `sejour_id@h` |
| `unite_actuelle`, `unite_appartenance`, `heberge` | Dernier mouvement connu (ou dernière évaluation, si plus récente) ; unité demandée |
| `mode_entree`, `tranche_age`, `isolement`, `oxygene` | Depuis la demande d'admission ; vides si elle n'a pas été livrée |
| `duree_ecoulee_h`, `mouvements_internes` | Depuis l'admission connue ; rapatriements connus |
| `dependance_obs`, `mobilite_obs`, `charge_soins_24h_obs`, `age_evaluation_h` | Dernière évaluation disponible |
| `dsp_jours_restants`, `dsp_revisions`, `dsp_absente` | Date de sortie prévisionnelle en jours à partir d'aujourd'hui (négative si dépassée), nombre de versions reçues |
| `sortant_medical_saisi`, `h_depuis_sortant_saisi` | Statut sortant reçu (45 % ne le sont jamais) |
| `destination_demandee`, `destination_revisions` | Dernière destination déclarée (`domicile`, `SMR`, `EHPAD`, `transfert`) |
| `imagerie_en_attente`, `avis_en_attente`, `transport_en_attente` | Demande reçue, fin non reçue |
| `demande_aval_en_attente`, `anciennete_demande_aval_h`, `place_aval_confirmee` | Demande SMR ou EHPAD envoyée, non annulée et non confirmée |
| `aide_domicile_requise`, `aide_domicile_organisee` | Événements du service social reçus |
| `age_derniere_information_h`, `derniere_disponibilite` | Fraîcheur ; `derniere_disponibilite <= h` est contrôlé |
| `dsp_event_id` | Lignage : événement qui porte la date prévisionnelle utilisée |

Un séjour apparaît dès qu'un mouvement ou une évaluation est disponible. Il disparaît quand sa sortie est disponible, quand un autre patient est enregistré dans son lit, ou après 96 h sans information.

## `apprentissage/cibles_sejours.csv.gz`

Même `sample_id`, dans le même ordre.

| Champ | Sens |
|---|---|
| `cible_present_vrai` | Le patient est réellement présent à `h` (faux pour un fantôme dont la sortie n'est pas encore saisie) |
| `cible_sortie_24h`, `_48h`, `_72h` | Sortie réelle dans `[h, h + horizon)` ; vide si inconnue à cause de la censure |
| `cible_duree_restante_h` | Heures jusqu'à la sortie réelle ; vide si la sortie est postérieure au 31/12 |
| `cible_sortant_medical_24h` | Devient médicalement sortant dans les 24 h ; vide s'il l'est déjà |

## `causal/decisions.csv.gz`

Une ligne par unité et par jour (9 h), avec `split`.

| Champs | Sens |
|---|---|
| `occupation`, `attente_urg`, `attente_urg_4h`, `sortants_medicaux`, `attente_aval`, `attente_aide_domicile`, `ecart_effectif`, `ratio_charge`, `lits_sup_actifs` | Caractéristiques lues par le recommandeur et le cadre, calculées sur l'état vrai |
| `q_reco_*` | Probabilité de recommander le levier ; dépend de ces seules colonnes |
| `r_*` | Levier recommandé |
| `exposition` | Le cadre a consulté les recommandations ce jour-là |
| `a_*` | Levier engagé par le cadre (validation ou initiative) |
| `n_concernes_*` | Patients ou postes réellement touchés |
| `x_*` | Exécuté : `a_* = 1` et `n_concernes_* > 0` |

## `causal/contrefactuels.csv.gz` et `causal/estimands.json`

Pour chaque jour et chaque unité, 18 rejeux de 72 h depuis l'état exact, avec les mêmes aléas. Colonnes : `famille`, `scenario`, `n_concernes`, `expose`, `actions_h0`, `levier_valide`, `split`, puis les métriques cumulées à 24 h et 72 h, pour l'unité ciblée et pour le pôle (`pole_*`).

| `famille` | `scenario` | Ce qui est imposé |
|---|---|---|
| `A_levier_seul_puis_rien` | `aucun`, 4 leviers, `renfort_soignant_pourvu` | Le levier engagé seul à 9 h (échec d'exécution compris), puis aucune décision nulle part ; `renfort_soignant_pourvu` : renfort réellement présent |
| `B_action_imposee_puis_politique` | `factuel`, `aucun`, 4 leviers, `renfort_soignant_pourvu` | Les actions de l'unité ciblée à 9 h ; ensuite la politique en vigueur. `factuel` n'impose rien et reproduit la vérité ; `actions_h0` donne alors la combinaison réellement engagée |
| `C_recommandation_imposee_puis_politique` | `aucune`, 4 leviers | Les recommandations de l'unité ciblée à 9 h ; l'exposition, la validation (`levier_valide`) et l'exécution suivent leurs mécanismes |

L'effet vrai d'un scénario est la différence avec `aucun` (A, B) ou `aucune` (C) de mêmes `ts`, `unite_cible` et `famille`. `estimands.json` déclare les trois estimands et ce qui est identifiable sur données observées.

## `observe/notes.jsonl.gz` : une ligne par version de note

| Champ | Sens |
|---|---|
| `note_id`, `version`, `remplace_version` | `N<séjour>-1` observation des urgences, `-2` observation d'entrée, `-3` recueil infirmier ; une version ajoute un complément daté au texte précédent, sans le modifier |
| `sejour_id`, `type_note`, `auteur`, `unite` | `OBS_URGENCES`, `OBS_ENTREE`, `RECUEIL_IDE` ; `interne_urgences`, `senior_urgences`, `interne_service`, `senior_service`, `ide` ; unité visée (urgences) ou unité d'admission |
| `ts_creation` ≤ `ts_modification` ≤ `ts_disponible`, `h_disponible` | Début de rédaction (identique pour toutes les versions), fin de la version, signature : la version n'est lisible qu'à partir de `ts_disponible` |
| `texte` | Texte libre. Aucun nom ; l'âge exact y figure, comme dans une vraie note |

Les notes ne sont produites que pour les demandes d'admission de la période (et des 30 jours qui la précèdent), et coupées au 31/12 à 24 h.

## `verite/notes_annotations.jsonl.gz`

Pour chaque version : `faits`, liste de faits affirmés, avec :
- `variable` : `motif`, `incertitude_diagnostique`, `vit_seul`, `aidant_present`, `aides_existantes`, `troubles_cognitifs`, `perte_autonomie_recente`, `evaluation_sociale_demandee`, `orientation_envisagee`, `autonomie`, `mobilite`, `oxygene`, `isolement`, `imagerie_prevue`, `avis_prevu` ;
- `valeur` ; `statut` (`documente`, `negation`, `hypothese`) ;
- `correct` : `vrai`, `faux` (erreur de saisie), `perime` (copier-coller d'un ancien dossier), `prevision` (orientation envisagée) ;
- `extrait`, `debut`, `fin` : position exacte dans `texte`.

Une variable absente de la liste n'est pas mentionnée dans la note : un extracteur doit répondre « inconnu ».

## `verite/sejours_cliniques.csv.gz`

Situation vraie de chaque séjour à l'arrivée : `motif`, `incertitude_diagnostique`, `antecedents` (séparés par `|`), `vit_seul`, `aidant_present`, `aides_existantes`, `troubles_cognitifs`, `perte_autonomie_recente`, `evaluation_sociale_demandee`, `cause_isolement`, et la situation détaillée dont toutes les notes du séjour sont rédigées : `statut_marital` (`marie`, `veuf`, `divorce`, `celibataire`), `cohabitant` (`conjoint`, `enfant`), `enfant`, `aidant_type` (`conjoint`, `fille`, `fils`, `niece`), `aides_types`, `logement`, `aide_technique` (`aucune`, `canne`, `deambulateur`, `tierce_personne`, `fauteuil`, `transfert_deux`, `alite`). Tirée après coup, en cohérence avec les attributs du moteur ; sans effet sur la physique.

## `apprentissage/extraction_notes.csv.gz`

Une ligne par version de note : `note_id`, `version`, `sejour_id`, `type_note`, `unite`, `h_disponible`, `h_utilisable` (heure entière à partir de laquelle la ligne peut entrer dans une prédiction), `split` (selon `h_utilisable`), puis pour chaque variable sa valeur extraite et `<variable>_statut`. `source_ancienne_signalee` vaut vrai si la note renvoie à un ancien dossier. Une valeur vide signifie que l'extracteur n'a rien trouvé.

## `apprentissage/etat_notes_asof.csv.gz`

Une ligne par version de note appliquée (`sejour_id`, `h_utilisable`, `h_disponible`, `note_id`, `version`, `type_note`, `split`), avec l'état documentaire complet du séjour après cette version. Pour chaque variable :

| Champ | Sens |
|---|---|
| `<variable>`, `<variable>_statut` | Valeur et statut de la nouvelle mention disponible la plus récente ; une absence ou une simple recopie ne la remplace pas |
| `<variable>_source`, `<variable>_h_source` | Type de note et heure de disponibilité de la version qui introduit cette mention : l'ancienneté de l'information à l'instant h vaut `h - <variable>_h_source` |
| `<variable>_note_id_source`, `<variable>_version_source` | Identifiant et version qui ont introduit la mention retenue ; peuvent différer de la note qui déclenche le snapshot |
| `<variable>_ts_redaction_source` | `ts_modification` de cette version source ; date de rédaction, pas date présumée de l'événement clinique |
| `<variable>_extrait_source` | Phrase extraite du nouveau texte de la version source, après normalisation des apostrophes et espaces |
| `<variable>_n_notes` | Nombre de notes distinctes qui ont mentionné la variable |
| `<variable>_conflit` | Vrai si les notes disponibles ne donnent pas toutes la même valeur (copier-coller périmé, erreur, évolution) |

Le correctif de fusion de la v0.4.1 conserve la provenance d'une mention recopiée. Seule une nouvelle mention explicite dans le texte ajouté actualise la variable. « RAS » ne rafraîchit aucun autre fait. La dernière valeur par note participe au conflit ; le conflit n'est pas résolu à partir de la vérité clinique.

La reconstruction exige toutes les versions précédentes des notes appliquées, dans un historique en ajout seul. Les historiques incomplets et les réécritures sont rejetés. Le journal utilisé est `observe/notes.jsonl.gz` ; les annotations privilégiées ne participent pas à la fusion.
