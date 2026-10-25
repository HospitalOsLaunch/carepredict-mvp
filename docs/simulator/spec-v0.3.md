# Spécification du simulateur hospitalier HospitalOS

Révision documentaire 0.3 • 25 octobre 2026

Parcours libérer puis attribuer • Court séjour gériatrique

Ce document fixe le contrat métier, scientifique et technique du simulateur hospitalier HospitalOS. Il consolide les deux revues du 25 octobre et remplace les deux versions de spécification précédentes. Il permet de construire un banc d’intégration, de produire des données synthétiques d’intervention et de conduire des expériences de pré-entraînement et de comparaison de politiques.

**Statut.** Spécification pour implémentation. La rédaction de cette révision ne constitue ni une livraison de logiciel, ni une qualification du simulateur, ni une preuve d’efficacité en établissement. Chaque qualification dépend d’essais identifiés et de résultats enregistrés.

**Versionnement.** « Révision 0.3 » désigne ce document. Les jalons M1 à M4 décrivent la construction du logiciel ; ils correspondent aux versions moteur 0.1 à 0.4 et ne sont pas présumés réalisés.

## 1 Objet et périmètre

Le moteur simule une unité de court séjour gériatrique alimentée par les urgences et par des admissions programmées. La médecine polyvalente constitue le second environnement prévu. Le choix de l’unité peut être adapté avant calage si un partenaire fournit un périmètre mieux documenté ; ce changement entraîne une nouvelle version du manifeste expérimental.

La simulation est à événements discrets en temps continu. Les arrivées, les décisions, les tâches, les changements d’état et les messages ont des dates explicites. SimPy est le choix d’implémentation par défaut. Le calendrier local est Europe/Paris ; le moteur utilise une chronologie monotone et des dates avec fuseau pour traiter les changements d’heure sans doublon.

**Inclus.** Arrivées et évaluation aux urgences, demandes de lit, réservations, installation, séjour, aptitude médicale à sortir, décision médicale, préparation et départ, nettoyage, fermeture de lits, professionnels, charge de travail simplifiée et information imparfaite.

**Frontières.** Les urgences sont représentées au niveau nécessaire aux arrivées, décisions et attentes. Les patients non hospitalisés sortent explicitement du périmètre. Le SMR et l’EHPAD sont des destinations avec un mécanisme d’accès exogène. Les autres unités ne sont pas simulées en détail. L’hébergement extérieur est désactivé jusqu’après M4.

**Exclusions.** Soins et trajectoires cliniques détaillés, bloc, imagerie, transport sanitaire et brancardage détaillés, planification du personnel et effets cliniques des politiques. Un délai de transfert agrégé reste représenté. Les effectifs sont fixés par plage horaire.

Trois usages sont distingués : intégration technique, pré-entraînement exploratoire, puis qualification de comportements sur un périmètre étayé par des données réelles. Aucun résultat de simulation ne constitue un résultat terrain.

## 2 Architecture et responsabilités

Le moteur détient l’état physique vrai et applique les transitions. Le générateur v0.2 fournit des profils et des primitives aléatoires après audit ; il ne produit pas une seconde trajectoire d’occupation ou de sorties. Les professionnels simulés exécutent la politique de référence dès M1. HospitalOS leur adresse ensuite des recommandations par un canal distinct.

| Composant | Responsabilité | Accès autorisé |
| --- | --- | --- |
| Générateur de scénarios | Profils, calendrier, aléas et paramètres versionnés | Configuration du scénario ; aucune décision de politique |
| Moteur et ordonnanceur | États physiques, ressources, événements et invariants | État vrai et primitives aléatoires |
| Professionnels simulés | Décision, vérification et exécution des tâches | SI déclaré et observations acquises par leur rôle |
| Faux SI | Déclarations, corrections, projections et livraison des messages | Faits à déclarer ; exposition limitée par canal |
| HospitalOS | Reconstruction, prévision et recommandations | Informations reçues avant D et retours d’action disponibles |
| Notateur indépendant | Calcul des métriques et vérification des journaux | Journal de vérité après l’épisode ; jamais utilisé par la politique |

Les observations directes sont des événements : un professionnel peut vérifier un lit ou rencontrer un patient, en consommant du temps. Cette vérification ne lui donne pas accès à l’ensemble de l’état caché.

Le journal de vérité est séparé des interfaces, des fichiers d’observation et des journaux accessibles à HospitalOS. Le mode privilégié utilisé pour un diagnostic d’information parfaite est un mode expérimental distinct, désactivé dans les essais normaux et exclu des données d’entraînement.

### Informations disponibles à la décision

| Horodatage | Signification | Exposition |
| --- | --- | --- |
| t_true | Heure physique du fait dans le moteur | Journal de vérité uniquement |
| t_event_declared | Heure du fait déclarée par le système source | Facultative ; peut être absente ou erronée |
| t_recorded | Heure d’enregistrement dans le système source | Si exposée par ce système |
| t_received | Heure de réception par le connecteur HospitalOS | Métadonnée locale d’ingestion |

À D, seules les informations effectivement reçues et rendues accessibles avant D entrent dans l’observation. Une correction tardive ne réécrit pas les observations historiques utilisées pour décider. L’ordre est déterminé par le couple date de réception et numéro de séquence, y compris pour les messages reçus à la même date.

Les identifiants de patient, séjour, mouvement, tâche, recommandation et réservation sont distincts. Les horodatages ne servent jamais seuls d’identifiants.

## 3 Entités et états

Le modèle contient patient, séjour, demande de lit, lit, chambre, réservation, professionnel, tâche et créneau de capacité. Les objets métier portent les liens nécessaires à la conservation et à l’audit. Un patient a au plus une localisation physique à un instant donné, indépendamment des divergences du SI déclaré.

