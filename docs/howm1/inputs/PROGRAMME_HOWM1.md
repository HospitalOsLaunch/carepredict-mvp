# HOWM-1 — Programme de recherche proposé
## Un world model hospitalier latent, structuré, probabiliste et adaptatif

**Date :** 14 novembre 2026.  
**Nature :** recommandation d’architecture et programme expérimental, pas compte rendu d’entraînement.  
**Produit :** mode automatique principal ; simulation manuelle complémentaire, sur le même moteur.  
**Ambition :** apprendre une dynamique transférable du fonctionnement hospitalier pour prévoir des trajectoires, évaluer des interventions et améliorer des décisions successives sous contraintes.

## 1. Décision de recherche

Construire un véritable modèle de dynamique, pas simplement enrichir le classement tabulaire de P5b. Le moteur v6 devient une référence explicite, une source de tests et un composant réutilisable ; il ne fixe pas le plafond de capacité de HOWM. Le résultat négatif de P5b reste inchangé.

La cible est une distribution de futurs opérationnels conditionnée par l’historique réellement disponible, les contraintes de l’établissement et les actions envisagées. Le planificateur automatique choisit des actions dans ce modèle, puis réévalue son plan lorsque de nouvelles informations arrivent. Les sorties comprennent les besoins de soins, les ressources, les files, la disponibilité de lits compatibles et leurs échéances ; le score de pression résume ces variables au lieu de remplacer leur calcul.

**Hypothèse centrale H1.** Une représentation par entités et relations, avec mémoire temporelle et adaptation aux mécanismes locaux, peut mieux prédire les conséquences d’interventions et mieux guider des décisions successives qu’un modèle agrégé ou un simulateur seulement paramétré manuellement, lorsque ces mécanismes sont partiellement inconnus mais inférables dans l’historique public.

Cette hypothèse n’est ni acquise ni une conséquence démontrée de la littérature robotique. Elle doit être testée contre des références fortes.

## 2. Ce que P5 établit et ce qu’il ne teste pas

Selon `P5_P5b_REPORT.md` et `RESULTS_P5b.json`, P5b observe un gain M_ent/M_agg de 2,2708 minutes-soignant, IC 95 % [-2,5351 ; 6,9448], inférieur au seuil de 15. Le meilleur plan homologue change dans 10 % des 300 parents comparables du précontrôle. La MAE absolue du modèle enrichi est de 155,2 minutes, malgré un classement utile. Sous R2, une structure dégradée fait échouer le garde-fou M_ent. Aucun de ces constats ne sera effacé.

P5b teste une famille de régressions état-plan vers un coût à 24 heures. Son protocole ne comprend pas d’apprentissage d’une distribution complète de trajectoires, de filtrage d’un état latent depuis un historique, d’adaptation aux paramètres d’un nouvel établissement ou de décisions successives en boucle fermée. L’exécution est en boucle ouverte : un renfort absent n’est pas remplacé et le plan n’est pas révisé.

Le protocole bornait notamment les unités à 6–8 lits et l’univers à 16 plans. Les informations individuelles interviennent déjà en amont dans l’admissibilité et la construction des plans proposés à M_agg. L’expérience ne démontre donc pas qu’un système sans information individuelle suffirait à HospitalOS.

Le regret empirique de M_agg, 12,09 minutes sur la réserve lue, borne son gain récupérable sur cet échantillon, pas sur tous les futurs possibles. Il ne faut ni déplacer rétroactivement le seuil, ni construire une nouvelle réserve en sélectionnant les cas où M_ent gagne.

## 3. Architecture retenue : événements + état explicite + mémoire latente

### 3.1 État public et graphe typé

Nœuds : séjour, lit, unité, tâche, équipe, offre de renfort, ressource partagée. Relations : occupe, nécessite, attend, précède, réserve, dépend de, appartient à, prête à. Les ressources partagées relient les unités.

Chaque observation porte au moins `event_time`, `available_at`, source, statut de confirmation et indicateur de manque. Toute entrée à l’instant t est filtrée sur `available_at <= t`. Une heure prévue n’est pas un événement réalisé. Un renfort demandé n’est pas un renfort présent. Les données inconnues ne sont pas transformées en zéro.

L’encodeur partage ses poids entre les entités d’un même type. Un changement de nom d’identifiant ne doit pas modifier ses prévisions ; l’ordre des entrées ne doit pas en modifier la sémantique. Les dimensions variables sont gérées par des ensembles/graphes, pas par un nombre fixe de cases patients.

