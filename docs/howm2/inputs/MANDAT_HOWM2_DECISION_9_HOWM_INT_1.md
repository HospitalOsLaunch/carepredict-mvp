# HospitalOS — Campagne intégrée de construction et d’apprentissage du world model
17 novembre 2026 — Mandat prêt à transmettre au worker du dépôt

Ce document formalise la suite approuvée dans la conversation : passer des micro-pilotes à une campagne intégrée. Il définit un nouveau plafond de calcul local, choisi pour dimensionner la campagne ; ce plafond n’est ni une estimation de durée ni une dépense déjà engagée. Aucun entraînement n’a été lancé depuis cette conversation.

## PROMPT D’EXÉCUTION

J’autorise une campagne intégrée de construction, d’apprentissage et d’évaluation du world model hospitalier, sous le nom de travail HOWM-INT-1. Utilise un autre identifiant si celui-ci existe déjà. Enregistre le prochain numéro de décision libre ; ne suppose pas qu’il s’agit nécessairement du n° 9.

**Livrable visé : un système appris qui représente les dépendances entre unités et ressources, simule des interventions et révise ses décisions au cours du temps.**

Deux tâches sont couvertes par ce même mandat :

1. **Tâche principale :** pilotage du périmètre actuel pendant 168 h, avec nouvelles observations et replanification quotidienne.
2. **Extension :** pilotage d’une maquette opérationnelle de plusieurs services pendant 24 h, avec replanification toutes les 6 h et test sur une taille d’hôpital non vue en entraînement.

Ce programme est autorisé dans son ensemble. Avance de façon autonome entre les lots. Les diagnostics et corrections techniques font partie du travail ; ils ne nécessitent pas une nouvelle décision utilisateur à chaque étape.

### 1. Point de départ et reprise

Lis les instructions applicables au dépôt, puis vérifie l’état effectif du code, des registres, des données et des checkpoints. Le dernier état livré annoncé est la décision n° 8, commit local 8a3e5c8, branche claude/hospitalos-auto-first-p0-p4-s2dywn. Ce sont des indications à vérifier, pas une preuve de présence dans le worker courant.

Éléments acquis à conserver :

- B-FRAG 2 : gain décisionnel de F sur R1 de 253,984375 patients-minutes ; portée précisée par l’addendum.
- Pilote W : 200 structures TRAIN, un petit modèle récurrent de 26 144 paramètres ; comparaison principale W–D indéterminée et estimation défavorable à W.
- Diagnostic descriptif : le déficit W–D se concentre dans la famille SF1 du nettoyage.
- Aucun bénéfice d’un modèle latent général, aucune validation réelle ou clinique n’est établi.

Crée un module dérivé et, si utile, une branche locale de travail. Préserve les sources, gels, résultats et archives historiques. Les nouvelles variantes de F, R1 et du générateur portent des noms et empreintes distincts.

### 2. Ressources et autonomie

**Nouvelle enveloppe propre à HOWM-INT-1 :**

- 72 heures de temps mural comptabilisé, soit 259 200 secondes ;
- plafond complémentaire de 288 heures CPU cumulées ;
- calcul local uniquement, 0 € de dépense ;
- pas de GPU ni de location de calcul dans ce mandat ;
- pas de consommation ni de remise à zéro du reliquat B, qui reste dans son registre historique.

Le temps mural comptabilisé est la somme des durées des commandes principales enregistrées. Un groupe de processus lancé par une même commande est compté une fois en mural ; le CPU de tous ses descendants est additionné. Deux commandes principales concurrentes restent toutes deux comptées, de façon conservatrice. Ne double-compte pas les descendants comme de nouvelles commandes principales. Ce plafond ne constitue pas un engagement sur le délai calendaire.

Répartition initiale, réallouable automatiquement dans le total :