| Entité | Attributs minimaux |
| --- | --- |
| Patient et séjour | Profil, entrée, besoins d’équipement et surveillance, exigences d’isolement, aptitude clinique cachée, décision médicale, destination, conditions de départ |
| Demande de lit | Patient, date de création, priorité, unité compatible, état, motif de clôture |
| Lit et chambre | Occupation, hygiène, ouverture, réservation ; caractéristiques de chambre et cohabitation |
| Réservation | Identifiant, patient, lit, création, expiration, état et motif de clôture |
| Professionnel | Rôle, présence, compétences, tâches courantes, file et charge de fond |
| Tâche | Type, patient ou lit, prérequis, rôle, priorité, durée, dates, résultat et coût |
| Créneau de capacité | Rôle, période, minutes disponibles, charge courante, tâches et déficit |

Le lit possède quatre dimensions séparées, liées par des invariants. Le parcours de sortie appartient au séjour et n’est affiché à côté du lit que par référence.

| Dimension du lit | Valeurs et règles |
| --- | --- |
| Occupation physique | Vide ou occupé par un patient identifié |
| Hygiène | À nettoyer, nettoyage en cours, prêt ; exigence standard ou renforcée portée séparément |
| Disponibilité opérationnelle | Ouvert, fermé ou fermeture prévue |
| Réservation | Aucune ou réservation active identifiée ; l’historique conserve expirations et annulations |

Une sortie envisagée n’est ni une autorisation médicale ni un départ. Une aptitude médicale peut être révoquée par un événement clinique exogène ; les tâches et autorisations devenues obsolètes sont alors annulées ou réévaluées explicitement.

### Réserver et installer

**Réserver pour P.** La politique sélectionne le lit à partir de l’état déclaré disponible : vide, prêt, ouvert, compatible et sans réservation connue concurrente. Le service de réservation garantit l’unicité atomique de la réservation active. Il ne corrige pas silencieusement les autres informations à partir de l’état vrai.

**Installer P.** Une vérification d’exécution confirme que le lit est physiquement vide, prêt, ouvert, compatible et réservé activement pour P. La capacité de soins est revérifiée. Le patient doit encore être en attente et admissible. La réservation est consommée et l’occupation mise à jour dans une même transaction.

Un échec produit un motif, un délai, un coût et une mise à jour observable selon le canal prévu. Une réservation expirée ne peut pas être consommée. Le transfert est précédé d’une vérification ; une invalidation en cours de transfert déclenche une attente localisée et tracée. Une réservation ne laisse jamais deux patients occuper un lit.

Les admissions programmées créent une demande planifiée. Elles ne bloquent un lit physique qu’à l’intérieur d’une fenêtre de réservation paramétrée, lorsque les conditions sont satisfaites. Une réservation exclusive d’un lit encore occupé n’est pas utilisée en v0.

## 4 Affectation et invariants métier

La politique de référence affecte sous contraintes, puis applique FIFO entre demandes de même priorité. Une règle explicite de vieillissement évite une attente indéfinie ; ses paramètres et priorités sont figés avant comparaison. L’aptitude à entrer dans l’unité dépend du profil, des équipements, de la surveillance et de la capacité disponible.

Les règles de cohabitation sont configurables par établissement. L’isolement est une exigence documentée de chambre et d’environnement, pas un booléen qui garantit à lui seul la compatibilité. Certaines précautions respiratoires comportent des exigences de ventilation [S4]. La v0 encode les contraintes retenues sans prétendre représenter l’ensemble des recommandations cliniques.

**Cohérence physique.** Un lit héberge au plus un patient ; une réservation active appartient à un seul patient ; une tâche ne consomme pas deux fois le même professionnel ; un patient n’est ni perdu ni dupliqué. Les compteurs sont reconstruisibles depuis les événements.

**Fermetures.** Une fermeture prévue empêche de nouvelles réservations selon sa date d’effet. Un lit occupé ne devient pas simplement vide ou fermé. La fermeture physique attend la libération, sauf événement de transfert ou d’évacuation explicitement représenté. Une baisse d’effectif peut créer un déficit de capacité de soins sans supprimer les patients présents.

**Conservation.** Pour chaque périmètre, stock final = stock initial + entrées physiques − sorties physiques. Les sorties sont ventilées par destination et motif. Un décès change l’état du patient ; le lit reste occupé jusqu’au départ physique, avec un délai distinct. Le journal permet aussi de vérifier la conservation des demandes et des réservations.

**Concurrence.** L’ordonnanceur utilise un ordre stable documenté pour les événements simultanés : faits physiques et fins de tâches, invalidations et expirations, réception des observations, puis décisions et transactions. Les cas où un autre ordre admissible changerait un résultat sont testés en sensibilité. Les décisions d’une même date utilisent un instantané défini et des écritures sérialisées.

## 5 Catalogue des événements

Chaque événement possède un identifiant, une entité, une date moteur, un type, des préconditions, un effet et une cause. La distribution des durées et ses paramètres sont versionnés. Le moteur est seul responsable des transitions.