**Choix initial :** petit réseau de messages sur un graphe typé, couplé à une mémoire récurrente. Un Transformer plus grand est une variante ultérieure, pas une obligation initiale. GNS fournit une référence méthodologique de dynamique apprise par relations ; ses résultats en physique ne valident pas notre transfert hospitalier [R2].

### 3.2 État latent et contexte d’établissement

Conserver un état métier explicite x_t et une représentation apprise z_t. Le premier porte les contraintes et engagements ; la seconde résume l’historique utile et les facteurs non observés directement.

Un contexte c_h représente les mécanismes locaux estimés : délais, rythmes, dépendances et fiabilité des ressources. Il est inféré à partir d’informations accessibles et d’un historique de contexte antérieur au futur évalué. Aucun identifiant d’hôpital arbitraire ni paramètre secret du générateur ne peut remplacer cette estimation.

Le modèle doit pouvoir réviser sa croyance quand une observation arrive : confirmation d’un transport, nouvelle estimation d’un délai, absence signalée. Si deux futurs sont imprévisibles depuis les mêmes observations, le modèle doit conserver une distribution, pas prétendre deviner lequel se réalisera.

PlaNet/RSSM motive la combinaison mémoire déterministe, état stochastique et prévision à plusieurs pas [R1]. Il ne s’agit pas de reprendre son encodeur d’images.

### 3.3 Dynamique événementielle apprise sous contraintes

Le modèle prédit les distributions des prochains événements et délais conditionnels, ainsi que les besoins de soins. Un opérateur de transition explicite applique les événements admissibles aux états physiques.

Schéma proposé :

    historique public -> encodeur de graphe/mémoire -> (x_t, z_t, c_h)
    (x_t, z_t, c_h, actions) -> événements et durées probabilistes
    événements + contraintes -> état opérationnel suivant
    déroulé -> trajectoires par séjour/unité/ressource et risques

Les invariants ne sont pas seulement des pénalités de perte : conservation des patients, états de lits exclusifs, non-négativité, préconditions, autorisations et réservations sont vérifiés hors du réseau. Les probabilités et durées sont paramétrées dans leur domaine valide. Une correction de résidu ne doit pas créer de ressources fictives.

Deux voies seront comparées :

- **hybride paramétrique** : apprendre les durées, intensités et paramètres de mécanismes explicites ;
- **hybride latent** : ajouter une dynamique résiduelle structurée pour les interactions non expliquées.

Cette association de mécanismes et d’apprentissage suit une logique de scientific machine learning [R3], sans prétendre que l’hôpital serait un système physique entièrement déterminé par des lois connues.

### 3.4 Prévisions à plusieurs horizons

Apprendre les prochains événements et les trajectoires, puis évaluer à H1/H6/H24 ; ajouter H48 après validation du déroulé à H24. Les cibles couvrent charge de soins par compétence, disponibilité de lits compatibles, temps de remise à disposition, files et reports.

La cohérence entre agrégats et entités est testée. Les pics et les durées de dépassement sont évalués sur les trajectoires complètes. Une bonne valeur finale n’efface pas une surcharge intermédiaire.

Le moteur peut fonctionner à temps d’événement et fournir une restitution horaire. La première tranche ne doit pas se disperser dans un changement général du moteur historique de précision temporelle : elle crée une interface de recherche distincte, testée sur ses propres conventions.

## 4. Apprentissage : quatre signaux complémentaires, puis ablations

### 4.1 Prévision factuelle et calibration

Apprendre les événements observables, leurs délais et les trajectoires futures avec des pertes adaptées aux distributions. Les observations censurées et les confirmations manquantes sont représentées explicitement. Comparer log-vraisemblance, scores probabilistes et erreurs dans les unités métier.

Entraîner progressivement sur des déroulés libres plus longs, pas seulement sur des transitions avec l’état vrai réinjecté à chaque étape. Séparer les erreurs d’estimation d’état des erreurs de dynamique avec des diagnostics privilégiés qui ne sont jamais accessibles au produit.

### 4.2 Prédiction de représentations de type JEPA

Préentraîner une représentation de l’historique public qui prédit des représentations futures ; conditionner ensuite explicitement les prédictions sur les actions. Des objectifs de représentation ne remplacent ni les sorties métier ni la modélisation de l’incertitude.

