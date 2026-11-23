# HOWM-1 — Revue du complément R0+R1 v1.1

14 novembre 2026. **Revue documentaire, statique et arithmétique. Aucune autorisation d’exécution donnée.**

## Verdict

Avis favorable à la direction R0+R1, installation **A puis B** sous conditions, persistance **P2 sans push**. La complétude est rétablie. Deux points scientifiques doivent être corrigés avant entraînement/génération correspondante, le contrat de score doit être désambiguïsé, et les contrôles de volume/persistance doivent être intégrés au mandat. Ces demandes ne changent ni les modèles B0/B2/H1, ni la population, ni la finalité du programme.

Un accord éventuellement adopté doit inclure explicitement ces conditions. La simple phrase « selon les empreintes v1.1 » n’autoriserait pas à modifier silencieusement les documents. Les amendements techniques, leurs nouvelles empreintes et leur préséance doivent être consignés avant G0. Les activités de cette revue ne consomment ni ne modifient un registre scientifique utilisateur.

## 1. Intégrité et complétude

Archive : `HOWM1_R0R1_complement_v1_1.zip`.
SHA-256 : `44951a90dea55c364f0aa58cdbf2fd53baaada195252e167180dac43a8ecef87`.

- Vérification CRC : conforme.
- 14/14 fichiers listés dans SHA256SUMS conformes. Le ZIP comprend ces 14 fichiers plus le fichier SHA256SUMS.
- 13/13 pièces de la liste de complétude : tailles et empreintes conformes.
- 7/7 originaux v1 : conformes aux empreintes annoncées, dont les cinq pièces manquantes.
- Les deux documents d’entrée correspondent aux originaux montés de cette conversation.
- Les neuf références de la proposition finale concordent avec les fichiers contenus.
- Le contenu des cinq documents auparavant absents a maintenant été lu, et non inféré depuis les résumés.

Le paquet est une préparation, pas une livraison de modèle entraîné. L’intégrité des documents ne valide pas le code à écrire. Les états locaux Git 35b563d / 4f58150 et tous les objets historiques listés dans INPUT_PROVENANCE ne sont pas vérifiés ici.

## 2. Points positifs acquis dans la spécification

L’amendement A1 remplace le pourcentage de NLL par une différence appariée de score logarithmique sur supports discrets. Le CRPS normalisé porte une ambition ponctuelle distincte, sans transformer automatiquement 10 % ponctuels en 10 % démontrés. L’objectif U, les poids multi-horizons, la patience et la sélection du taux d’apprentissage sont définis. La partition est l’établissement couplé : les deux unités, les jours et les fenêtres restent groupés. Les deux modèles appris utilisent le même historique public, les mêmes candidats et le même opérateur que leurs références. Les paramètres locaux de B0 sont inférés depuis la même fenêtre publique. La réserve reste fermée ; les résultats de R1 sont des résultats de développement.

Ces choix sont adéquats pour une première tranche. Le latent stochastique, JEPA et la boucle fermée peuvent rester différés. Aucun résultat de P5 n’est réécrit.

## 3. HOWM-C11-01 — Normalisation signée des pertes

**Sources :** DESIGN §4.1, lignes 279–287 ; JSON v1.1 `training.losses` et `training.loss_normalisation` ; amendement A1, lignes 17–19.

Le score d’évaluation est devenu discret, mais l’entraînement conserve une NLL de densité log-normale. La règle « chaque terme divisé par sa valeur initiale sur TRAIN » reste écrite. Une telle NLL peut être négative ou proche de zéro.

Exemple analytique, sans modèle exécuté : pour Y log-normal, mu=0, y=1, NLL=log(sigma*sqrt(2*pi)). Sigma=0,1 donne -1,38364656 ; sigma=0,2 donne -0,69049938. Le deuxième ajustement de loi est moins bon au point y=1. Pourtant, diviser par la valeur initiale négative donne respectivement 1 et 0,49904318 : minimiser le terme normalisé favorise ici la mauvaise direction.

**À imposer :** règle de normalisation par famille strictement positive, finie et commune lorsqu’une même perte de validation est comparée. Règle fixée avant G0, valeurs établies sur TRAIN sans DEVTEST/DIAG-DEV, puis gelées avant les entraînements principaux. Pas de division par une NLL signée. Ajouter des cas négatifs, nuls et quasi nuls et vérifier le sens d’amélioration du score. Le choix exact de l’échelle peut relever de l’implémentation déléguée, mais doit être explicite et identique entre modèles/graines comparés.