| Lot | Enveloppe initiale |
|---|---:|
| Reprise, architecture, moteur, tests et pilote de coût | 3 h |
| Génération et qualification des données | 18 h |
| Apprentissages, courbes et diagnostics | 30 h |
| Évaluation finale | 12 h |
| Rapport, archive et restauration | 2 h |
| Réserve | 7 h |

Réserve effectivement le coût projeté de l’évaluation et de la livraison avant de consommer le budget d’apprentissage. Une réallocation documentée n’exige pas une nouvelle approbation.

Mesure d’abord débit de génération, mémoire, étapes d’entraînement et coût de décision sur des cas représentatifs, notamment à 2, 4 et 8 unités. Projette les coûts avec la concurrence réellement mesurée. Aucun calcul de durée fondé uniquement sur une division par le nombre théorique de cœurs.

Conserve la limite de 540 s par commande. Enchaîne automatiquement les commandes et reprends depuis les checkpoints : cette limite ne doit pas devenir un arrêt de programme ni une demande répétée à l’utilisateur. Prévois le temps d’écriture du checkpoint avant expiration.

Aucune extension payante n’est autorisée implicitement. Si les ressources deviennent réellement insuffisantes, optimise et réalloue dans le plafond, livre ce qui est construit et chiffre précisément l’extension manquante. Ne transforme pas discrètement la campagne en un nouveau pilote de 200 situations.

### 3. Monde et décisions répétées

Conserve un mode à deux unités permettant de relier les nouveaux résultats aux expériences précédentes. Développe un générateur paramétrable à 4 et 8 unités, avec ressources de nettoyage, transport et personnel partagées, compatibilité des lits et contraintes d’aval explicitement définies.

Une maquette à 12 unités servira au test de changement de taille. Il s’agit d’une extension opérationnelle synthétique, pas d’une représentation exhaustive ou validée d’un hôpital réel.

Réutilise les mécanismes existants lorsqu’ils sont compatibles. Chaque mécanisme ajouté doit avoir un rôle identifiable, des unités physiques, des paramètres et un test de cohérence. Évite d’introduire simultanément de nombreux phénomènes sans pouvoir en contrôler les effets.

Avant les comparaisons de modèles :

- qualifie les régimes nominal, tendu et fragile sous une politique de référence fixe ;
- vérifie qu’ils ne sont pas tous saturés dès le départ ;
- conserve aussi des cas où les règles simples suffisent ;
- fixe la distribution des mécanismes et leur combinaison ;
- vérifie la convention temporelle : aucun événement postérieur à l’instant de décision ne doit apparaître dans les entrées publiques.

Ne règle pas la difficulté ou la fréquence des ruptures en fonction des performances de W.

Sur 168 h, décisions à t = 0, 24, 48, 72, 96, 120 et 144 h. Sur 24 h, décisions à t = 0, 6, 12 et 18 h. À chaque décision, chaque politique reçoit uniquement son propre historique public, issu de ses actions antérieures.

Les observations et files des différentes politiques peuvent diverger : ne réutilise jamais pour W un état futur observé sous F ou sous la politique de référence.

### 4. Catalogue, engagements et coûts

Pars du catalogue existant : coordination/compatibilité, renfort nettoyage, renfort transport, inaction. Étends-le aux unités et ressources du nouveau monde avec des descripteurs explicites.

Une intervention doit avoir une portée, une durée, un début, un coût de ressource et des conditions d’admissibilité. Fixe avant comparaison les budgets journaliers et hebdomadaires, ainsi que leur adaptation à la taille de l’établissement.

Pour le mode à deux unités, utilise comme point de départ un plafond de 8 heures-agents supplémentaires par jour, 56 sur la semaine. Documente toute adaptation avant les apprentissages comparatifs.

Empêche :

- le cumul involontaire de plusieurs renforts sur le même créneau ;
- l’annulation gratuite d’engagements déjà commencés ;
- la répétition gratuite d’une tâche de coordination déjà exécutée ;
- la réinitialisation du budget à chaque projection du planificateur ;
- l’accès aux arrivées ou absences futures non publiées.