| Événement | Déclenchement | Effet et contrainte |
| --- | --- | --- |
| Arrivée aux urgences | Intensité jour et heure | Création du patient et d’une présence aux urgences |
| Évaluation aux urgences | Délai propre à l’évaluation | Hospitalisation et demande de lit, ou sortie explicite sans hospitalisation |
| Demande programmée | Planning daté | Création, modification ou annulation de demande ; ressources identiques aux autres patients |
| Réservation | Bed manager disponible | Transaction atomique, expiration et motif de refus éventuel |
| Transfert et installation | Réservation et vérification | Déplacement puis occupation ; durée et ressources consommées |
| Aptitude à sortir | Trajectoire exogène par profil | Rend une sortie médicalement possible, sans décision automatique |
| Révocation de l’aptitude | Aléa clinique exogène | Suspend ou annule la sortie et les tâches incompatibles |
| Évaluation médicale | Tour ou réévaluation demandée | Autorise, refuse ou diffère la sortie ; consomme du temps médecin |
| Préparation | Sortie envisagée | Tâches avec dépendances ; achèvement, échec ou travail perdu |
| Demande d’aval complète | Pièces et éligibilité réunies | Démarrage du délai externe associé à la demande |
| Accord d’aval | Fin du délai externe | Rend une condition de destination disponible ; ne déclenche pas seul le départ |
| Départ effectif | Autorisation et conditions réunies | Sortie physique ; libération du lit et besoin de nettoyage |
| Décès ou transfert hors périmètre | Événement exogène ou règle explicite | Motif terminal enregistré ; libération seulement lors du départ physique |
| Déclaration ou correction | Fait à déclarer | Projection différée dans le SI, sans altérer le passé physique |
| Demande de nettoyage | SI ou constat selon variante | Création unique d’une tâche ; déduplication des deux canaux |
| Nettoyage et déclaration | ASH disponible puis fin de tâche | Lit physiquement prêt, puis information disponible selon délai ou omission |
| Fermeture et réouverture | Incident ou décision du cadre | Mise à jour de disponibilité sous les invariants définis |

### Durées et mécanismes externes

L’arrivée suit par défaut un processus de Poisson non homogène. Une variante réserve une intensité journalière aléatoire pour tester une variabilité supplémentaire. Cette variante ne devient pas une description calibrée du réel du seul fait qu’elle existe.

La durée totale de séjour est décomposée en aptitude clinique et délais d’organisation, avec tâches pouvant se chevaucher. Le départ survient lorsque tous les prérequis nécessaires sont satisfaits ; les durées ne sont pas additionnées systématiquement. Aux urgences, évaluation, attente du lit et transfert sont distingués.

Chaque décomposition est calée sous la politique de référence, puis figée pour A0 et A1. Plusieurs décompositions compatibles avec les agrégats sont conservées pour tester l’incertitude sur les mécanismes. Une durée PMSI totale ne sert jamais directement de durée clinique à laquelle seraient ajoutés les mêmes délais [S6].

Le délai d’accès SMR ou EHPAD commence à la réception d’une demande complète et éligible. HospitalOS peut contribuer à avancer cette demande par la préparation, sans réduire le délai exogène tiré pour cette demande. Une annulation ne permet pas de retirer gratuitement une durée plus favorable. L’effet éventuel vient du calendrier de préparation et reste une hypothèse.

Ce mécanisme ne représente pas une compétition territoriale complète pour des places partagées. Aucune conclusion sur la création ou la redistribution de capacité SMR ou EHPAD n’est autorisée en v0.

## 6 Ressources humaines et charge

Les ressources et la politique métier existent dès M1. Les rôles minimaux sont bed manager, cadre, médecin, IDE et ASH. Les présences, compétences, tâches de fond, durées et règles d’interruption sont explicites. Une personne ne peut travailler au-delà de ses minutes disponibles sans que le déficit soit enregistré.

**Unité du proxy.** Minutes de travail par rôle et par plage horaire. La capacité est le temps de présence utilisable après les indisponibilités définies dans le scénario. Les coefficients de besoin courant par patient sont des hypothèses de simulation, non un score SIIPS validé.

La charge demandée est la somme des besoins courants et des tâches ponctuelles. Une tâche de préparation ou d’admission déjà présente dans une file n’est pas recomptée dans un forfait parallèle. Les minutes demandées, exécutées, reportées et non couvertes sont distinctes.

Les besoins courants consomment une part explicite de la capacité. Les tâches ponctuelles utilisent le reliquat et attendent dans une file si nécessaire. Les règles de priorité et d’escalade sont fixées par rôle. Le modèle n’infère pas de conséquence clinique à partir de ce proxy.

À chaque réservation puis installation, une règle d’admission vérifie la capacité projetée sur un horizon configuré à partir des informations accessibles. Une vérification d’exécution traite les changements. Un déficit déjà présent déclenche retard, alerte ou refus de nouvelle admission selon la règle ; il n’efface pas l’occupation existante.

Le nettoyage engagé est non préemptif en v0. Une priorité change l’ordre des tâches en attente, sans raccourcir leur durée. Le scénario doit dire si une tâche engagée se termine à la relève, est transmise ou nécessite une autre plage de travail. Les absences sont traitées par présence réelle et délégation, pas par un délai arbitraire qui permettrait de travailler hors service.

### Deux organisations du nettoyage

**Organisation A.** La déclaration de départ au SI déclenche la demande de nettoyage. Le retard de saisie peut donc retarder cette demande.

**Organisation B.** Le SI et un constat direct ou une communication peuvent déclencher la même demande. La première demande valide crée la tâche ; la seconde est dédupliquée. Constat, communication et saisie ont leurs propres délais et coûts.

Ces organisations sont des variantes de mécanisme. Leurs proportions et paramètres ne sont pas présentés comme mesurés avant recueil terrain.

## 7 Faux système hospitalier

Le faux SI publie des projections déclarées. Il ne garantit ni exhaustivité ni fraîcheur. Il conserve les corrections, les doublons et l’historique nécessaires à une reconstruction bitemporelle. Les références techniques sont figées dans le manifeste.

| Canal | Contrat de la v0 | Limite d’exposition |
| --- | --- | --- |
| Mouvements | HL7 v2.5, sous-ensemble IHE PAM France 2.11.2, ZBE, transport MLLP | N’expose pas automatiquement hygiène, préparation ou réservations |
| API | FHIR R4 4.0.1 ; Patient, Encounter, Location, Task ; extensions documentées si nécessaires | Valeurs déclarées uniquement, avec droits et disponibilité par champ |
| Écrans | Tableau des lits, fiche patient et tâches ; variante d’affichage et de fraîcheur | Informations affichées uniquement ; aucun champ caché du moteur accessible au client |