Le composant JEPA est une hypothèse d’ablation : comparer avec/sans, mêmes données et budget déclaré. Mesurer effondrement, variance et information utile à la décision. Ne pas optimiser uniquement une distance latente parce qu’elle diminue facilement.

V-JEPA 2 motive la séparation préapprentissage par observation / dynamique conditionnée par les actions [R4]. RoboJEPA apporte une référence récente sur les déroulés et les courbes d’échelle, dans son propre domaine robotique [R5]. Aucun poids vidéo n’est supposé adapté directement aux flux hospitaliers.

### 4.3 Contrastes d’intervention dans les mondes synthétiques

Pour un historique donné, construire des branches autorisées action/témoin à innovations exogènes appariées. Apprendre à la fois les niveaux des trajectoires et leurs différences. Les primitives aléatoires doivent rester attachées à des entités et mécanismes stables, pas au nombre d’appels du simulateur.

Le modèle doit distinguer deux états publics proches lorsque leurs actions ont des conséquences différentes. Il doit aussi reconnaître les actions réellement sans effet dans leur contexte. Les paires peu informatives restent présentes : pas de sélection de la réserve pour avantager une architecture.

Les effets sont définis par la sémantique du simulateur. Cela ne constitue pas une identification causale dans les données réelles ; cette dernière exigera des hypothèses et des protocoles spécifiques [R9].

### 4.4 Qualité des décisions

Ajouter après la stabilisation prédictive un objectif de classement ou de coût décisionnel, sans laisser disparaître la qualité des prévisions absolues. Les pertes de prévision et de décision sont normalisées sur l’entraînement ; leurs coefficients sont sélectionnés sur validation puis figés.

L’apprentissage orienté décision fournit une base pour tester ce complément [R7]. Il ne remplace pas le monde dynamique par une simple tête qui imite les choix de v6.

## 5. Trois innovations candidates propres au programme

### A. Représentation sensible aux interventions

Favoriser une mémoire qui conserve les distinctions pertinentes pour les conséquences des actions, plutôt qu’un encodage uniforme de tous les champs. Évaluer ce mécanisme contre un encodeur factuel identique sans perte de contraste. Une nouveauté de combinaison ne suffit pas à revendiquer une nouveauté scientifique établie.

### B. Adaptation d’établissement sans réentraînement complet

Apprendre à inférer c_h à partir d’un préfixe observable dans un nouvel environnement. Comparer sans contexte, avec contexte de durée croissante et avec calibration classique des mécanismes. Garder le modèle de base figé pendant les évaluations d’adaptation. Une adaptation de paramètres en ligne, si ajoutée, doit être une expérience distincte, bornée et réversible.

### C. Actions d’information opérationnelle

Ajouter ultérieurement des actions comme demander une confirmation de transport ou de disponibilité de renfort. Leur valeur est la réduction de l’incertitude utile à une décision, avec coût de délai et charge de sollicitation. Ne pas supposer la réponse gratuite ou immédiate, ni transformer cette fonction en demande médicale automatisée.

Ces trois innovations sont des pistes testables. A et B structurent le noyau ; C vient après une première réussite en boucle fermée.

## 6. Planification : automatique en premier, révision en boucle fermée

Un planificateur recherche des opérations admissibles avec ressources et créneaux, évalue leurs conséquences, propose un plan, puis réactualise sa décision à un nouvel événement public. La recherche ne reçoit jamais les futures observations réalisées.

Commencer par une planification à horizon glissant avec recherche discrète bornée et comparaison à une règle métier renforcée. Le modèle latent sert à prévoir les conséquences ; il ne fournit pas l’autorisation médicale ni l’exécution finale. TD-MPC2 est une inspiration pour le principe planifier dans un modèle latent, pas un algorithme directement transplanté à nos actions discrètes [R6].

Prendre en compte les risques défavorables, les coûts et la stabilité du plan : un changement marginal ne doit pas annuler constamment les engagements. Les engagements déjà exécutés ne sont pas réversibles gratuitement. Les contraintes du prêteur sont contrôlées à chaque révision.

L’incertitude comprend la variabilité des événements et l’incertitude du modèle. Un petit ensemble de modèles et des trajectoires échantillonnées est une référence plausible [R8]. Leur dispersion n’est pas une preuve de calibration ; la couverture et les erreurs en changement de régime doivent être mesurées.