Le planificateur compare des séquences d’interventions et n’exécute que la partie correspondant à la décision courante. La politique de fond, les délais d’exécution et le traitement des engagements sont communs à tous les concurrents.

### 5. Corpus à grande échelle

Construis deux paliers emboîtés : **1 000 puis 10 000 structures d’entraînement**. Le passage à 10 000 fait partie du mandat : il n’est pas conditionné à une significativité à 1 000.

Répartition cible à 10 000 : 6 000 structures à deux unités, 2 000 à quatre et 2 000 à huit. Conserve les proportions au palier 1 000. Le pilote de coût peut conduire à une autre répartition documentée avant les apprentissages comparatifs.

Pour chaque structure, vise au moins trois situations de décision distinctes, plusieurs épisodes/régimes et des actions ou séquences appariées. Décorrèle explicitement famille, indice de structure, épisode et heure de décision : un choix du type « épisode = indice modulo 3 » ne doit pas confondre un mécanisme avec une heure de départ.

Utilise au moins deux réalisations futures par origine, avec un sous-ensemble fixé à l’avance comportant davantage de réalisations, par exemple huit, pour mesurer le bruit des effets. Augmente le nombre de futurs là où ce diagnostic montre qu’ils sont plus utiles que de nouvelles origines, sans consulter le test final.

Les données doivent couvrir des séquences et des états visités par des politiques différentes : règle historique, politique exploratoire admissible et modèles intermédiaires sur TRAIN uniquement. Journalise la provenance. Les références directes ont accès au même corpus autorisé.

Génère les conséquences avec le moteur vrai ; ce n’est pas une distillation de F. Les états privés futurs sont autorisés comme cibles TRAIN, jamais comme entrées au moment de choisir.

Sépare par structure et par provenance de scénario :

- TRAIN et les deux paliers emboîtés ;
- développement et VAL pour sélectionner les modèles ;
- test final neuf ;
- tests de configurations et de taille non vues.

Aucun clone de structure sous un nouvel identifiant ne compte comme indépendance. Les anciennes CONF et CEVAL restent exclues de l’apprentissage et de la sélection. La réserve HOWM-1, DEVTEST et DIAG-DEV restent fermées.

### 6. Modèle appris structuré

Implémente une famille de modèles partageant ses paramètres entre unités et ressources. La représentation doit pouvoir traiter un nombre variable de nœuds et les relations entre unités, lits, ressources et aval.

Architecture de référence :

- encodeur de l’historique public et des événements disponibles à l’origine ;
- composante d’état opérationnel explicite ;
- composante latente récurrente pour ce qui n’est pas représenté directement ;
- échanges d’information entre unités et ressources liées ;
- transition conditionnée par les interventions et les calendriers connus ;
- sorties : états, flux, coûts incrémentaux et prévisions de rupture.

Préserve les contraintes essentielles par construction lorsque possible : comptes non négatifs, capacité, conservation des patients et cohérence des flux. Rapporte toute projection et les erreurs avant/après ; ne masque pas une mauvaise dynamique par une correction finale non documentée.

Deux tailles principales, à préciser après profilage :

- S : ordre de grandeur 0,1 à 0,5 million de paramètres ;
- M : ordre de grandeur 1 à 3 millions.

Ce sont des cibles de capacité, pas une obligation d’ajouter des paramètres inutiles. Ne réduis pas silencieusement les deux tailles au modèle précédent de 26 144 paramètres.

Trois graines par taille. Vise les deux tailles aux deux paliers, soit douze points d’apprentissage. Une continuation du palier 1 000 vers 10 000 est autorisée pour économiser du calcul ; indique alors qu’il s’agit d’une trajectoire d’apprentissage avec curriculum, pas de deux entraînements indépendants depuis zéro.

Plusieurs passages sur TRAIN sont autorisés. Utilise des fenêtres temporelles et un curriculum d’horizon pour maîtriser le coût, en conservant un entraînement et une validation de déroulés longs. Aucune observation future pendant un déroulé d’évaluation ouvert.