### Contrat PAM

Le sous-ensemble couvre A05 et A38, A01 et A11, A02 et A12, A03 et A13, et Z99 pour les corrections de mouvements. A08 est exclu d’ITI-31 ; A31 relève d’ITI-30 pour les mises à jour démographiques. A04 et A06 sont inclus seulement si le scénario expose le parcours administratif des urgences et la transition vers hospitalisé [S1].

Le contrat d’implémentation fixe les champs requis, les autorités d’identification, la version du profil, les acquittements, les reprises, la déduplication, les annulations et les corrections historiques. Une prise en charge de ce sous-ensemble n’est pas une déclaration de conformité complète à PAM. Les extensions et options réellement implémentées sont listées.

### Contrat FHIR et écrans

Le code HL7 0116 U signifie inoccupé. La disponibilité d’un lit est reconstruite à partir de plusieurs informations et ne découle pas de ce code seul. Les champs standards sont utilisés lorsque leur sémantique correspond ; tout ajout suit le mécanisme FHIR d’extension, avec URL, définition, type, cardinalité et exemples [S2, S3].

Les statuts de Task décrivent le travail ; le parcours du séjour est rattaché à Encounter ou à des extensions définies. Les champs réservés au moteur, dont l’aptitude clinique future et t_true, sont absents des réponses, du DOM et des ressources servies au navigateur.

La v0 fournit des lectures d’état versionnées. Le mécanisme de notification est documenté : polling ou implémentation explicite de Subscription R4. La présence d’une API FHIR n’implique pas à elle seule des abonnements opérationnels.

### Bruit et critère I1

Les scénarios couvrent retards, saisies groupées, omissions de disponibilité, corrections, annulations, champs manquants, écarts d’horloge, duplications, désordre de livraison et coupures. Chaque perturbation est désactivable. Ses dépendances à la charge et au rôle sont configurables ; le bruit ne doit pas être nécessairement indépendant de la saturation.

I1 vérifie que chaque canal permet de reconstruire ce qu’il expose. Les champs communs convergent vers la même projection déclarée après livraison des événements attendus et réconciliation. Une information jamais déclarée reste inconnue ; la convergence vers l’état vrai n’est pas exigée. Les délais de convergence, règles de priorité des sources et méthodes de récupération après coupure sont fixés avant le test.

## 8 Canal de recommandation

HospitalOS émet une proposition horodatée, fondée sur l’observation disponible à D. Le destinataire peut la refuser, la différer ou l’accepter. Les effets physiques passent par des tâches et des vérifications ; aucun appel de recommandation ne modifie directement l’occupation ou l’aptitude clinique.

| Action | Mécanisme | Coût et limite |
| --- | --- | --- |
| Demander une réévaluation | Avancer une évaluation médicale | Temps médecin ; aucune modification de l’aptitude clinique ; refus de sortie possible |
| Préparer une sortie | Créer ou avancer des tâches éligibles | Temps cadre ou IDE ; prérequis et travail perdu si annulation |
| Proposer un lit pour un patient | Réservation puis installation | Temps bed manager ; concurrence et vérification d’exécution |
| Prioriser le nettoyage | Réordonner les tâches en attente | Temps d’encadrement ; retard possible pour d’autres lits ; tâche engagée non interrompue |
| Signaler une disponibilité probable | Vérifier puis déclarer | Temps professionnel même si le signalement est faux |

L’hébergement hors unité ne fait pas partie des actions actives avant M4. Toute extension future devra conserver les places externes occupées, les compatibilités et le temps passé hors unité.

**Cycle d’action.** Proposition, décision d’acceptation, début d’exécution, achèvement et résultat sont journalisés séparément. Les branches refusée, différée, expirée, annulée, échouée ou devenue inapplicable sont conservées. Une acceptation ne vaut pas exécution.

Chaque recommandation contient un identifiant idempotent, sa durée de validité, sa cible, les observations de justification et ses préconditions. Une relance possède un lien vers la recommandation initiale et ne doit pas créer une seconde tâche équivalente. Le refus ou la lecture peuvent consommer du temps, selon le scénario.

Les paramètres d’adhésion dépendent du rôle, de la disponibilité, de la charge et des sollicitations récentes. Leur forme est une hypothèse, y compris une éventuelle baisse de l’acceptation avec la saturation. L’évaluation inclut des variantes de sensibilité et ne présente pas cette relation comme une loi métier universelle.

Les données d’entraînement contiennent les observations disponibles, les propositions, les réponses et les effets ultérieurement observés. Le journal de vérité n’est pas utilisé pour l’entraînement dans cette révision. L’absence de recommandation, le refus et l’échec restent représentés ; le jeu ne se limite pas aux actions réussies. Des politiques de collecte sûres et variées explorent les actions admissibles, avec leurs probabilités de sélection connues dans le simulateur.

## 9 Calage et statut des paramètres

Les paramètres portent une valeur, une unité, une plage, une source, une population, un millésime et un statut : observé, estimé, hypothèse ou non évaluable. Une valeur technique choisie pour un scénario n’est jamais présentée comme une mesure française.

| Paramètre | Source ou méthode | Usage autorisé |
| --- | --- | --- |
| Capacités et activité annuelle | SAE DREES [S5] | Contraintes et agrégats au périmètre effectivement disponible |
| Durées totales et distributions | PMSI via ATIH ou DREES [S6] | Calage des statistiques disponibles ; vérifier séjour hospitalier versus unité |
| Arrivées jour et heure | ORU Pays de la Loire 2024, figure 19 page 21 [S7] | Forme temporelle des arrivées ; pas décisions vers l’unité cible |
| Destinations | Restitutions PMSI vérifiées pour le périmètre | Catégories et marges uniquement après contrôle de nomenclature |
| Variations NHS | Série et version à inventorier | Sensibilité externe ; ne qualifie pas une unité française |
| Profils du générateur v0.2 | Audit requis | Réutilisation conditionnée à l’audit |
| Décomposition des durées | Ensemble de variantes compatibles | Hypothèses non identifiées par les seuls agrégats |
| Nettoyage, charge, réactions et adhésion | Scénarios puis recueil pilote | Hypothèses jusqu’à mesure pertinente |

