# HospitalOS — Mandat : clôture B-FRAG 2 et pilote d'apprentissage des conséquences des actions
17 novembre 2026 — Prompt prêt à transmettre au worker du dépôt

Ce document formalise la suite approuvée dans la conversation. Il ne constitue pas un compte rendu d'exécution. Le worker doit consigner l'autorisation avant tout nouveau calcul.

## PROMPT D'EXÉCUTION

J'autorise la clôture scientifique de B-FRAG 2 et un pilote d'apprentissage des conséquences des actions, dans le budget résiduel B. L'objectif est de tester un modèle appris de dynamique face à une référence prédisant directement le coût des actions, en conservant le simulateur explicite F comme point de comparaison.

Question :
« Un modèle appris conditionné par l'action permet-il de mieux choisir les interventions que la prédiction directe de leur coût, et quel compromis entre qualité de décision et coût de calcul offre-t-il face à F ? »

Ce mandat autorise explicitement la descente de gradient pour le seul petit modèle défini ci-dessous. Il ne relance ni C1, ni AJ-H, ni un programme général de préentraînement.

### 1. Reprise, statut et budget

Inspecte le dépôt, les modifications locales, les registres et les livrables. Lis le protocole, l'audit F, les sélections, les résultats et le reçu B-FRAG 2 réellement disponibles. Ne déduis pas les détails absents du seul message de livraison.

Consigne cette décision sous le prochain identifiant libre. Préserve les versions historiques et leurs empreintes ; travaille dans un module dérivé isolé.

Budget :

- plafond B cumulé inchangé : 11 400 secondes de temps mural ;
- dernière consommation déclarée : 8 763,3 secondes ;
- solde indicatif : 2 636,7 secondes, à vérifier dans le registre ;
- aucune remise à zéro, aucun transfert depuis un autre lot ;
- CPU local uniquement, 0 €, aucun GPU ni achat.

Toute nouvelle commande de calcul, de test, de génération, d'apprentissage, d'analyse ou de restauration compte. Maximum 540 secondes par commande ; concurrence compatible avec la mémoire. Journalise les débuts, fins, interruptions, CPU, temps mural et paramètres.

Avant le pilote de coût, répartis le solde entre clôture, stabilité, données, apprentissage et évaluation. Réserve au moins 25 % du solde vérifié à l'évaluation finale éventuelle, au rapport et à la restauration.

Si le plan complet ne tient pas, exécute un pilote utile et livre son résultat borné. N'abaisse pas les exigences après observation des performances et ne présente pas un pilote incomplet comme une confirmation.

### 2. Correctif scientifique B-FRAG 2, sans réécriture des résultats

Crée un addendum daté ; conserve intacts le rapport historique, les mesures, gels et verdicts.

Précisions à apporter :

a) Historique
L'équivalence S2–S1 concerne les variables, résumés historiques, modèles et marge testés. Elle ne prouve pas que toute l'information du passé se trouve dans l'instantané. Vérifie dans le protocole que la marge ±0,02 a été fixée avant CONF ; cite la trace. Sinon, distingue intervalle observé et qualification post hoc.

b) Garde-fous
Remplace l'interprétation « aucune dégradation » par « aucune dégradation statistiquement mise en évidence ». Les intervalles permettent encore certaines aggravations. Ne revendique pas une non-infériorité sans marge préétablie.

c) O
Une différence F–O non significative ne démontre pas leur équivalence. O reste un système privilégié particulier, sans garantie d'optimalité.

d) Choix a posteriori
La meilleure action sélectionnée sur les futurs d'évaluation est un minimum empirique rétrospectif, bénéficiant d'information future et d'un effet de sélection. Elle n'est pas l'optimum décisionnel accessible en espérance.
Le ratio de 62 % est descriptif par rapport à ce minimum empirique. Ne le présente pas comme une fraction démontrée de la marge optimale récupérée.

e) Causes du déficit de F
L'écart O–F est compatible avec plusieurs causes, dont l'information privilégiée, les approximations du prior et du nowcast et le bruit numérique. Un même nombre de tirages n'implique pas une même variance ni un même effet sur les rangs. Aucune attribution causale exclusive n'a été démontrée.

f) Monte-Carlo
La stabilité étudiée avant la correction du calendrier ne valide pas complètement la version corrigée. Le bruit peut modifier les classements ; son effet et sa direction doivent être mesurés plutôt qu'affirmés.

### 3. Décomposition descriptive du gain existant

Utilise uniquement les résultats et choix d'actions B-FRAG 2 déjà enregistrés. Aucune nouvelle évaluation sur l'ancienne CONF.