Déclare la méthode de représentation de l’incertitude. Une moyenne de trois graines ne suffit pas à affirmer une calibration probabiliste. Si le modèle ne produit qu’une espérance, limite les conclusions à cette espérance et mesure séparément la capacité à prévoir une rupture.

### 7. Apprentissage et diagnostic intégrés

Les pertes doivent rendre visibles les effets des actions, y compris lorsqu’ils sont petits devant le niveau d’attente : états/flux, coûts par pas, coût cumulé et effets appariés. Normalise avec TRAIN uniquement.

Le diagnostic SF1 est une tâche interne du programme :

- capacité à ajuster un petit ensemble d’exemples TRAIN, dont des cas de nettoyage ;
- erreurs d’effet sur TRAIN et VAL ;
- erreurs sur les meilleures actions et sur les écarts entre ces actions ;
- dérive avec l’horizon ;
- couverture des créneaux, régimes et situations critiques.

Distingue défaut d’implémentation, optimisation, manque de données et généralisation. Une baisse de la perte TRAIN ne démontre pas qu’un entraînement plus long améliore VAL.

Conçois une sélection VAL suffisamment stable : panel plus large que les 18 structures précédentes, mêmes futurs entre checkpoints, métriques d’effets et de décision rapportées ensemble. Fixe les règles de sélection et d’arrêt avant chaque apprentissage comparatif.

Tu peux corriger les bugs, les échelles, les lots, le curriculum, les problèmes de mémoire et une recette d’optimisation manifestement inadaptée dans le budget. Consigne les changements et conserve les essais défavorables. Ne multiplie pas les architectures : garde les deux tailles de la même famille et au plus quatre variantes courtes de recette d’optimisation avant les apprentissages retenus.

Une contre-performance à un palier déclenche le diagnostic et les travaux indépendants ; elle ne clôt pas automatiquement toute la campagne.

### 8. Références fortes et comparaison équitable

Conserve :

1. la règle historique et une règle robuste utilisant les informations publiques ;
2. une référence directe D prédisant le coût d’une **séquence** d’actions ;
3. R1, avec sa dynamique statistique ;
4. F, avec sa simulation explicite ;
5. W, le modèle appris.

D reçoit les mêmes informations publiques et les mêmes descripteurs de séquence que W. Réutilise Ridge/HGB et ajoute une référence directe de capacité comparable si le profilage le permet. Le développement de D dispose d’un budget explicite ; ne le laisse pas à l’état du petit pilote pendant que W bénéficie du nouveau corpus.

Pour les méthodes qui planifient, utilise les mêmes séquences admissibles, contraintes, horizon, règle de départage et procédure de recherche. Fixe le nombre de candidats après profilage. Privilégie une recherche bornée et reproductible ; rapporte à part toute expérience où le modèle change aussi le générateur de candidats.

F et R1 doivent être adaptés explicitement au nouveau moteur. Le F historique n’est pas automatiquement une référence exacte pour plusieurs unités ou plusieurs décisions. Aucun accès privilégié aux paramètres cachés, graines ou futurs pour ces concurrents publics.

Mesure les coûts de préparation des entrées, d’estimation initiale, de recherche et de décision. Chronomètre chaque méthode séparément, sur un matériel et un mode de concurrence précisés. Ne compare pas un temps CPU à une latence murale sans distinction.

Préserve un petit diagnostic privilégié sur DEV pour séparer information, dynamique et recherche lorsque c’est utile ; ce diagnostic ne constitue pas une politique optimale garantie.

### 9. Fragilités, temporalité et généralisation

Évalue trois questions distinctes :

- **Anticipation :** quelle situation risque de franchir le seuil de rupture, à quel horizon et avec quelle calibration ?
- **Intervention :** quelle séquence réduit effectivement le coût dans les futurs du moteur ?
- **Propagation :** quel couplage transmet un effet à une autre unité ?

