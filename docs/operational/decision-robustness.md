# Robustesse des décisions v1 : résultat non concluant

Statut : expérience synthétique séquentielle, 24 octobre 2026. La politique
supervisée reste expérimentale. Ce lot ajoute des fonctions de comparaison et
un superviseur en mémoire ; il ne modifie ni l'API par défaut ni le gateway.

## Problème et résultat principal

Une régression de prévision ne mesure pas directement une dégradation de décision.
Le benchmark compare maintenant les actions recommandées et leurs conséquences
dans des épisodes à deux unités, avec départs préparables et ressources limitées.

**Verdict scientifique : non concluant, pas de promotion.** Sur trois graines et
96 épisodes post-réorganisation, les écarts descriptifs ne démontrent aucune
supériorité statistiquement établie. La référence poolée ne distingue pas les
deux transports en espérance dans ce fixture ; le bruit Monte Carlo les départage.
Un repli qui copie cette référence réduit mécaniquement le taux « pire que la
référence ». Ce taux seul ne démontre pas une protection décisionnelle.

Le [protocole v2](decision-v2-protocol.md) remplace cet essai pour toute nouvelle
conclusion scientifique : logistique, référence analytique, vérité continue,
départs concurrents, CUSUM et inférence appariée sur 30 trajectoires réservées.
Les fonctions v1 sont conservées pour reproduction et tests de régression.

## Politiques comparées

| Politique | Prévision et décision |
|---|---|
| Référence | Risque de préparation lissé, sans covariables, puis planificateur existant |
| Boosting | Risque conditionnel au contexte, puis même planificateur |
| Mélange fixe | Distribution combinée, sans supervision ; ablation pour isoler l'effet du mélange |
| Mélange supervisé | Combinaison, contrôle du désaccord entre modèles, repli ou abstention |

L'inaction est évaluée comme témoin de l'utilité. Un oracle connaissant les temps
réels et les chocs synthétiques sert uniquement à calculer un regret rétrospectif.
Il ne constitue pas une politique déployable et ne participe pas à la sélection.

`decision_guard.mix_forecasts` combine les **masses de probabilité et leur queue** :
`F = alpha × F_boosting + (1-alpha) × F_reference`. Il ne moyenne ni les risques
conditionnels ni les log-pertes. Les identités patient, l'état, l'origine et les
dates de disponibilité doivent correspondre ; le poids fait partie de l'identité
de la prévision. La masse après 24 h reste explicite.

## Données de réglage et test

Les experts de cette expérience sont réentraînés séparément sur le générateur
synthétique antérieur, avec la graine 20261025 et les deux unités explicitement
représentées. Le périmètre du modèle précédent à une unité n'est pas élargi
silencieusement. Les fenêtres train/recalibrage/sélection restent celles du premier
protocole ; le jeu de test de ce générateur n'est pas utilisé pour ce réglage.

La fonction `fit_benchmark` ne reçoit aucun épisode de test décisionnel :

- 40 épisodes, soit 80 patients, du 8 octobre au 11 octobre à 06 h UTC choisissent `alpha` parmi
  `0, 0.25, 0.5, 0.75, 1` selon la vraisemblance censurée. Les égalités favorisent
  la référence. Les mécanismes de développement varient la force de l'effet de
  charge et le niveau général des délais.
- Leurs labels sont disponibles au plus tard le 12 octobre à 06 h UTC. Le poids
  est verrouillé à 08 h UTC ; un embargo de suivi sépare les deux périodes.
- Les 20 épisodes suivants, soit 40 patients distincts, du 12 octobre à 08 h UTC
  au 13 octobre à 22 h UTC, règlent les seuils de surveillance. Leurs labels sont
  disponibles au plus tard le 14 octobre à 22 h UTC, avant le verrouillage du
  15 octobre. Le test ne commence qu'après ces deux verrous.
- Les tests commencent le 18 octobre : trois flux × trois graines réservées
  `1109, 1223, 1301` × 48 décisions espacées de deux heures = **432 épisodes**.
- Chaque politique utilise 32 scénarios de planification, sur un horizon de six
  heures. Les scénarios sont appariés entre modèles et actions.

Les familles de perturbations sont motivées par les stress précédents. Ce sont
de nouveaux épisodes, graines et interactions temporelles, pas une découverte
aveugle de familles de dérive entièrement inconnues. Aucun réglage n'a été effectué
sur leurs résultats. Modifier la politique après lecture nécessite une nouvelle
séparation développement/test.

