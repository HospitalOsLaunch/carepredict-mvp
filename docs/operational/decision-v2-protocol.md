# Décisions v2 : protocole verrouillé avant lecture du test

Statut : recherche synthétique uniquement. Le résultat v1 est **non concluant**.
Le nouveau protocole ne transforme pas les tests logiciels en preuve d'efficacité.

<!-- decision-v2-primary: inconclusive -->

Le test v2 verrouillé ne démontre pas de supériorité du mélange supervisé sur la
régression logistique pour le critère principal. L'intervalle apparié contient zéro.
La borne basse de validation ne confirme pas non plus l'objectif ARL₀, et les
actions restent sensibles au nombre de scénarios. Les réglages n'ont pas été
modifiés après ces observations. La CI recalcule et vérifie ce verdict ; les
chiffres et tableaux sont produits par la commande ci-dessous, sans copie manuelle.
Sur développement stable, le poids choisi est à la borne boosting seul ; le terme
« mélange » désigne donc ici la famille testée, pas une combinaison intérieure retenue.
Dans le choc annoncé, les politiques convergent vers l'absence de demande
supplémentaire : leur égalité ne démontre donc pas un meilleur arbitrage. Des
expositions liées au transport déjà demandé peuvent subsister. Dans le choc
non annoncé, les régressions de surcharge persistent. Les chocs de ressources
ne changent pas les labels de préparation dans ce protocole ; toute alarme de
préparation dans ces flux est donc comptée comme fausse, même après la rupture.

## Choix fixés

- Trois patients préparables, un transport déjà demandé et un choix entre deux
  demandes supplémentaires ; une équipe partagée. Durées de transport, retour et
  nettoyage observées, hétérogènes. Chaque départ libère au plus un lit.
- Vérité continue : risques constants par morceaux, grille de 30 minutes jusqu'à
  8 h puis queue jusqu'à 24 h. Censure indépendante aux bornes de cette grille.
- Dépendance commune par copule gaussienne, chargement 0,6 (corrélation latente
  paire à paire 0,36), conservant les marginales. Sensibilité 0 / 0,6 / 0,85
  sur développement. Les temps continus ne sont pas arrondis dans le benchmark.
- Covariables d'entraînement continues ; calendrier Europe/Paris dérivé d'origines
  UTC. Un calendrier civil ne remplace jamais les horodatages UTC.
- Références : hazard poolé, règle analytique de gain marginal isolé, règle du
  patient autorisé depuis le plus longtemps, régression logistique patient–intervalle.
  La règle analytique ignore la concurrence : elle est un témoin, pas un optimum.
- Boosting et logistique ont le même jeu d'apprentissage et la même grille.
  Mélange exact de distributions poolée/boosting ; poids choisi sur développement
  stable, parmi 0 / 0,25 / 0,5 / 0,75 / 1. Un poids nul est un résultat acceptable.
- Prévisions et labels figés à D ; retours à D+24 h ; aucune vérité future dans la
  sélection des actions. Le suivi de préparation est supposé indépendant de l'action.
- CUSUM unilatéral sur log-pertes appariées centrées sur développement stable,
  marge de dérive 0,05 nat par patient. Surveillance complémentaire de la référence.
  Un incrément est la moyenne des trois patients d'un épisode, pour conserver leur
  dépendance. Objectif ARL₀ : **200 épisodes informatifs**, soit 400 heures à cadence
  de 2 h, après disponibilité du premier retour. Ce choix est expérimental.
- Calibration sur 128 flux stables de 1 000 épisodes ; validation distincte sur
  128 autres. Rapporter E[min(T,1000)], taux de censure et probabilité de fausse alerte
  à 48 épisodes, sans appeler cette moyenne restreinte l'ARL exact. Seuils calibrés
  conjointement pour les deux alarmes, puis figés. Aucun ajustement sur validation.