Les publications publiques ne garantissent pas un accès aux séries conjointes nécessaires pour estimer les dépendances temporelles d’une unité. Les horodatages RPU sont administratifs et peuvent différer de la présence physique [S7]. Une médiane, un quantile ou une destination manquants ne sont pas inventés.

### Trois jeux séparés

Le jeu de calage sert à estimer les paramètres. Le jeu de validation de développement sert à choisir les variantes et peut être consulté avec journalisation. Le test final est réservé et ouvert une fois par campagne gelée. Une campagne inclut versions, règles, paramètres, métriques, seuils, périmètres et budget de calcul.

Les périodes et établissements sont séparés pour éviter le chevauchement des fenêtres. Les statistiques du test final ne servent ni au calage du simulateur ni au pré-entraînement. Après consultation, une nouvelle modification ne conserve pas le statut de test intact : elle exige un nouveau test réservé ou une qualification explicitement exploratoire.

Chaque variante structurelle est calée sous la référence métier. Les paramètres, présences et primitives exogènes sont ensuite figés entre A0 et A1. Les différences de sorties résultant des actions sont autorisées ; aucun recalage spécifique à HospitalOS n’est effectué.

## 10 Qualifications et critères

Chaque qualification est liée à une version du moteur, du scénario, des interfaces, des politiques et du notateur. Les statuts possibles d’un critère sont réussi, échoué et non évaluable. Le dernier ne compte jamais comme une réussite.

| Qualification | Conditions | Portée |
| --- | --- | --- |
| SIM_GO_INTEGRATION | C1 et I1 réussis sur la suite publiée ; séparation des accès vérifiée | Essais techniques sur le sous-ensemble d’interfaces documenté |
| SIM_GO_PRETRAIN_RESEARCH | Qualification précédente ; contrôles de mécanismes, de fuite et de diversité réussis ; manifeste gelé | Pré-entraînement exploratoire sans revendication terrain ; U1 à mesurer ensuite |
| SIM_QUALIFIED_FOR_SCOPE | Critères réels pertinents réussis sur test réservé, fiche de portée et limites | Comportements observables effectivement validés ; aucune validation causale implicite des actions |

| Critère | Contrat de mesure | Règle de décision |
| --- | --- | --- |
| C1 Cohérence | Invariants à chaque événement ; conservation, ressources, concurrence et sorties | Zéro violation dans la suite exigée ; toute violation bloque l’usage concerné |
| I1 Interfaces | Reconstruction par canal, correction, reprise et convergence déclarée | Tous les cas du contrat passent ; aucune exposition interdite |
| C2 Durées | Médiane, dispersion et queue à population et périmètre identiques | Médiane à ±10 % comme tolérance d’ingénierie proposée ; marges complémentaires gelées avant test ; sinon portée réduite |
| C3 Destinations | Parts, effectifs, incertitudes et nomenclature | Marges par catégorie pré-enregistrées ; ne pas confondre tolérance métier et incertitude d’échantillonnage |
| C4 Dynamique | Occupation, variabilité, autocorrélation, fréquence et durée des tensions | Statistiques, lags, seuil de tension et marges gelés sur le jeu de référence hors test |
| C5 Horaires | Distance de Wasserstein circulaire sur 24 h, séparément par flux | Seuil candidat au 95e percentile des distances entre blocs réels comparables, défini hors test ; sinon non évaluable |
| C6 Diagnostic | Discrimination simulé contre réel sur périodes ou sites distincts | Diagnostic avec incertitude et contrôles de puissance ; aucun seuil bloquant à 0,65 |
| U1 Utilité | Avec ou sans pré-entraînement, mêmes données cibles, architecture et budgets | Effet apparié, incertitude, régimes de dégradation ; aucune conclusion réelle à partir du seul synthétique |

C5 utilise des profils comparables, avec stratification définie par flux et population. Le volume total est évalué séparément. La règle au 95e percentile est un choix méthodologique à pré-enregistrer, pas une norme établie. La matrice agrégée ORU ne fournit pas seule la variabilité entre périodes ou sites.

Les marges C3, les paramètres C4 et les données de référence C5 sont des prérequis à la qualification réelle, pas des raisons de bloquer M1. Une fiche de portée indique les variables, horizons, populations, régimes et critères effectivement évalués. Une qualification limitée aux durées ou aux flux porte exactement cette limite.

Le réalisme observationnel et les effets d’action sont deux niveaux distincts. Les tests par classifieur examinent des distributions ; ils ne valident pas les effets des interventions [S8, S10].

## 11 Évaluation des politiques

### Mesure principale et frontières

La mesure principale est W = intégrale de N_attente(t) entre t0 et t1, en heures-patients. N_attente compte les patients dont la demande est active et qui ne sont pas encore installés, y compris pendant un transfert précédant l’installation. Chaque attente inachevée à t1 contribue jusqu’à t1.

Les stocks initiaux et finaux sont publiés. Les annulations, sorties sans installation, décès et transferts externes sont ventilés séparément, afin qu’une diminution de file ne soit pas interprétée automatiquement comme une amélioration d’accès au lit. Le temps physique aux urgences est une mesure complémentaire distincte.

Les attentes extrêmes sont traitées avec leur censure de fin d’épisode ; les quantiles calculés seulement parmi les patients installés ne constituent pas la mesure principale. Sont également rapportés reports d’admissions programmées, charge demandée et non couverte par rôle, temps de sollicitation, refus d’exécution et violations de contraintes.