**Qualification :** défaut de spécification potentiellement bloquant, pas erreur observée d’un entraînement qui n’a pas eu lieu.

## 4. HOWM-C11-02 — Oracle et marge d’information

**Sources :** DESIGN §5.3–5.4 (lignes 351–394) ; TEST_MATRIX T-PLAN-03 (ligne 98) ; amendement A1.3.

T-PLAN-03 exige des réalisations de choix et d’évaluation disjointes pour « C_*, oracle ». C’est correct pour les contrôleurs non anticipatifs. Ce n’est pas le contrat d’un oracle clairvoyant qui borne la métrique réalisée : il doit minimiser U sur tous les candidats publics pour chaque réalisation évaluée elle-même. S’il choisit sur un autre futur, sa valeur n’est plus un plafond clairvoyant.

**Correction :** exclure l’oracle de cette assertion de disjonction ; conserver la disjonction pour B0, B2, H1, C_param, C_full. Calculer `U_star(w)=min_a U(a,w)` sur les mêmes réalisations d’évaluation, sans tolérance lexicographique pour le minimum de U. Si un oracle métier utilise la tolérance 15 et les coûts de renfort, l’étiqueter séparément. L’oracle n’entre ni dans les modèles publics ni dans leurs choix.

Le diagnostic V_param+V_latent compare C_pub-snap à C_full. C_full connaît des paramètres et un état cachés et reste un contrôleur calculé avec un budget fini : il n’est pas établi qu’il soit optimal. Une différence favorable ne prouve pas que l’historique public permet de récupérer ces informations, ni que B0-local laisse toute cette marge. Même un paramètre secret sans aucun indice dans l’historique peut améliorer C_full.

**Correction de portée :** nommer la quantité « marge observée sous information privilégiée », non « marge publiquement accessible certifiée ». Conserver delta_dec=15 comme convention du précontrôle, sans le transformer en preuve qu’un gain de 5 est atteignable. L’écart de regrets B0-local−H1 se simplifie en différence de U sur les mêmes cas ; le résultat reste calculable sans traiter C_full comme optimum certifié. Une marge faible ne bloque pas l’étude prédictive.

## 5. HOWM-C11-03 — Cohorte et masque du score de soins

**Sources :** amendement A1.1, lignes 36–44, et JSON `scores.primary_log_score.item_set`.

Le texte dit que tous les éléments évalués sont fixés par l’état public à t, mais le score de soins sélectionne aussi les séjours « observés présents » à une heure future j. Il faut distinguer : cohorte d’origine publique, réalisations futures utilisées comme labels et masque de notation.

La présence future est permise du côté du score, pas dans les entrées. Elle doit être identique pour tous les modèles, indépendante de leurs propres départs prédits, et le score doit être présenté comme conditionnel aux séjours effectivement présents. Il ne peut remplacer à lui seul l’évaluation inconditionnelle de la charge totale, qui reste fournie par le CRPS des trajectoires.

Avant G0, définir ce masque et sa sémantique, les bornes exactes des intervalles de 5 minutes (y compris la queue), le traitement des soins nuls pour la densité log-normale et les cas `s_c=0` ou score CRPS de référence nul. Ne pas corriger les zéros par un epsilon silencieux ni exclure les cas en fonction du modèle. Les tests doivent vérifier que changer une présence future ne change aucune prédiction, seulement le label/masque autorisé côté score.

Cette ambiguïté n’est pas une fuite démontrée.

## 6. HOWM-C11-04 — Le pilote doit chiffrer toute l’évaluation

Les plafonds des douze lots totalisent bien 21 600 s. Ce total n’est ni une durée garantie ni une mesure de faisabilité.

Le score prévoit toutes les heures des jours 2 à 6 : 120 origines par établissement. Sur 24 REF + 12 DIAG, à M=16, pour B0-pool, B0-local, B2 et H1, cela représente **276 480 trajectoires prédictives de 24 h** avant mutualisation/vectorisation, sans compter les diagnostics décisionnels, les sondes, G_alt et la restauration. H1/H6/H24 peuvent être lus dans une même trajectoire ; le calcul ne les multiplie pas par trois. Le M est supposé ici total par système, pas par graine ; cette convention doit être explicite.