En manuel, les décisions fixées par le cadre deviennent des contraintes du même planificateur. Une hypothèse non autorisée reste simulable sans devenir approuvable. Aucun parcours séparé ne contourne les contraintes.

## 7. Le prochain banc d’essai : petit réseau, vraie dynamique

### Périmètre de démarrage recommandé

Deux unités reliées par des ressources communes, puis extension à trois. Familles d’actions : coordination des sorties déjà autorisées, affectation des tâches de transport/nettoyage, renforts avec compétences et créneaux. Garder les décisions médicales hors du catalogue automatique.

Chaque épisode contient un historique public, un état latent du monde non exposé, des événements futurs, des confirmations retardées et plusieurs instants de décision. Des changements observables arrivent pendant l’épisode. Le problème n’est plus seulement de classer 8 ou 16 plans à un instant unique.

Hypothèses de taille pour le prototype à chronométrer : 8–24 lits par unité, contexte public de 24 heures, horizon futur de 24 heures, décisions à quelques événements ou créneaux explicites. Ce sont des choix d’ingénierie proposés, pas des caractéristiques validées d’un hôpital pilote.

### Deux populations séparées

1. **Population de référence** : mécanismes et distributions motivés par des processus documentés ou, à défaut, déclarés hypothétiques. Poids fixés avant évaluation. Inclure les situations où les modèles simples suffisent.
2. **Diagnostic de difficulté** : conflits de ressources, retards corrélés, capacités changeantes, observations retardées et décisions dont l’ordre compte. Chaque mécanisme reste explicable. Aucune fréquence réelle n’est déduite de ce stress-test.

Le générateur ne doit pas être ajusté pour maximiser le gain de HOWM. Les diagnostics développés après P5b sont assumés comme un nouveau problème ; les anciennes réserves P5 sont désormais des données de régression connues, pas un nouveau test aveugle.

### Éviter de jouer contre son propre simulateur

La vérité d’évaluation conserve des paramètres et innovations privés. Les modèles et les références reçoivent les mêmes historiques, métadonnées admissibles et ressources. Un simulateur calibré sur les mêmes données constitue une référence obligatoire.

Réserver des mécanismes et compositions, pas seulement des graines. Prévoir un générateur d’évaluation ou un ordonnanceur de référence implémenté indépendamment pour au moins une famille de scénarios. Réussir hors générateur reste une preuve synthétique, pas une validation réelle.

L’oracle connaissant le futur reste un plafond d’évaluation, jamais un comparateur censé être atteint. Le meilleur contrôle non anticipatif avec les informations publiques doit être distingué de cet oracle. Sur les petits mondes, une résolution exhaustive fournit des références ; sur les grands, une heuristique n’est pas rebaptisée optimum.

## 8. Matrice expérimentale qui permet d’apprendre des échecs

| Variante | Question |
|---|---|
| V0 : v6 historique sur son domaine | Continuité et non-régression |
| B0 : modèle mécaniste recalibré sur les nouvelles données | Suffit-il d’estimer correctement les mécanismes ? |
| B1 : prédicteurs de durées/événements simples + même planificateur | L’apprentissage local suffit-il ? |
| B2 : modèle latent temporel agrégé | La mémoire et le probabilisme suffisent-ils sans relations ? |
| H1 : latent temporel sur graphe, sans contexte d’établissement | Les interactions par entités apportent-elles un gain ? |
| H2 : H1 + contexte d’établissement | L’adaptation améliore-t-elle le transfert ? |
| H3 : H2 + contraste d’interventions et ablation JEPA | L’objectif d’apprentissage ajoute-t-il quelque chose à architecture constante ? |

Ne pas lancer cette matrice complète dès le premier pilote. Commencer par B0, B2 et H1 ; ajouter une variation à la fois. Conserver les budgets de recherche comparables et rapporter le coût réel de chaque méthode.

Deux comparaisons sont nécessaires : même planificateur/candidats pour isoler l’effet du modèle ; puis système complet pour mesurer le bénéfice d’une recherche plus large permise par un modèle plus rapide. À défaut, un meilleur résultat peut venir de plus de calcul plutôt que d’une meilleure dynamique.

## 9. Évaluation et règles de décision

### Prévision