La fenêtre est identique pour les politiques. Le moteur part soit d’un instantané cohérent comprenant ancienneté des séjours et attentes, soit d’une mise en régime sous la même référence avant bifurcation. Cette mise en régime est exclue du score. La durée d’épisode et l’effet du stock terminal sont testés en sensibilité.

### Comparaisons appariées

A0 est la politique métier de référence. A1 conserve le même environnement et ajoute les recommandations HospitalOS. Les deux partent du même état et des mêmes primitives exogènes. Les tirages sont indexés par scénario, entité, mécanisme et occurrence, avec espaces de noms séparés pour la politique. Une graine globale seule ne garantit pas le couplage [S9].

Le couplage partage les primitives, pas nécessairement les résultats : si une action change la charge ou l’heure d’une demande, le mécanisme peut produire un résultat différent à partir du même aléa. Les états futurs ne sont pas recopiés entre branches. L’effet rapporté est W(A0) − W(A1), positif pour une réduction d’attente.

Le notateur est indépendant du planificateur et ne reprend pas sa fonction d’utilité pour calculer le résultat principal. Il reconstruit les métriques depuis le journal de vérité, après l’épisode. Ses formules sont vérifiées sur des micro-scénarios calculables à la main. Une indépendance de module ne vaut pas, à elle seule, audit indépendant de toute l’équipe.

### Références et contrôles

| Comparaison | Résultat attendu ou interprétation |
| --- | --- |
| Référence métier | Préparation simple, suivi des lits et affectation sous contraintes ; mêmes informations, ressources et possibilités d’action |
| FIFO passif | Référence secondaire ; jamais seule preuve de valeur |
| Planificateur sans world model | Mêmes actions et contraintes ; prévisions remplacées par des références simples explicitement définies |
| Actions désactivées et sollicitations gratuites | Identité des trajectoires physiques A0 et A1 sous couplage ; contrôle strict de neutralité |
| Acceptation nulle avec sollicitations coûteuses | Aucun effet direct des actions refusées ; effets indirects possibles via charge, délais et politiques ; aucun signe global imposé |
| Information courante parfaite | Diagnostic privilégié sans connaissance du futur ; pas de borne optimale garantie |
| Aval exogène inchangé | Même primitive de délai pour la même demande ; gains possibles par demande plus précoce, sans modification gratuite de l’offre |
| État périmé ou action dupliquée | Refus ou déduplication traçables ; jamais installation incompatible ou double exécution |

Les effets sont présentés avec incertitude, par régime et par variante structurelle. Les unités de réplication sont des scénarios ou blocs indépendants, pas des événements corrélés traités comme observations indépendantes. Le nombre de réplications et la règle d’arrêt sont fixés avant la comparaison, sans arrêt opportuniste sur un résultat favorable.

## 12 Pré entraînement et généralisation

La collecte diversifie les profils, niveaux de tension, durées, organisations et informations disponibles. Les paramètres ne sont pas tous tirés indépendamment : leurs contraintes et corrélations plausibles sont décrites. Un scénario impossible n’est pas une forme utile de diversité.

| Niveau de test | Séparation exigée | Conclusion permise |
| --- | --- | --- |
| Nouveaux épisodes | Graines et épisodes distincts, mêmes mécanismes et plages | Généralisation aux épisodes non vus |
| Nouveaux régimes | Plages ou combinaisons de paramètres réservées | Robustesse au changement de régime testé |
| Nouveaux mécanismes | Formulation ou organisation structurelle réservée | Robustesse aux choix de modélisation effectivement changés |

Les trois niveaux ont des manifestes séparés. Aucun résultat sur des graines nouvelles n’est présenté comme une preuve d’indépendance au simulateur. Une variante structurelle est réservée à U1 avant le pré-entraînement ; une seconde formulation de la sortie, du nettoyage ou de l’adhésion suffit pour commencer.

U1 compare le même modèle avec et sans pré-entraînement, à données cibles et budget d’adaptation identiques. Le coût supplémentaire du pré-entraînement est rapporté séparément ; un comparateur à budget total comparable est ajouté lorsque la revendication porte sur l’efficacité de calcul. Les gains et les transferts négatifs sont publiés, y compris par mécanisme.

Les cibles d’apprentissage utilisent seulement les futurs états déclarés ou effets observés autorisés. Ni aptitude future cachée, ni t_true, ni graine, ni paramètres secrets du moteur ne deviennent des entrées. Les validations de fuite couvrent fichiers, API, écrans, caches et traces d’exécution.

Tout résultat porte la version du simulateur, sa qualification effective, le manifeste des scénarios et la mention « sur simulateur ». Aucune revendication de ROI, de sécurité clinique ou de causalité terrain n’est déduite d’U1 synthétique.

## 13 Recueil au premier pilote

Le recueil vise d’abord à identifier où le temps est consommé et ce qui était connu au moment des décisions. Les sources, modalités de collecte et autorisations sont à convenir avec l’établissement. Les observations directes sont distinguées des horodatages administratifs.

| Domaine | Données minimales |
| --- | --- |
| Accès au lit | Demande, priorité, réservation, refus, départ des urgences, installation |
| Sortie | Sortie envisagée, décision médicale, conditions restantes, demande d’aval, accord, départ physique et déclaration |
| Nettoyage | Demande, prise en charge, début, fin, protocole, déclaration de disponibilité |
| Ressources | Présence par rôle, charge disponible, tâches, interruptions et blocages |
| Recommandation | Contenu présenté, destinataire, informations visibles, réponse, motif, dates, exécution, résultat et effort |

Le dénominateur de l’acceptation est le nombre de recommandations effectivement présentées aux destinataires éligibles. Les propositions générées mais non présentées, doublons, expirations et absences de réponse sont comptés séparément. L’exécution est évaluée distinctement de la réponse déclarée.