Pour la propagation, prévois des contrôles appariés où un canal est modifié de façon isolée et interprétable, en conservant les autres mécanismes et les événements exogènes autant que possible. Si le contrôle change aussi la capacité totale ou plusieurs canaux, rapporte ce mélange plutôt qu’une preuve causale spécifique.

Prévois sur VAL des ablations bornées : historique complet contre instantané, échanges entre unités contre variante sans ces échanges, et petite contre grande taille. Leur rôle est de diagnostiquer la contribution de ces choix. Ne prétends pas isoler « le latent » si la supervision, la capacité et les contraintes changent simultanément.

Le test de généralisation sépare :

- nouveaux établissements de la distribution d’entraînement ;
- nouvelles combinaisons ou intensités de contraintes, définies avant apprentissage ;
- changement de taille vers 12 unités.

Le succès dans ces mondes ne vaut pas transfert démontré vers des établissements réels.

### 10. Évaluation finale unique

Constitue les partitions finales sans en consulter les résultats. Cibles initiales :

| Panel | Structures | Épisodes | Rôle |
|---|---:|---:|---|
| Deux unités, décisions quotidiennes pendant 7 jours | 200 | 3 | Comparaison principale |
| Quatre et huit unités, décisions toutes les 6 h pendant 24 h | 96, moitié par taille | 3 | Extension descriptive |
| Combinaisons de contraintes nouvelles | 48 | 3 | Généralisation descriptive |
| Douze unités non vues en entraînement | 48 | 3 | Généralisation de taille descriptive |

Vise quatre réalisations futures indépendantes par épisode, communes entre politiques. Les aléas exogènes sont indexés par entité/événement, pas par un générateur séquentiel dont la consommation dépendrait des actions.

La politique est réexécutée en boucle fermée dans chaque réalisation, avec ses observations propres. Les futurs internes utilisés pour planifier restent disjoints du futur réalisé servant à évaluer.

W, D et les règles sont évalués sur tout le panel principal. F et R1 peuvent être limités, pour le coût, à un sous-panel commun préfixé de 32 structures du panel principal ; les résultats W/D/règles sur ce même sous-panel sont alors rapportés pour comparaison. Tout sous-panel de l’extension est également fixé avant ouverture. Ne mélange pas des moyennes provenant de panels différents.

Le pilote de coût peut ajuster ces volumes avant les apprentissages comparatifs et avant toute ouverture du test. Consigne le plan réalisable et sa précision attendue à partir de DEV/VAL. Un changement d’effectif après observation de résultats finaux est interdit. Préfère réduire le sous-panel des simulateurs coûteux à sacrifier les structures indépendantes de la comparaison principale.

Après sélection sur VAL, gèle modèles, transformations, moteur, distribution, actions, planificateur, tailles de panel et analyse. Lance une seule campagne finale, reprenable par fichiers vérifiés. Toute analyse supplémentaire du test devient exploratoire et ne sert pas à modifier le système évalué.

### 11. Questions principales et portée des résultats

Sélectionne sur VAL la meilleure référence peu coûteuse parmi D et les règles définies, puis gèle-la comme B*. F et R1 restent des comparateurs explicites secondaires sur leur sous-panel.

**Comparaison principale unique :** attente cumulée de B* moins attente cumulée de W sur les sept jours, positive si W est meilleur. Moyenne et intervalle appariés, avec rééchantillonnage par structure regroupant tous ses épisodes et futurs. Rapporte aussi la distribution des effets et les cas défavorables.

Une borne basse à 95 % supérieure à zéro soutient un gain sur cette comparaison. Une différence non significative n’établit aucune équivalence.

**Ambition de recherche :** réduction d’au moins 5 % de l’attente moyenne face à B*. Ce seuil est une cible proposée pour cette campagne, pas une estimation déjà obtenue ni un seuil clinique. Rapporte séparément :