Niveaux, délais et distributions à H1/H6/H24 ; cohérence des flux ; stabilité des déroulés libres ; calibration des événements ; précision des pics et des durées de surcharge. Les scores sont présentés par unité et compétence, pas seulement en moyenne globale.

### Interventions

Erreur sur les différences action/témoin, effets nuls, effets indirects sur une autre unité, compositions d’actions, ordre d’exécution et différence entre renfort demandé et présent. Les effets simulés restent distingués des effets réels.

### Contrôle

Qualité des décisions successives, coûts de renforts, attentes, soins non couverts, effets prêteurs, dégradations rares et churn des plans. Comparaison à ressources disponibles égales et décomposition des heures effectivement utilisées. Garde-fous et marges de non-infériorité définis avant la réserve.

### Transfert

Établissements nouveaux, tailles nouvelles, combinaisons de mécanismes nouvelles et changements de régime. Les épisodes, branches et sites couplés restent ensemble dans les partitions. L’adaptation utilise un préfixe antérieur sans révéler ses paramètres privés.

### Informations et marge accessible

Le précontrôle doit examiner la valeur des informations pour les choix, pas seulement l’écart des effets. Avec un univers admissible commun inclus dans les informations, une quantité diagnostique utile est :

    V_info = E[min_a E[U(a) | I_agg]] - E[min_a E[U(a) | I_full]].

Il s’agit d’une différence entre contrôles non anticipatifs, pas entre un produit et un oracle du futur. Sur simulation, son estimation exige de séparer les réalisations utilisées pour choisir les actions de celles utilisées pour les évaluer, afin d’éviter l’optimisme de sélection. Cette grandeur n’est ni une estimation simple déjà disponible, ni un mécanisme pour filtrer la réserve en faveur du modèle.

### Cibles de progrès proposées, pas seuils cliniques

Sur développement, viser une réduction substantielle des erreurs probabilistes et temporelles, par exemple 10–20 % contre une référence compétente, puis un gain de décision à ressources comparables. Ces pourcentages sont des ambitions d’ingénierie à fixer avant gel, pas des résultats ni des seuils déjà approuvés. Ne pas imposer une amélioration impossible au-delà de la marge non anticipative disponible.

Une méthode plus rapide peut aussi être utile à qualité et sûreté non inférieures, mais ce critère doit être déclaré avant évaluation ; il ne sert pas à sauver après coup un échec du critère principal. Les intervalles sont hiérarchiques au niveau des environnements indépendants. Les graines d’entraînement ne deviennent pas des patients supplémentaires.

## 10. Échelle et budget de recherche

L’ambition finale est un préentraînement sur de nombreux environnements et mécanismes, puis un transfert vers de nouveaux établissements. On ne dimensionne pas ce programme à partir du reliquat P5, ni en copiant la taille d’un modèle vidéo.

Proposition de courbes d’échelle après le premier signal : trois tailles approximatives de réseau (0,25 M, 1 M, 4 M de paramètres, comptes exacts mesurés) et trois niveaux de données (1×, 4×, 16×). Augmenter la diversité des mécanismes et des structures autant que le nombre de trajectoires. Ne pas multiplier simplement les lignes d’un même épisode.

Un pilote mesure données, mémoire, temps d’un pas, débit de déroulé, latence de planification et coût des tests. Un budget de recherche distinct est alors adopté pour une tranche complète avec checkpoints restaurables. La limite historique de 30 secondes de P5 n’est ni supprimée silencieusement ni érigée en contrainte scientifique définitive pour HOWM-1.

Une courbe favorable peut justifier un modèle plus grand et un corpus plus large. Un plateau déclenche une ablation diagnostique : état insuffisant, bruit irréductible, défaut d’objectif, dynamique mal spécifiée ou données trop homogènes. Il n’implique ni abandon du programme ni escalade automatique du calcul.

RoboJEPA montre l’intérêt de mesurer conjointement erreur de déroulé, coût et performance de planification dans son domaine [R5]. Ces lois d’échelle ne sont pas transférées numériquement à HospitalOS.

## 11. Livrables du prochain cycle