En mode observation, « je l’aurais fait » mesure une intention déclarée. Ce taux n’est pas substitué au taux d’exécution. Un recueil d’exécution exige un dispositif où les actions et leurs suites peuvent effectivement être observées. Un effet causal terrain nécessitera un protocole propre, au-delà de cette spécification.

## 14 Plan de construction et critères de sortie

### M1 Moteur métier et notateur

Version moteur 0.1. Construire les entités, le catalogue, les ressources, les tâches et la politique métier de référence. Ajouter réservations atomiques, événements simultanés, initialisation, aléas indexés, conservation et journal de vérité. Prévoir la frontière d’observation même dans le mode initial sans bruit.

**Sortie.** C1 passe sur la suite déterministe et les scénarios extrêmes ; les micro-scénarios du notateur donnent les valeurs attendues. Une campagne de robustesse couvre au minimum 1 000 jours simulés cumulés sur au moins dix graines et plusieurs régimes, sans assimiler ce volume à une preuve générale.

### M2 Interfaces et information imparfaite

Version moteur 0.2. Implémenter le sous-ensemble PAM, l’API FHIR, les écrans, les projections déclarées, les corrections et les perturbations. Documenter champs, versions, limites et droits. Ajouter les tests de fuite et de reprise.

**Sortie.** C1 reste valide, I1 passe et la séparation des accès est vérifiée. SIM_GO_INTEGRATION peut être attribué au contrat effectivement testé.

### M3 Recommandations et comparaisons

Version moteur 0.3. Ajouter les actions HospitalOS, leur cycle complet, leur coût, l’adhésion et les vérifications. Comparer A0 et A1, la référence métier, FIFO et l’ablation sans world model. Couvrir les deux organisations du nettoyage dans les essais de développement.

**Sortie.** Les contrôles corrigés du chapitre 11 passent ; les causes de chaque effet sont traçables. Le rapport contient la mesure intégrée d’attente, les stocks terminaux, les coûts et les scénarios de dégradation. Ce jalon ne présume pas un gain positif.

### M4 Calage et expériences de pré entraînement

Version moteur 0.4. Auditer puis intégrer le générateur, documenter les sources, préparer les trois jeux, caler la référence et figer les variantes. Réserver une formulation structurelle avant entraînement. Exécuter les contrôles de diversité, de mécanismes et de fuite.

**Sortie.** SIM_GO_PRETRAIN_RESEARCH peut être attribué si ses conditions passent ; U1 est ensuite exécuté sur les trois niveaux de généralisation. C2 à C5 sont évalués seulement lorsque les données pertinentes existent. La qualification réelle reste liée à ces données et à une fiche de portée.

Après M4 : médecine polyvalente, hébergement extérieur fini, extensions au pôle et approfondissement des mécanismes. Leurs ressources et leurs frontières doivent être explicites avant toute nouvelle comparaison.

## 15 Matrice de tests de référence

Ces tests définissent des résultats attendus. Ils ne sont pas présentés comme exécutés dans cette révision documentaire.

| Test | Situation | Attendu |
| --- | --- | --- |
| T01 | Deux réservations simultanées du même lit | Une seule réservation active ; refus tracé de l’autre |
| T02 | Lit réservé à P et installation de P | Succès si autres préconditions valides ; réservation consommée |
| T03 | Réservation expirée ou pour Q | Installation de P refusée ; aucun changement d’occupation |
| T04 | SI prêt mais lit encore à nettoyer | Vérification, délai et refus ; aucune installation physique |
| T05 | Sortie autorisée puis aptitude révoquée | Départ bloqué ; tâches et autorisation réévaluées |
| T06 | Décès avec départ physique différé | Patient encore localisé, lit occupé jusqu’au départ, puis nettoyage |
| T07 | Fermeture demandée sur lit occupé | Fermeture prévue ; pas de disparition ni capacité fictive |
| T08 | Deux déclenchements du même nettoyage | Une tâche unique et un seul coût d’exécution |
| T09 | Priorité pendant un nettoyage engagé | Pas d’interruption ; réordonnancement des seules tâches en attente |
| T10 | Recommandation ou message rejoué | Idempotence ; aucun double effet physique |
| T11 | Z99 reçu après une décision historique | État déclaré corrigé ; observation historique à D inchangée |
| T12 | Actions désactivées et coût nul | Trajectoires physiques A0 et A1 identiques sous couplage |
| T13 | Toutes les actions refusées mais lecture coûteuse | Coût conservé ; aucune exécution d’action refusée |
| T14 | Même demande d’aval dans deux branches | Même primitive externe ; début éventuellement déplacé par préparation |
| T15 | Deux patients attendent de 0 à 1 h puis un de 1 à 3 h | W = 4 heures-patients, même si le second attend encore à 3 h |
| T16 | Baisse d’effectif avec patients présents | Déficit enregistré ; occupation conservée ; nouvelles admissions contrôlées |
| T17 | Patient non hospitalisé aux urgences | Sortie explicite ; conservation globale maintenue |
| T18 | Inspection API, DOM, fichiers et traces accessibles | Aucune aptitude future, t_true ou donnée du journal privilégié |
| T19 | Coupure, désordre, annulation et correction | Reconstruction déclarée conforme au contrat après réconciliation |
| T20 | Modification d’une politique sous le même scénario | Paramètres exogènes inchangés ; effets endogènes autorisés et traçables |

Le notateur doit aussi détecter volontairement des journaux falsifiés : patient dupliqué, transition absente, temps négatif, réservation concurrente ou ressource surconsommée non déclarée. Les tolérances numériques sont fixées selon les unités ; les violations discrètes ne sont pas masquées par un arrondi.

## 16 Décisions et prérequis restants