Le réglage de développement retient **75 % de boosting et 25 % de référence**.

## Épisodes et conséquences réelles dans la simulation

Chaque unité contient un patient sortant éligible, éventuellement un résident
non éligible, et un ou deux patients en attente. Un second lit peut être fermé.
Une équipe de transport et une place d'aval sont partagées. Le catalogue autorise
l'inaction ou la demande immédiate du transport d'un des deux sortants.

Le transport dure 45 minutes, le retour d'équipe et le nettoyage 30 minutes.
Ces durées sont des hypothèses fixes du fixture. La préparation est tirée par
un mécanisme distinct des prédictions, avec la même réalisation pour toutes
les politiques. Aucune autorisation médicale n'est prédite.

Les trois flux sont :

1. **Stable** : processus inchangé, nouvelles réalisations.
2. **Réorganisation** : après la 16e décision écoulée (`index=16`), modification
   du signe de l'effet de charge et de son interaction avec l'heure/demande.
3. **Choc opérationnel** : même point de rupture, ralentissement de préparation
   et perturbations non annoncées du transport et de la capacité soignante.

Pour un même index/graine, les requêtes visibles sont identiques entre ces flux.
Le nom du régime, les futurs temps de préparation et les perturbations cachées
n'entrent jamais dans les arguments du planificateur.

L'évaluation applique chaque action aux mêmes réalisations et utilise le notateur
de parcours. `decision_cases.hand_oracle`, un calcul algébrique séparé du simulateur
et du notateur, vérifie pour chaque action l'attente, les admissions et les
expositions de surcharge. Toute divergence interrompt l'expérience.

Cet oracle est limité au fixture à deux unités/six heures. Les épisodes ne
propagent pas les patients et ressources au suivant : seule la mémoire du
superviseur est séquentielle. Ce n'est pas encore le déroulement continu d'un hôpital.

## Supervision à information disponible

Les prévisions de la référence et du mélange candidat sont figées à chaque origine.
Elles continuent à être suivies en parallèle, même lorsque l'action utilise un
repli. Chaque label devient disponible **24 heures après son origine**, y compris
si l'événement est observé plus tôt. La censure est indépendante dans ce fixture.

Le superviseur refuse les labels futurs, les doublons patient, les retours d'un
autre périmètre et les retours en arrière de l'horloge. Les suivis ne couvrant
aucun intervalle complet et sans événement ne comptent pas comme information.

Après 24 labels informatifs, une fenêtre mobile de 24 compare :

- la différence de log-perte censurée du candidat et de la référence ;
- la log-perte de la référence, pour ne pas la considérer toujours fiable.

Le premier seuil est le maximum entre 0,05 et le quantile empirique 95 % des
moyennes mobiles de calibration, augmenté de 0,05. Le second est le quantile
empirique 99 % des moyennes mobiles de la référence, augmenté de 0,25. Ce sont
des seuils de recherche fondés sur un petit échantillon, **sans garantie de taux
de fausse alerte**. Ce n'est pas une implémentation de WATCH ou d'une borne conforme.

La revue a confirmé que 40 labels ne donnent que 17 fenêtres chevauchantes :
les quantiles 95 % et 99 % sélectionnent tous deux le maximum de leur série.
Ces seuils v1 n'ont pas d'ARL contrôlé et ne doivent pas être réutilisés comme
calibration opérationnelle. La v2 calibre conjointement des CUSUM sur des flux stables.

Une alarme relative verrouille le repli vers la référence. Une alarme sur la
référence suspend les recommandations. Il n'y a pas de reprise automatique dans
ce lot. La supervision est commune aux deux unités ; une supervision par service
reste à développer.

Le fixture suppose qu'un flux distinct observe la fin de préparation des deux
patients, même si leur transport n'est pas demandé. L'action ne modifie pas leur
préparation. Cette hypothèse évite une sélection des labels par politique dans
l'expérience ; elle devra être vérifiée ou remplacée sur données réelles.

## Protection au moment de la décision

Avant une alarme, le candidat est comparé sous les deux modèles. Une action doit
respecter leurs contrôles mécaniques, ne pas augmenter les expositions simulées
et rester bénéfique face à l'inaction. Si son écart au meilleur objectif d'un
modèle dépasse 30 patients-minutes, la politique peut revenir à l'action de
référence lorsque son bénéfice est partagé par les deux modèles.