- Test : 30 graines nouvelles (20000 à 20029), 48 épisodes chacune, quatre flux :
  stable, réorganisation, choc de ressources annoncé et non annoncé. Rupture à
  l'index 16. Les premières sorties modifiées ne sont disponibles qu'à index 28.
- Prévisions évaluées sur 128 scénarios communs ; contrôle de convergence sur
  développement uniquement. L'optimisation reste une décision immédiate.
- Critère principal : écart moyen d'attente cumulée du mélange supervisé à la
  **logistique**, après réorganisation. IC à 95 % par bootstrap apparié de 30
  trajectoires entières, 5 000 rééchantillonnages, graine 81001. Les autres
  comparaisons sont exploratoires ; aucune sélection du meilleur flux a posteriori.
- Précision recherchée : demi-largeur d'IC <= 10 patients-minutes par épisode.
  Trente graines constituent un minimum, pas une garantie de puissance. Si la
  précision manque, verdict non concluant ; ne pas ajouter des graines jusqu'au succès.
- Publier meilleur/égal/pire, regret, fraction de l'écart à l'oracle clairvoyant
  (ratio des gains agrégés, indéfini si dénominateur nul), surcharges, repli,
  abstention et décomposition avant/après alarme avec attribution des fausses alertes.
  Ces décompositions sont descriptives et ne sont pas des effets causaux.

## Séparation et portée

Apprentissage : du 1er mars à juin (1 200 épisodes, 3 600 patients), modèle
disponible le 1er août ; sélection du mélange du 2 au 12 août, poids disponible
le 15 août ; centrage du 15 au 22 août ; calibration des alarmes et validation :
flux parallèles distincts du 26 août à novembre, réglages disponibles le 1er décembre
2026 ; test fictif à partir du 1er janvier 2027. Ces dates sont celles d'une simulation,
pas des données hospitalières déjà observées. Chaque étape respecte son embargo.
Les graines 1109/1223/1301 sont retirées du test. Les familles de perturbations sont
connues par construction ; seule leur nouvelle réalisation est réservée.

L'inférence est conditionnelle à un seul ajustement des modèles et à ce générateur.
La variabilité entre entraînements, les risques concurrents, landmarks répétés,
adhésion aux recommandations et calibration réelle restent hors validation.
Le benchmark v2 est un banc de files dédié, vérifié par un second moteur intégrant
les événements ; il n'est pas un replay hospitalier continu ni une qualification du gateway.
L'API conserve son comportement par défaut. Aucun résultat généré n'est versionné.

Les covariables continues du banc v2 sont des indices synthétiques de charge et
de demande observables à D, pas une reconstruction de comptes entiers de lits,
ni une mesure SIIPS. La transposition aux observations réelles reste à qualifier.
Le balayage exploratoire du coefficient (-2 à +2 par pas de 0,5) utilise une
cohorte réservée de 3 000 patients, graine 71001, distincte des tests décisionnels.
Il rapporte discrimination AUC à 240 minutes sur vérité complète, Brier oracle
et écart d'un IPCW marginal volontairement invalide sous censure informative.
Ce diagnostic de biais n'est jamais une mesure d'efficacité valide.

Le contrat optionnel PREPARATION_FORECAST_2 permet la même interpolation dans le
moteur API, sur une grille explicite, et un chargement partagé entre patients.
Le moteur arrondit alors à la minute supérieure (erreur <1 minute), contrairement
au banc continu. Le mélange continu exact reste dans le banc : le superviseur
v1 refuse ces courbes plutôt que de mélanger leurs hazards par approximation.
Les plans utilisant v2 portent HYBRID_PLAN_5 ; régénérer les anciennes propositions.

## Reproduction

`PYTHONPATH=src python -m hospitalos.hybrid.robustness_v2 --check`

La commande calcule le rapport, génère ses tableaux depuis les mêmes agrégats et
vérifie leurs identités numériques. La CI ne se contente pas d'exécuter un script.
Une sortie positive sur synthétique ne change jamais le statut de déploiement.