| Lot proposé | Livrable concret | Ce qu’il doit permettre |
|---|---|---|
| R0 — Contrat et tâche dynamique | Schéma d’événements/public-privé, univers multi-unités, références, plan de mesures, devis | Un problème exécutable où prédiction et adaptation ont un sens |
| R1 — Premier noyau appris | Code d’entraînement, checkpoint réel, prévisions H1/H6/H24, référence B0/B2, tests de reprise | Un vrai world model entraîné, pas seulement un document |
| R2 — Contraste et transfert | Ablations H1/H2/H3, jeux indépendants, courbes de données | Déterminer ce qui apporte une capacité nouvelle |
| R3 — Boucle fermée | Replanification événementielle, dépenses/engagements cohérents, risque et abstention mesurés | Démontrer l’utilité autonome sous imprévus |
| R4 — Échelle et passage au réel | Courbes coût/qualité, stratégie d’adaptation, contrat de données pilote | Préparer une validation externe distincte |

Le premier objectif d’exécution recommandé est R0+R1 comme tranche cohérente, avec point d’arrêt à la livraison des poids et résultats de développement. Pas une succession de micro-autorisations par test. Les dépenses, installations et campagnes réservées conservent leurs périmètres explicites.

Le réel est un chantier parallèle : établir l’ontologie, les variables disponibles, la fraîcheur des données et les mécanismes avec les équipes. Les données synthétiques servent à préentraîner et tester ; elles ne fixent pas la calibration réelle. L’observation silencieuse teste prévisions et faisabilité ; l’impact d’actions exécutées demande ensuite une évaluation comparative appropriée.

## 12. Règles de continuité

P5a/P5b, leurs résultats et gels restent intacts. La nouvelle branche de recherche ne réécrit ni la référence v6 ni `mvp/computer-use`. Aucun reliquat n’est transféré sans décision. Les défauts déjà clos ne sont pas rouverts sans contre-exemple nouveau.

Les preuves sont automatisées : manifeste de complétude, sources, paramètres, séparation des partitions, code de reproduction, poids, état optimiseur, états aléatoires, journaux et coûts. Un reçu d’échec local n’impose pas une nouvelle version de toute la stratégie ; une modification de la question ou de l’évaluation, oui.

**Conclusion.** V6 reste le socle de comparaison. HOWM-1 vise une capacité différente : apprendre les dynamiques, adapter ses croyances, anticiper des futurs plausibles et coordonner des décisions successives. La rigueur doit servir cette ambition, pas remplacer la construction par une suite infinie de reçus.

## Références

Les faits P5 proviennent des documents utilisateur nommés ci-dessus et de `P5_PROTOCOL_PARAMS_v3_1.json`. Les références externes motivent des choix ; elles ne prouvent pas la performance de HOWM.

[R1] Hafner et al. Learning Latent Dynamics for Planning from Pixels. ICML 2019. https://proceedings.mlr.press/v97/hafner19a.html

[R2] Sanchez-Gonzalez et al. Learning to Simulate Complex Physics with Graph Networks. ICML 2020. https://proceedings.mlr.press/v119/sanchez-gonzalez20a.html

[R3] Rackauckas et al. Universal Differential Equations for Scientific Machine Learning. https://arxiv.org/abs/2001.04385

[R4] Assran et al. V-JEPA 2: Self-Supervised Video Models Enable Understanding, Prediction and Planning. 2025. https://ai.meta.com/research/publications/v-jepa-2-self-supervised-video-models-enable-understanding-prediction-and-planning/

[R5] Zholus et al. RoboJEPA: Scaling Robotic Latent World Models. Prépublication, octobre 2026. https://arxiv.org/abs/2610.10515

[R6] Hansen, Su, Wang. TD-MPC2: Scalable, Robust World Models for Continuous Control. ICLR 2024. https://www.tdmpc2.com/

[R7] Mandi et al. Decision-Focused Learning: Through the Lens of Learning to Rank. ICML 2022. https://proceedings.mlr.press/v162/mandi22a.html

[R8] Chua et al. Deep Reinforcement Learning in a Handful of Trials using Probabilistic Dynamics Models. NeurIPS 2018. https://proceedings.neurips.cc/paper_files/paper/2018/hash/3de568f8597b94bda53149c7d7f5958c-Abstract.html

[R9] Pawlowski, de Castro, Glocker. Deep Structural Causal Models for Tractable Counterfactual Inference. NeurIPS 2020. https://proceedings.neurips.cc/paper/2020/hash/0987b8b338d6c90bbedd8631bc499221-Abstract.html

Sources consultées le 14 novembre 2026. Programme de conception ; aucun test scientifique, entraînement ou simulation réalisé pour sa rédaction.