- gain statistiquement établi ;
- estimation du gain relatif et son intervalle ;
- cible de 5 % atteinte en estimation ou soutenue par l’intervalle ;
- résultats de chacun des garde-fous.

Calcule le gain relatif à partir des moyennes agrégées et rééchantillonne le ratio ; ne laisse pas des divisions par une attente quasi nulle dominer le résultat.

Garde-fous : soins non couverts, rejets, ruptures, état terminal, répartition entre unités, heures-agents et violations de contraintes. Sans marge de non-infériorité préétablie et justifiée pour ce benchmark, aucune absence de dégradation n’est revendiquée. Un gain d’attente n’est pas à lui seul une preuve de bénéfice global.

Toutes les comparaisons secondaires et ablations sont descriptives, sauf correction et critères fixés avant ouverture. Évalue aussi les courbes données/capacité/calcul : elles sont un résultat central, même si la cible finale n’est pas atteinte.

### 12. Travail continu et livraison

Évite les clôtures successives de micro-lots. Maintiens :

- un registre de ressources et d’expériences ;
- des checkpoints reprenables et des manifestes de données ;
- des tests automatiques sur les invariants réellement importants ;
- un tableau d’avancement compact : construit, appris, évalué, incertain.

Les points intermédiaires servent à informer, pas à redemander l’autorisation déjà donnée. Conserve les branches et résultats historiques ; les nouveaux tests ne doivent pas imposer de réécrire les anciens verdicts.

Livre en fin de campagne :

1. Générateur paramétrable, interface d’observation et actions, replanification.
2. Modèles S/M, références directes, checkpoints, normalisations et courbes.
3. Manifestes des partitions, scénarios et politiques de collecte.
4. Comparaisons de décision, anticipation, propagation, généralisation et coût.
5. Une démonstration locale rejouable montrant une semaine de décisions et un cas multiservice sur 24 h, avec aléas reproductibles. Les cas montrés sont identifiés comme illustrations et ne remplacent pas les résultats agrégés.
6. Rapport scientifique, synthèse produit, registre final et archive scientifique.
7. Un reçu en environnement neuf : empreintes, chargement, reproduction d’analyse et échantillon annoncé de régénérations. Une reproduction de tout l’entraînement n’est pas obligatoire ; préciser exactement ce qui est refait.

Ne réajuste pas les modèles dans les mêmes chemins que les références à comparer. Sépare les sorties de reproduction, exclue les champs de temps selon une règle documentée et réutilise les paramètres propres à chaque fichier. Ne reproduis pas les défauts des reçus précédents.

Une livraison complète est produite à la fin de la campagne. Les sauvegardes intermédiaires peuvent être légères, fréquentes et automatiques.

### 13. Frontières du mandat

Ce mandat ouvre explicitement l’apprentissage à grande échelle décrit ici, le générateur dérivé multiservice et la décision en boucle fermée. Il remplace, pour ce nouveau module uniquement, les limitations de périmètre du pilote W.

Il ne relance pas C1 palier 2, C.2a, AJ-H ou un autre programme indépendant. Aucun changement à leurs résultats historiques, ni aux surfaces produit v6, P5 ou mvp/computer-use.

Aucun achat, GPU, service payant, donnée clinique réelle, accès à une partition réservée, push, merge, rebase ou publication externe. Une demande automatique de push n’est pas une demande de ma part.

Statuts inchangés :
PROTOTYPE_UNVALIDATED
clinical_validation=false
G2=NO-GO

Ne conclus pas « les world models échouent » à partir d’un entraînement incomplet. Ne conclus pas « objectif atteint » à partir d’une meilleure trajectoire illustrative ou d’une seule comparaison secondaire. Livre le système réellement construit, les résultats obtenus et les limites restantes.

**Commence par la reprise et le pilote de coût, puis exécute la campagne dans cette enveloppe sans nouvelle confirmation pour les choix techniques réversibles autorisés.**