Cette valeur de 30 est un point de fonctionnement synthétique, pas un seuil
métier validé. Le repli conserve une action utile sous les deux hypothèses mais
ne garantit ni optimalité au pire cas, ni regret réel inférieur à 30. L'absence
de bénéfice partagé entraîne une abstention. Repli, abstention et inaction sont
comptés séparément.

## Mesures et lecture du test réservé

Les chiffres qui suivent décrivent l'exécution historique v1 et ne constituent
pas une démonstration d'efficacité. Ils ne sont pas les résultats du protocole v2.

Le rapport donne les moyennes, résultats par graine et phases avant/après rupture :
attente cumulée sur six heures en patients-minutes, gain face à l'inaction, écart
apparié à la référence, regret face à l'oracle, pire décile du regret, expositions
par ressource, fréquence des régressions de ressource, repli et abstention.

Les conclusions doivent porter sur la phase après rupture : une moyenne mélangeant
avant et après peut masquer une régression. Sur les 96 épisodes après réorganisation,
le boosting est moins bon que la référence dans 10,4 % des cas, le mélange fixe
dans 8,3 % et le mélange supervisé dans 3,1 %. L'attente cumulée moyenne est
respectivement de 940,78, 938,59 et 933,28 patients-minutes, contre 941,41 pour la
référence. Le gain moyen du mélange supervisé est donc de 8,13 patients-minutes
par épisode de six heures, soit environ 0,9 % : ce n'est pas un gain par patient.
Le triplet meilleur/égal/pire vaut 11/75/10 pour le boosting, 9/79/8 pour le
mélange fixe et 7/86/3 pour le mélange supervisé. Le gain supervisé repose sur
10 épisodes de résultat différent ; il ferme 14,8 % de l'écart agrégé à l'oracle
clairvoyant. Cet oracle n'est pas une politique atteignable. Aucun intervalle
apparié n'a été établi ; trois trajectoires indépendantes sont insuffisantes
pour une conclusion robuste, même si les trois moyennes sont favorables.
La régression de prévision antérieure ne devient donc pas systématiquement une
régression moyenne de décision dans ce nouveau fixture. Les deux expériences
portent sur des mécanismes, des modèles et des mesures distincts.

Les alarmes de deux replays de réorganisation apparaissent 38 et 40 heures après
la rupture, avec des labels décalés de 24 heures. Le troisième déclenche à 20 h,
alors qu'aucun label post-rupture n'est encore disponible : c'est une fausse alerte,
également observée sur le contrôle stable de la même graine. Elle ne doit pas
être comptée comme une détection de dérive. Le rapport distingue le temps écoulé
depuis la rupture du délai de détection admissible. Une alarme sur trois contrôles
stables est observée ; ce faible effectif ne permet pas d'estimer un taux général.
Une partie du repli observé provient donc d'une alarme sans preuve de changement.
Cette graine représente 22 des 47 épisodes de repli post-réorganisation.

Le flux avec chocs non annoncés conserve des expositions de surcharge, y compris
avec le repli. La continuité des tâches après réduction de capacité peut créer
une surcharge sans violation des invariants mécaniques : zéro erreur de mécanique
ne signifie pas absence de tension. La référence elle-même n'élimine pas ce risque.
Après choc, la politique supervisée augmente au moins une exposition de surcharge
par rapport à l'inaction dans 13,5 % des épisodes. Ce taux est identique à celui de
la référence ; le repli ne constitue donc pas une protection suffisante contre
ces perturbations.

La politique supervisée ne s'abstient pas dans les neuf replays exécutés ; elle
utilise des replis. Les tests vérifient séparément sa suspension lorsque la
référence devient mauvaise. Il n'y a ni preuve d'efficacité clinique, ni intervalle
de confiance, ni certificat de robustesse globale dans ce résultat.

Le rapport conserve explicitement `research_only_no_promotion`. La suite devra
étudier une sélection orientée coût de décision, des signaux organisationnels
observables et des hypothèses de ressources plus variées, avec un nouveau test.

## Reproduire

```bash
PYTHONPATH=src python -m hospitalos.hybrid.decision_benchmark
PYTHONPATH=src:. pytest -q tests/hybrid/test_decision_guard.py
```

Le résultat est imprimé en sortie standard. Aucun dataset, rapport généré ou
modèle sérialisé n'est versionné. Les fonctions de supervision et de mélange
restent séparées du comportement par défaut de l'API et du workflow d'exécution.