Le plan ne mesure pas encore le débit de ces prévisions. L’ordre de grandeur 0,03–0,1 s concerne un déroulé vrai, pas nécessairement le débit des modèles : il ne faut pas le présenter comme un benchmark des modèles. S’il leur était appliqué à titre illustratif, la prévision seule représenterait 8 294–27 648 s, au-delà de R1.EVAL=3 600 s. Une vectorisation peut changer ce coût ; c’est le pilote qui doit le mesurer.

Imposer un tableau de volumes par système, population, origine, candidat, réalisation, graine et test. Contrôler le plafond R1.EVAL autant que l’entraînement. Les réductions prévues pour les diagnostics décisionnels ne doivent pas supprimer silencieusement des origines du critère prédictif. Toute modification supplémentaire des tailles ou métriques exige une décision distincte. Pas d’usage de l’évaluation pour décider un repli favorable.

## 7. Installation : A puis B, sans argument d’exclusivité

PyPI et l’annonce officielle confirment torch 2.15.0, publié le 28 octobre 2026, avec roue CPython 3.11 Linux x86_64. Le troisième avis GHSA cité, publié le 10 novembre, est confirmé et désigne 2.15.0 comme version corrigée [S1–S5].

En revanche, « seule version hors des trois avis » est trop fort : les plages indiquées n’excluent pas à elles seules les versions 2.10–2.13. Cela ne prouve pas qu’elles soient exemptes d’autres vulnérabilités. Conserver 2.15.0 comme choix explicite, pas comme déduction d’unicité.

Le blocage du proxy est un constat de l’environnement de l’auteur, non reproduit ici. A puis B est raisonnable après adoption explicite, mais ne vaut pas contournement d’un refus de politique. B ne démarre que si A est indisponible/refusée et que sa propre route est autorisée. Version, provenance, dépendances, mémoire/disque, import et temps d’installation restent vérifiés dans les plafonds. Aucune installation n’a été faite pendant cette revue.

`weights_only=True` réduit la surface d’attaque sans garantir toute la sécurité [S6]. Les checkpoints du projet doivent stocker des tenseurs/structures autorisées, dont les états RNG convertis si nécessaire, pour permettre la reprise sans passer à `weights_only=False` en cas d’erreur. Tester ce contrat dès le pilote.

## 8. Persistance : P2, avec paquets intermédiaires restaurables

Le connecteur GitHub confirme `visibility=public` pour HospitalOsLaunch/carepredict-mvp. Aucun changement distant n’a été effectué. Un push publierait les objets effectivement transmis, pas automatiquement tous les fichiers du conteneur ; la proposition prévoit néanmoins des checkpoints versionnés. P2 permet d’éviter cette publication.

Deux précisions :

1. G0, F1 et fin de R1 ne suffisent pas à protéger les entraînements intermédiaires si le conteneur disparaît avant F1. Livrer aussi un paquet après chaque exécution complète (modèle, taux, graine), et avant toute interruption volontaire ou fin de session. Les sauvegardes locales toutes les 400 s ne remplacent pas ces fichiers récupérables.
2. `git bundle 68320a8..HEAD` est incrémental et requiert sa base [S7]. Fournir un bundle autonome ou un arbre source complet avec empreinte ; autrement, joindre les prérequis exacts au paquet. Tester la restauration depuis le paquet, pas depuis la copie de travail, sans accès implicite à une base manquante.

Tous les temps de conditionnement/restauration sont imputés. Aucun push, publication, nouvelle connexion ou stockage tiers n’est autorisé par cette recommandation.

## 9. Décision proposée

Conserver les choix scientifiques centraux, adopter A puis B et P2 avec l’addendum ciblé ci-dessus, puis laisser l’agent exécuter R0+R1 jusqu’au point d’arrêt sous les contrôles prévus. Les conditions doivent être transcrites avec leurs empreintes et leurs tests avant G0/entraînement, sans nouvelle micro-autorisation par fichier. Un échec de test ou de budget conduit à un arrêt traçable, pas à un affaiblissement silencieux.

Ce document n’adopte pas cet accord à la place de l’utilisateur. Il fournit une proposition distincte. Aucun modèle n’a été entraîné ou chargé, aucun corpus généré, aucun test produit exécuté et aucun registre modifié pour cette revue.