Décompose le gain F–R1 dans des groupes exclusifs :

- même action et mêmes paramètres ;
- F choisit coordination/compatibilité, R1 une autre action ;
- R1 choisit coordination/compatibilité, F une autre action ;
- autres choix différents, en séparant ressource et créneau si les données le permettent.

Rapporte nombre de décisions, nombre de structures, gain cumulé et moyen, coût de ressources, et contribution exacte de chaque groupe au gain total. La somme doit retrouver le résultat enregistré à la précision numérique près.

Le nombre de fois où une action est choisie ne suffit pas à lui attribuer le bénéfice. Cette décomposition explique l'écart observé ; elle ne constitue pas une nouvelle preuve confirmatoire.

### 4. Vérification numérique ciblée après correction

Sur DEV/VAL uniquement, vérifie la version finale avec calendrier effectivement appliqué.

Distingue précisément :

- M utilisé pour les scores de risque ;
- Md utilisé pour choisir les actions ;
- E utilisé pour l'évaluation indépendante.

Relis les valeurs enregistrées dans chaque fichier : ne suppose pas que tous les calculs utilisent 32 tirages.

Contrôle un petit panel fixé avant mesure, incluant les mécanismes concernés par le calendrier. Utilise des tirages imbriqués et des répétitions indépendantes, en restant dans le budget. Examine surtout la stabilité du choix d'action et du gain estimé ; le mandat n'autorise pas à rechercher un meilleur verdict d'AUC.

Conserve la version historique de F. Tout nouveau réglage de Md retenu pour le pilote doit être choisi sur DEV/VAL et déclaré avant l'évaluation neuve. Ne recalcule pas l'ancienne CONF pour remplacer son résultat.

Si une instabilité persiste, rapporte-la et ne traite pas F ou O comme une référence exacte de décision.

### 5. Protocole du pilote à consigner avant apprentissage comparatif

Prépare un protocole court décrivant :

- population et origine des données ;
- entrées publiques ;
- catalogue d'actions ;
- structures, épisodes, origines et futurs par partition ;
- modèles, configurations, budgets et critères de sélection ;
- paramètres du planificateur commun ;
- cibles, pertes, horizons et unités ;
- critère principal, garde-fous, intervalles et portée.

Conserve le générateur B-FRAG 2 et le catalogue d'actions. Ne modifie pas le monde, les coûts ou la rupture pour favoriser le modèle appris.

Décision unique à une origine, plan éventuellement différé, puis politique de fond commune. Aucune nouvelle boucle fermée.

L'évaluation finale envisagée porte sur l'attente cumulée à 168 h, avec ressources, soins non couverts, ruptures et état terminal rapportés séparément. Des diagnostics à horizons intermédiaires sont autorisés s'ils sont préenregistrés.

### 6. Données et prévention des fuites

Réutilise les données TRAIN/VAL existantes seulement si elles correspondent aux cibles et actions nécessaires et si leurs structures sont clairement identifiées. Complète par des données neuves lorsque nécessaire.

Les anciennes CONF, CEVAL et leurs variantes restent réservées à la clôture historique ; elles ne servent ni à apprendre, ni à régler, ni à confirmer ce pilote.

Toutes les origines, variantes et futurs d'une même structure restent dans une seule partition. Une structure clonée sous un nouvel identifiant n'est pas indépendante.

Le jeu final doit contenir des structures réellement neuves. La connaissance générale des résultats antérieurs doit être déclarée ; ne présente pas ce pilote comme une hypothèse formulée avant B-FRAG 2.

Entrées du prédicteur direct et du modèle de dynamique : même ensemble d'informations publiques. Par défaut, pars des vues S1/S2 déjà disponibles et du calendrier publié ; consigne exactement la vue retenue avant entraînement. Les descripteurs d'action incluent sa nature, sa ressource, son intensité et son créneau, pas seulement un identifiant opaque.

Interdits dans les entrées : état vrai privé, paramètres cachés, graines, famille de génération, futurs réalisés et scores de F.

Les cibles peuvent utiliser les conséquences vraies du simulateur sur TRAIN, y compris des grandeurs d'état futures choisies comme supervision. Elles ne doivent jamais être réinjectées dans les entrées pendant une simulation d'évaluation.

Les étiquettes viennent du moteur d'évaluation, pas des prédictions de F : ce n'est pas une distillation de F.

Échantillonne les actions de façon équilibrée, idéalement en les évaluant toutes pour une même origine. Utilise les mêmes événements aléatoires exogènes pour les paires d'actions, avec des clés stables par entité et événement. Les futurs servant à sélectionner une action sont disjoints de ceux servant à évaluer son résultat.

