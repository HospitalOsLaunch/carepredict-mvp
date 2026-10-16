# Porte de valeur du pré-entraînement synthétique — v1

Date : 16 octobre 2026. Base inspectée : `bfa1fa7e0a8bbdd8817157a162d65f507568a251`.

Statut : **plan prospectif pour revue ; aucun nouveau résultat de performance**.
L'audit E0 est terminé. Les expériences E1 et E2 sont bloquées par les entrées
manquantes décrites dans le [rapport d'audit](../evidence/foundation_gate_v1/audit.md).
Ce document ne constitue pas un préenregistrement rétroactif des lots 15–17.
Avant toute nouvelle lecture de cibles d'évaluation, compléter et versionner le
registre de lancement ci-dessous. Aucune porte de transfert réel n'est franchie.

## Décision de recherche

Mesurer l'utilité de notre pré-entraînement synthétique avant d'élargir le
générateur et le couplage territorial. Garder les composants et résultats négatifs
existants. Un échec arrête l'investissement dans le candidat et le périmètre
évalués ; il ne démontre pas l'inutilité universelle du synthétique.

Deux questions sont séparées :

1. Quel prévisionniste offre la meilleure référence sur les observations accessibles ?
2. À architecture, données réelles et budget d'ajustement identiques, quel gain
   apporte une initialisation pré-entraînée sur notre synthétique ?

Comparer seulement le petit réseau aux modèles de fondation répond à la première
question, pas à la seconde. « Sans notre synthétique » décrit les références
externes ; cela ne présume pas l'absence de synthétique dans leur pré-entraînement.

La connexion à poids figés utilise l'historique comme contexte sans mettre à jour
les paramètres. L'ajustement des poids constitue une expérience distincte.
Le périmètre autorisé dépend des variables réellement observées : des totaux
d'établissement ne rendent pas identifiables les trajectoires de ses unités.

## Décisions, cibles et pertes

Ces usages sont des hypothèses produit à confirmer avec les professionnels avant
de figer une fonction d'utilité clinique ou organisationnelle.

| Niveau observé | Décision à préparer | Horizon | Quantité prévue et évaluation |
|---|---|---|---|
| Unité | Préparer les lits et l'équipe du lendemain | 24 h, puis 12/48 h | Occupation et file observables ; MAE en unités physiques, quantiles et coût de sous/surestimation à fixer avec le métier |
| Pôle | Répartir les ressources entre unités | 24–72 h | Totaux, pointes et déplacements de tension ; distributions conjointes et violations de contraintes |
| Établissement | Préparer capacités et effectifs | 24 h et 7 jours | Occupation, dépassement des capacités ouvertes et durée de saturation ; scores probabilistes et calibration |
| GHT | Organiser des transferts compatibles | 24–72 h, planification à 7 jours | Disponibilités compatibles, délais et effets dans tous les sites reliés ; coût et regret évalués séparément de la seule prévision |

Une présence aux urgences ne vaut pas automatiquement une attente de lit ; une
charge synthétique n'est pas une mesure SIIPS. Chaque cible doit avoir une
définition, une unité, une population et une procédure de reconstruction propres.
Les moyennes conditionnelles des lots 15–16 sont des prévisions à t+24 h, pas des
distributions calibrées ni une moyenne des 24 heures suivantes.

## Expériences du moins cher au plus cher

Les coûts sont relatifs. Les durées de calcul seront mesurées sur un essai
technique borné avant de réserver une campagne complète.

| ID / coût | Question | Données | Références / contrôle | Critère de passage | Arrêt ou suspension |
|---|---|---|---|---|---|
| E0 — très faible | Les données permettent-elles de construire la cible sans inventer de simultanéité ou d'observabilité ? | Schémas, provenance, documentation et entrées disponibles | Contrat commun et définition de chaque cible | Chronologie commune, couverture du périmètre, cible et disponibilité des observations démontrées ; accès autorisé | BLOQUÉ si une condition manque ; aucune note prédictive calculée |
| E1 — faible, aucune nouvelle formation du réseau | Où se situent les modèles publiés sur notre validation synthétique existante ? | Deux bras du lot 16, six hôpitaux de validation chacun, observations originales restaurées et empreintes vérifiées | Persistance, référence quotidienne, climatologie, réseau et poids existants ; lissage/boosting du lot 17 seulement après récupération vérifiée | Même liste d'origines, horizon, cibles et information ; prédictions archivées avant notation ; rapport complet, même négatif | Suspendre si les observations ou poids manquent ; aucun succès de transfert réel ni ouverture du test final déduit de E1 |
| E2 — faible à modéré | Quelle référence battre sur une vraie série opérationnelle ? | Séries synchronisées d'occupation d'un périmètre documenté ; autres cibles seulement si observables | Modèles de fondation à poids figés, persistance et saisonnalité ; boosting ajusté uniquement sur le train réel | Référence choisie sur développement, puis gelée ; couverture, coût, erreurs par site/régime publiés | Suspendre si E0 échoue ; avec un site, limiter la conclusion à ce site |
| E3 — modéré, campagne pilote contrôlée | Notre pré-entraînement améliore-t-il précision et efficacité en données ? | Train/développement réels séparés des sites et périodes d'évaluation ; mêmes mondes synthétiques versionnés | Même architecture : initialisation aléatoire + réel contre synthétique + même réel ; référence E2 ; versions à poids figés séparées | Porte quantitative ci-dessous ; courbes avec 0/7/30/90 jours réels, trois graines appariées au minimum | NO-GO pour le candidat si le gain utile est exclu ; INCONCLUSIF si la précision statistique ne permet pas de trancher ; pas d'extension GHT |
| E4 — modéré à élevé, conditionnel | Un calibrage inféré améliore-t-il le transfert par rapport à nos distributions initiales ? | Statistiques des seuls sites de train/développement ; références publiques réservées avant calibrage | Paramètres/distributions initiaux et calibrage simple contre inférence par simulation avec sbi | Paramètres récupérables dans des expériences connues, vérifications prédictives sur statistiques non utilisées, puis gain aval sur validation indépendante | Arrêter l'escalade de l'inférence si non-identifiabilité ou absence de gain ; conserver des distributions explicites de scénarios |
| E5 — élevé | Graphe, contexte et adaptation apportent-ils une capacité supplémentaire ? | Familles synthétiques réservées et sites réels de développement selon E0 ; topologies datées | Modèle sans graphe/contexte ; modèle figé ; MinT ; adaptateurs LoRA avec/sans L2-SP et références simples recalibrées | Gain utile, contraintes respectées, oubli borné, distributions évaluées ; géométries et ruptures tenues à l'écart | Repli sur le meilleur modèle plus simple ; adaptation désactivée si elle dégrade les régimes antérieurs |
| E6 — très élevé | La dynamique sous actions et les échanges intersites sont-ils fiables ? | Territoires synthétiques couplés, vrais journaux de transferts si disponibles ; aucun effet réel inventé | Simulateur et hybride à règles ; contrefactuels synthétiques communs ; politiques de référence | Conservation, compatibilité, effets synthétiques retrouvés, absence de déplacement caché de tension ; estimands et seuils causaux gelés avant campagne | Suspendre couplage/planificateur si effets non identifiés ou contraintes violées ; une bonne prévision seule ne passe pas cette porte |
| E7 — élevé, dépendant des accès terrain | Les résultats se reproduisent-ils hors de notre développement ? | Sites et périodes finales réservés ; ensuite prévisions silencieuses | Référence gelée, reproduction par un ingénieur extérieur, revue métier à l'aveugle | Reproduction dans la tolérance déclarée, prédictions horodatées avant issues, critères prédictifs et organisationnels distincts satisfaits | Rapport d'échec ou d'incertitude publié ; aucune action automatique sur cette seule base |

La revue à l'aveugle réel/simulé mesure une facette du réalisme perçu. Un résultat
indiscernable ne démontre ni l'exactitude des mécanismes, ni un effet causal.
Les données eICU réservées peuvent contribuer à une évaluation **patient**
intersite ; elles ne constituent pas à elles seules le test d'un hôpital ou GHT.

## Comparaison commune E1 / E2

Références proposées et identifiants explicites :

- Moirai 2.0 : `Salesforce/moirai-2.0-R-small`.
- Chronos-2 : `amazon/chronos-2` ; Chronos-Bolt peut servir au premier essai de coût,
  mais ne remplace pas silencieusement Chronos-2 dans le tableau final.
- TimesFM 2.5 : `google/timesfm-2.5-200m-pytorch`. La version est explicite ; aucun
  téléchargement automatique d'un modèle « latest ».
- Persistance, même heure quotidienne et climatologie ; boosting/lissage selon
  un protocole et des poids récupérés ou un entraînement nouveau déclaré.

Les SHA des poids, commits des bibliothèques, licences et dépendances exactes
doivent être ajoutés au registre de lancement. `uni2ts@main` dans le projet ne
constitue pas un verrouillage reproductible. Préparer des environnements
d'inférence séparés si les dépendances entrent en conflit avec le projet.

Pour E1 : conserver les deux bras, les 449 origines par flux, l'horizon 24 h et
le pas de 6 h du lot 16 après vérification des manifestes. Le test final demeure
fermé. La MSE historique et son comparateur quotidien restent rapportés ; la MAE
et les comparaisons nouvelles sont identifiées comme nouvelles analyses.
Lire au maximum les 168 dernières heures accessibles pour le tableau commun ;
ne pas transformer des horodatages d'événement en dates de disponibilité.
Le réseau garde ses entrées et poids historiques. Un tableau univarié commun
et un tableau avec les covariables prises en charge restent distincts : ils
comparent des produits différents, sans attribuer l'écart au seul pré-entraînement.

Même granularité et mêmes origines pour tous. Les manquants et pannes ne sont pas
remplacés par la vérité simulée. Un échec d'inférence est compté, sans suppression
opportuniste d'origines. Toute imputation utilise seulement le passé disponible ;
sa règle et son indicateur de manque sont gelés. Si une origine est techniquement
non prédictible, publier le taux de couverture et la règle de repli commune.

MAE pour les prévisions ponctuelles et MSE historique ; CRPS quand une distribution
ou des échantillons appropriés sont disponibles. Pour les modèles ne fournissant
qu'une grille de quantiles, employer un WIS commun et le nommer comme tel.
Ne pas inventer une distribution jointe à partir de quantiles marginaux.
Energy score pour de vrais échantillons conjoints ; vérifier en plus, échantillon
par échantillon, conservation, non-négativité et cohérence des sommes. Un score
probabiliste ne garantit pas ces propriétés. PIT adapté aux cibles discrètes,
couverture des intervalles à 80 % et résultats par régime de tension.

MinT est une référence de réconciliation avec hiérarchie connue et covariance
estimée sur les seules erreurs disponibles de train/développement. MinT ne
reconstitue pas des unités non observées à partir du seul total d'établissement.

## Porte quantitative E3 — proposition à figer avant lancement

Critère principal proposé : gain relatif de MAE d'occupation à 24 h, calculé
par site puis moyenné avec un poids égal par établissement indépendant. Les
sites partageant des ressources sont groupés par territoire indépendant.
Si la MAE de référence vaut zéro, publier l'écart absolu ; ne pas fabriquer un ratio.

- Gain utile proposé : 10 %. GO si la borne inférieure de l'IC à 95 % du gain
  atteint 10 %, contre le contrôle de même architecture et contre la référence
  E2 gelée. L'occupation en régime saturé est un garde-fou préspécifié.
- NO-GO pour le candidat et le périmètre testés si la borne supérieure du gain
  reste inférieure à 10 %. Si l'intervalle recouvre 10 %, résultat INCONCLUSIF.
- Garde-fous : aucune violation nouvelle des contraintes ; borne supérieure de
  dégradation des cibles critiques inférieure à 5 % ; évaluer explicitement le
  régime saturé. Une information insuffisante laisse la porte fermée.
- Les sorties probabilistes doivent aussi satisfaire la couverture 75–85 % pour
  l'intervalle nominal à 80 %, avec précision et largeur documentées ; une moyenne
  ponctuelle n'est pas promue en modèle probabiliste validé.

Rééchantillonnage apparié par établissement/territoire, puis blocs temporels
préspécifiés ; les fenêtres qui se chevauchent ne sont pas des sites indépendants.
Trois graines ne compensent pas un nombre insuffisant d'établissements.
Dimensionner le nombre de sites et la durée sur le train/développement avant de
geler le test final. Le protocole de multiplicité et les blocs restent des champs
de lancement obligatoires ; aucune conclusion finale avant leur fixation.

Pour attribuer un gain au synthétique, conserver architecture, informations,
paramètres d'optimisation, sélection et budget d'ajustement comparables. Publier
aussi le coût total, pré-entraînement compris. L'amélioration à faibles volumes
réels et la qualité à volume maximal répondent à deux questions différentes.

## Données et exclusions qui changent le plan

- **MIMIC-IV :** les dates sont décalées indépendamment par patient. Les durées
  individuelles sont préservées, pas la simultanéité entre patients. Le périmètre
  couvre les patients passés aux urgences ou en réanimation, pas un recensement
  exhaustif de l'hôpital. Ne pas reconstruire une occupation réelle commune en
  additionnant les `transfers` décalés ; les groupes d'années ne rétablissent pas
  cette simultanéité. Utilisable pour des tâches patient compatibles et autorisées.
- **eICU :** données de soins critiques multisites avec temps relatifs à l'admission
  en unité et quelques repères calendaires. Pas de calendrier commun complet
  permettant de déduire les files/lits de tout l'hôpital.
- **SAE / FINESS / GHT :** capacités, activités, identités et rattachements bornent
  les configurations. Ces sources ne suffisent pas à connaître les unités
  internes, les flux horodatés et les règles de partage effectives. Les mécanismes
  non observés restent explicitement hypothétiques.
- **Site réel :** privilégier un export agrégé synchronisé pour E2 ; les données
  patient individuelles ne sont pas nécessaires à ce premier benchmark. Si ADT,
  RUM, RPU ou ViaTrajectoire sont utilisés, leurs cadences, sémantiques, couvertures
  et dates de disponibilité doivent être établies séparément.

Le C2ST et la MMD comparent des représentations comparables, avec séparation par
site et contrôle des effets de mesure. Une non-détection d'écart ne démontre pas
l'équivalence ; des seuils utiles et une analyse de puissance sont nécessaires.
Calibrer le générateur uniquement sur train/développement. Les paramètres non
identifiables ne deviennent pas des estimations précises par l'usage de `sbi`.

Le cadre d'accès et de traitement est qualifié avec le responsable des données
et le DPO ; MR-004 n'est pas une autorisation automatique applicable à tout usage.
Respecter les accords des bases. Publier code, protocole et résultats diffusables,
pas des trajectoires, prédictions individuelles ou poids dérivés protégés par
un accord de données. Aucun accès PhysioNet ni délai d'acceptation n'est présumé.

## Registre obligatoire avant toute nouvelle notation

Le lancement reste bloqué tant que ces champs ne sont pas renseignés :

1. Version/hash du protocole et décision servie ; cibles et population.
2. Provenance, autorisation, empreintes des données ; démonstration de leur
   chronologie commune et de la disponibilité de l'information.
3. IDs des ensembles/site/territoire, périodes, origines, exclusions et embargo
   au moins égal à l'horizon maximal ; interdiction de retoucher le test final.
4. Révisions exactes des poids et logiciels, environnement, entrée commune,
   traitement des manquants, repli et plafonds de calcul.
5. Comparateur principal, scores, effets utiles, garde-fous, rééchantillonnage,
   multiplicité, dimensionnement et traitement des cas indéterminés.
6. Archive horodatée des prédictions avant accès aux issues ; manifeste MLflow
   ou équivalent ; lecteur/reproducteur indépendant désigné.

Une adaptation motivée par un test final transforme ce jeu en développement :
réserver un nouveau test selon le protocole. Ne pas appeler « gel » une liste de
modèles dont les versions et données restent à définir.

## Articulation avec le code et la roadmap

Les lots 1–16 et le correctif du validateur sont dans `main`. Le lot 17 est signalé
dans les notes antérieures comme calculé localement ; dans cette session, son
paquet original complet n'a pas été récupéré. Le code reconstruit ne remplace pas
les prédictions, poids et manifestes originaux. Il n'est pas compté comme résultat
reproduit, et aucune métrique de ce lot n'est republiée ici.

`hospitalos.operational` contient le premier prévisionniste ; ce n'est pas un
pré-entraînement JEPA. `rs_jepa/` est conservé comme chemin de recherche historique.
Son éventuel raccordement au contrat commun demandera une comparaison contrôlée,
pas une suppression ou un remplacement fondé sur le seul nom d'architecture.

La demande du 16 octobre introduit une évaluation réelle précoce, sous réserve
d'accès et d'adéquation des données, avant d'investir dans la chaîne complète.
Elle remplace la séquence « aucun jeu réel avant SYN ». SYN reste une porte de
validation synthétique, sans valider automatiquement un déploiement réel.
Le calendrier précédent est conservé comme historique ; il n'est pas une nouvelle
estimation de ce programme. Recalculer après E0 et le premier temps d'inférence
mesuré, puis après E3, en séparant travail, calcul et délais d'accès.

## Sources primaires consultées le 16 octobre 2026

- [MIMIC-IV 3.1 : population, décalage temporel, accès et partage](https://physionet.org/content/mimiciv/3.1/).
- [eICU : temps et couverture](https://eicu.mit.edu/about/eicu/) et [table patient](https://eicu.mit.edu/eicutables/patient/).
- [SAE, DREES](https://drees.solidarites-sante.gouv.fr/sources-outils-et-enquetes/00-la-statistique-annuelle-des-etablissements-sae), [FINESS, ANS](https://esante.gouv.fr/produits-services/repertoire-finess).
- [Moirai / Uni2TS](https://github.com/SalesforceAIResearch/uni2ts), [Chronos](https://github.com/amazon-science/chronos-forecasting), [TimesFM](https://github.com/google-research/timesfm).
- [Qualification des recherches, CNIL](https://www.cnil.fr/fr/recherches-sante-quelles-formalites), [MR-004](https://www.cnil.fr/fr/declaration/methodologie-de-reference-04-recherches-nimpliquant-pas-la-personne-humaine-etudes-et-evaluations-dans-le-domaine-de-la-sante).