Les décisions d’architecture sont prises dans cette version. Les éléments suivants sont des données ou artefacts à produire, avec une échéance de jalon ; ils ne sont pas des arbitrages laissés ouverts par défaut.

| Élément | Décision ou livrable | Échéance |
| --- | --- | --- |
| Unité | Court séjour gériatrique, puis médecine polyvalente | M1 ; adapter avant calage si terrain mieux documenté |
| Ressources | Minutes par rôle, sans double comptage ; coefficients déclarés comme hypothèses | Avant essais M1 |
| Contrat d’interface | Sous-ensemble PAM, profils FHIR, sources et temporalité | Avant I1 en M2 |
| Générateur v0.2 | Rapport d’audit des distributions, dépendances et sorties cachées | Avant réutilisation, au plus tard M4 |
| Référence C5 | Profils réels comparables distincts du test final | Avant qualification C5 ; sinon non évaluable |
| Marges C3 et C4 | Valeurs, unités, effectifs et règles pré-enregistrés | Avant ouverture du test réel |
| Variante structurelle réservée | Au moins une formulation non utilisée au pré-entraînement | Avant collecte d’entraînement M4 |
| Hébergement extérieur | Désactivé ; extension à ressources finies | Après M4 |
| Pilote | Dictionnaire de recueil et distinction intention, acceptation, exécution | Avant démarrage du recueil concerné |

Chaque campagne conserve le code identifié, le manifeste, les paramètres, les sources, les graines et versions, les journaux d’action, les résultats du notateur, les exclusions et les consultations du test. Un changement de mécanisme ou de règle métier produit une nouvelle version et une analyse d’impact sur les qualifications.

## 17 Sources de référence

Les références suivantes étayent les interfaces, les limites des données et les principes de validation. Les choix propres à HospitalOS, notamment les seuils candidats et les scénarios, restent des décisions d’ingénierie et de recherche. Sources consultées pour les revues du 25 octobre 2026.

- **S1. Interop’Santé.** IHE PAM National Extensions France, version 2.11.2, Trial Implementation, 3 février 2025. Événements, transactions et corrections de mouvements. https://www.interopsante.org/f/07f0be9ab9647f72a3e896fd14620eeba4b1f504/Publication-IHE_FRANCE_PAM_National_Extension_v2.11.2.pdf
- **S2. HL7.** FHIR R4 4.0.1, Location et table 0116. https://hl7.org/fhir/R4/location-definitions.html et https://hl7.org/fhir/R4/v2/0116/index.html
- **S3. HL7.** FHIR R4, Extensibility. https://hl7.org/fhir/R4/extensibility.html
- **S4. SF2H.** Recommandations pour la prévention de la transmission par voie respiratoire. https://www.sf2h.net/k-stock/data/uploads/2024/reco_respiratoire/Prevention_transmission_voie_respiratoire_RECOS_SF2H.pdf
- **S5. DREES.** Bases statistiques SAE. https://data.drees.solidarites-sante.gouv.fr/explore/dataset/708_bases-statistiques-sae/
- **S6. DREES.** Morbidité hospitalière, données jusqu’en 2023, publication du 5 mars 2025 ; distributions de durées issues du PMSI MCO. https://drees.solidarites-sante.gouv.fr/communique-de-presse-jeux-de-donnees/jeux-de-donnees/250305_DATA_morbidite-hospitaliere
- **S7. ORU Pays de la Loire.** Panorama Urgences 2024, décembre 2025. Figure 19 p. 21 : arrivées par jour et heure ; limites des horodatages administratifs. https://www.oru-paysdelaloire.fr/sites/default/files/medias/file/2025_PanoramaORUpdl2024_Regional.pdf
- **S8. Lopez-Paz D et Oquab M.** Revisiting Classifier Two-Sample Tests. https://arxiv.org/abs/1610.06545
- **S9. Winter Simulation Conference 2000.** Experimental Design for Simulation ; synchronisation des nombres aléatoires communs. https://informs-sim.org/wsc00papers/006.PDF
- **S10. Sargent RG.** Verification and validation of simulation models. Journal of Simulation, 2013, 7, 12–24. https://doi.org/10.1057/jos.2012.20
- **S11. HAS.** Check-list de sortie d’hospitalisation supérieure à 24 h, 2015 ; organisation et conditions de sortie. https://www.has-sante.fr/jcms/c_2035081/fr/check-list-de-sortie-d-hospitalisation-superieure-a-24h

## 18 Traçabilité de la consolidation

| Point corrigé | Règle retenue | Chapitres |
| --- | --- | --- |
| Sortie clinique et délais confondus | Aptitude, décision, prérequis et départ distincts ; calage sous référence | 3, 5, 9 |
| État unique du lit | Quatre dimensions du lit et état du séjour lié | 3 |
| Réservation incompatible avec installation | Deux prédicats et consommation atomique de réservation | 3, 15 |
| Information privilégiée exposée | Heure vraie cachée, déclaration et réception séparées | 2, 7, 12 |
| Ressources ajoutées trop tard | Professionnels, tâches et politique métier dès M1 | 6, 14 |
| Gains gratuits ou capacité externe implicite | Coûts, contraintes, aval exogène explicite ; hébergement reporté | 5, 6, 8 |
| Contrôles trop forts ou incorrects | Neutralité sans coût, refus coûteux, diagnostic d’information parfaite | 11 |
| Patients inachevés exclus du score | Intégrale de file, stocks, censure et sorties alternatives | 11 |
| Nouvelles graines assimilées à une généralisation structurelle | Trois niveaux de test et mécanisme réservé | 12 |
| Qualification unique | Intégration, recherche et portée réelle distinctes | 10 |
| Réalisme assimilé à causalité | Effets d’action hypothétiques jusqu’à preuve pertinente | 10, 11, 13 |
| Questions restantes non bornées | Décisions explicites et prérequis rattachés aux jalons | 16 |