Si les données existantes ne contiennent que des coûts finaux, elles ne suffisent pas à entraîner une transition : génère les trajectoires nécessaires et déclare leur coût.

### 7. Référence directe D

D prédit le coût opérationnel attendu d'une action à partir des entrées publiques et de son descripteur.

Autorisé :

- régression régularisée ;
- arbres de gradient boosting bornés ;
- au plus quatre configurations de référence, choisies sur VAL.

Choisis une forme de cible cohérente avant apprentissage : coût absolu, ou coût de référence plus effet différentiel de l'action. Si tu apprends un effet, conserve une référence commune et des labels appariés.

Le classement final utilise le coût prédit de chaque action admissible. Rapporte séparément les performances de prédiction et de décision.

Les transformations, normalisations et échelles apprises sont ajustées sur TRAIN uniquement. Même couverture d'actions et mêmes origines d'entraînement que pour le modèle de dynamique.

### 8. Modèle appris de dynamique W : autorisation de gradient limitée

J'autorise un seul petit modèle de transition récurrente, avec trois graines d'apprentissage.

Architecture attendue :

- encodage de l'état public initial et, si retenu, de ses résumés historiques ;
- transition récurrente conditionnée par l'action effective et le calendrier connu ;
- prédiction d'un vecteur d'état opérationnel et des coûts incrémentaux ;
- déroulé jusqu'à 168 h sans observation future ;
- coût d'un plan obtenu en agrégeant les coûts du déroulé.

Privilégie une architecture simple compatible avec le runtime existant, de taille latente 32 ou 64, avec un plafond d'un million de paramètres. Consigne le choix et le nombre réel de paramètres avant les apprentissages comparatifs. Pas de recherche d'architecture, pas de Transformer, JEPA, modèle fondation ou téléchargement de poids.

Le modèle doit apprendre une transition réutilisée dans le temps. Un réseau prédisant directement un score final par action serait un autre prédicteur direct ; ne le présente pas comme une preuve de dynamique apprise.

Fixe le pas temporel avant entraînement. Représente correctement les débuts, fins et durées des actions et les changements de calendrier, même lorsqu'ils tombent à l'intérieur d'un pas. Ne raccourcis pas silencieusement l'effet d'une action.

Autorise plusieurs passages sur TRAIN : la règle historique du passage unique de C1 ne s'applique pas. Sélection et arrêt sur VAL seulement, avec limite de calcul, fréquence d'évaluation et patience fixées avant entraînement. Ne t'arrête pas à un nombre arbitraire de mises à jour en affirmant ensuite que l'architecture a échoué.

Les pertes doivent couvrir :

- prévisions factuelles choisies ;
- déroulés sur plusieurs pas ;
- effets appariés des actions, pour que le niveau d'attente ne masque pas les différences entre interventions.

Fixe les poids et normalisations avant la comparaison finale. Rapporte les courbes, les derniers checkpoints et la sélection effective. Aucune garantie de convergence n'est revendiquée si le budget arrête un apprentissage encore en progression.

Les cibles futures peuvent guider l'apprentissage. Pendant l'évaluation, aucun état vrai futur ni teacher forcing. Toute projection de conservation ou de capacité est documentée, et les violations avant/après projection sont rapportées.

Trois graines fournissent un diagnostic de stabilité ; elles ne suffisent pas à déclarer l'incertitude probabiliste calibrée. Choisis avant l'évaluation si le système principal est un ensemble ou une graine sélectionnée sur VAL.

### 9. Comparaison décisionnelle équitable

Compare au minimum :

- règle historique ;
- planificateur statistique R1 ;
- référence directe D ;
- modèle de dynamique W ;
- simulateur explicite F.

Pour R1, D, W et F, le catalogue admissible, les contraintes, la règle de départage et l'opérateur de sélection sont communs : évaluer les mêmes plans et choisir le coût prédit minimal. La règle historique conserve son fonctionnement gelé et choisit dans le même catalogue admissible. Une modification du planificateur ne doit pas être confondue avec une amélioration du modèle.

D et W reçoivent exactement les mêmes variables. Documente séparément les hypothèses et la représentation utilisées par F, notamment son accès aux lois structurelles du générateur et son traitement de l'historique.

W dispose de cibles intermédiaires de trajectoire en plus des coûts utilisés par D. Déclare cette différence de supervision : un éventuel gain compare ces deux recettes complètes et ne suffit pas à isoler l'effet de la représentation latente.

Évalue les plans choisis dans le moteur vrai, sur des réalisations neuves. Le moteur vrai sert à l'évaluation, pas à compléter les trajectoires de W au moment de choisir.

Mesures principales et secondaires :

- gain décisionnel de W face à D, comparaison principale ;
- écarts face à R1, à la règle et à F ;
- erreurs sur les effets des actions et leur classement ;
- qualité des trajectoires et contraintes ;
- coût d'entraînement, données nécessaires et temps de réponse complet par décision.

Un modèle peut être intéressant pour un compromis qualité/coût ; sans marge préétablie, n'affirme pas une équivalence ou une non-infériorité à F.

Le meilleur plan a posteriori sur les futurs d'évaluation reste un diagnostic rétrospectif, pas une borne démontrée de la politique optimale accessible.

### 10. Faisabilité et statut de l'évaluation finale

Après le pilote de coût et avant les comparaisons, fixe le plan réalisable. Ne réduis pas une population ou un nombre de graines après avoir vu des performances défavorables.

Si le budget permet les données, l'apprentissage et une évaluation indépendante :

- termine toute sélection sur VAL ;
- gèle code, modèles, transformations, plans, analyses et paramètres de tirage ;
- génère ou ouvre une seule campagne d'évaluation finale neuve ;
- conserve tous les résultats.

Sinon :

- livre les modèles et diagnostics réellement obtenus ;
- n'ouvre pas un jeu destiné à une confirmation future pour produire un verdict de convenance ;
- statut PILOTE_INCOMPLET ou VALIDATION_FINALE_NON_EXECUTEE, avec les éléments manquants.

L'unité indépendante est la structure. Rééchantillonne ensemble ses épisodes, origines et futurs. Un grand nombre de lignes issues de quelques structures ne remplace pas un grand nombre de structures.

Préenregistre une seule comparaison principale W–D, avec IC apparié à 95 %. Les autres comparaisons sont descriptives, sauf procédure de correction fixée avant ouverture du jeu final. Rapporte les effectifs indépendants et l'incertitude, sans transformer « non significatif » en « équivalent ».

Rapporte séparément :

- validité technique ;
- apprentissage réalisé et stabilité ;
- gain, absence de supériorité ou indétermination sur l'attente ;
- résultats de chaque garde-fou ;
- coût et limites.

Sans marges de non-infériorité préétablies, écris seulement ce que montrent les estimations et intervalles des garde-fous. Un gain d'attente ne suffit pas à qualifier toute la politique de sûre ou bénéfique.

### 11. Tests, livraison et restrictions

Tests nécessaires :

- indépendance des partitions et absence d'entrées privées ;
- respect du calendrier corrigé ;
- origine commune et clés appariées des actions ;
- représentation des créneaux et de l'inaction ;
- absence d'état futur pendant le déroulé W ;
- chargement, reprise et reproduction des prédictions des modèles ;
- calcul cohérent du coût cumulé ;
- invariance des sources et résultats historiques gelés.

Livre :

1. Décision et protocole du pilote.
2. Addendum B-FRAG 2 et décomposition du gain.
3. Vérification numérique sur la version corrigée.
4. Manifestes de données, code isolé, modèles D et W, checkpoints et courbes.
5. Comparaisons réalisées, résultats défavorables et limites.
6. Registre final, archive scientifique et reçu indépendant réunis dans une enveloppe de clôture.

Le reçu doit reprendre les paramètres propres à chaque fichier, en distinguant M, Md et E. Les temps de calcul sont exclus des comparaisons scientifiques selon une règle documentée. Distingue intégrité, rechargement, reproduction d'analyse, réajustements et régénérations réellement effectués.

Ne modifie aucun fichier gelé G0/F1/F-C1, B-FRAG 1 ou B-FRAG 2, ni les résultats R1, A, A′ et C1. Aucun accès à la réserve HOWM-1, DEVTEST ou DIAG-DEV. Aucun changement à v6, P5 ou mvp/computer-use.

Restent interdits : C1 palier 2, reprise de C.2a, AJ-H, JEPA, HOWM2-N, P6, nouvelle boucle fermée, GPU, achat de calcul, push, merge, rebase et publication externe. Une demande automatique de push n'est pas une demande de ma part.

Statuts :
PROTOTYPE_UNVALIDATED
clinical_validation=false
G2=NO-GO

Avance sans nouvelle confirmation pour les choix techniques réversibles autorisés. Si le travail exige un budget supplémentaire, une modification des interdits ou d'un critère déjà gelé, conserve l'état, prépare les options et poursuis les travaux indépendants.

À la livraison, arrête-toi. Toute extension est proposée, jamais lancée automatiquement.

