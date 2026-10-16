# Protocole et références multi-hôpitaux — lot 05

Ce lot entraîne trois régressions de référence, une par cible, sur des hôpitaux
synthétiques et les compare à la persistance et à la saisonnalité hebdomadaire.
Il fournit un protocole d'ingénierie exécutable, figé avant l'ajustement. Ce n'est
ni le protocole final signé de phase 0, ni une évaluation du futur world model.

## Population et séparation

`cohort_baselines_v1.json` définit une cohorte nouvelle, avec sa propre identité
et sa graine. Les scores descriptifs des cohortes précédentes ne sont pas réutilisés.
Les plages de paramètres restent des hypothèses d'ingénierie non calibrées.

| Ensemble | Hôpitaux | Structure | Répétitions annuelles |
|---|---:|---|---:|
| Apprentissage | 2 | 2 pôles, 4 unités | 2 par hôpital |
| Validation | 2 | 3 pôles, 6 unités | 2 par hôpital |
| Test réservé | 2 | 4 pôles, 8 unités | 2 configurations par hôpital, sans trajectoires |

Chaque trajectoire couvre 2025 après 61 jours de chauffe. Les répétitions sont
indépendantes sous une même configuration hospitalière, pas deux années successives.
Le découpage réserve établissements et structures ensemble ; il ne permet pas
d'isoler leurs effets respectifs. Une seule structure existe par partition.
Les trois ensembles utilisent la famille `v041` : aucun test de mécanisme inédit.

Le benchmark refuse une cohorte ayant ouvert le test, des mondes manquants ou
ajoutés, des métadonnées incohérentes et des empreintes modifiées. Il n'a aucune
option pour évaluer le test final. Les configurations du test restent visibles
pour vérifier la réservation, ses trajectoires ne sont pas matérialisées.

## Contrat de prévision

Horizon fixe : **24 heures**. Trois cibles instantanées à la frontière `t+24` :
lits occupés, nombre de patients en attente aux urgences et charge de soins en
minutes par heure. Ce ne sont ni des cumuls sur 24 h, ni des durées de séjour.

Les variables proviennent exclusivement du contrat d'observation du lot 02 :
17 états agrégés par unité, disponibles au moment de la décision. Le gradient
boosting reçoit ces états à `t`, `t-24` et `t-168`, leur ancienneté courante,
le nombre de lits ouverts, des cycles calendaires et la spécialité de l'unité.
Les identifiants de site, monde et graine servent aux jointures et contrôles,
jamais à la régression. Aucune note, trajectoire patient, variable cachée de
simulation, future action ou cible future n'entre dans les variables.

Chaque état historique est celui **connu à sa propre date** ; une correction
reçue plus tard ne le remplace pas rétroactivement. Les états anciens/manquants
dans les retards de 24/168 h deviennent NaN. L'échelle des états et des cibles
apprises est `max(1, lits ouverts observés à t)`. La spécialité est une propriété
statique connue. Le calendrier garde la convention UTC+01 fixe du générateur.

| Référence | Prévision d'unité |
|---|---|
| Persistance | Dernier état disponible à `t` |
| Saison hebdomadaire | État connu à `t+24-168`, soit `t-144` |
| Gradient boosting | Un `HistGradientBoostingRegressor` partagé entre unités pour chaque cible |

Paramètres fixés : perte absolue, 100 itérations, taux 0,05, 15 feuilles,
100 observations minimales par feuille, régularisation L2 de 1, graine 1701,
arrêt anticipé désactivé et un fil de calcul. Aucune recherche d'hyperparamètres,
aucun ajustement ni calibrage sur la validation. Les poids donnent la même masse
à chaque hôpital, puis à ses répétitions, puis aux lignes d'une répétition.
La perte d'apprentissage porte sur les valeurs par lit ; les erreurs publiées
sont mesurées dans les unités naturelles.

Les sorties apprises sont ramenées à zéro si négatives, sans plafond d'occupation :
le nombre de lits ouverts à 24 h est inconnu. Les prévisions de pôle/hôpital sont
les sommes des prévisions d'unité. Cette cohérence arithmétique ne constitue pas
un modèle d'allocation ou de concurrence entre ressources. Le modèle hybride
à règles reste à développer.

## Fenêtres, abstentions et métriques

Les premières 168 heures servent de contexte ; aucun score ni exemple
supervisé n'en est tiré. Une cible au-delà de la fin d'année est exclue, sans
la remplir. La frontière exacte de fin d'année reste évaluable. Il n'y a pas
de coupure temporelle interne train/validation, donc pas de frontière temporelle
que des horizons pourraient franchir : les trajectoires entières sont séparées
par établissement. Un futur découpage temporel devra ajouter son propre embargo.

Pour une comparaison appariée, les trois méthodes s'abstiennent quand l'état
courant **ou celui de `t-144`** manque ou dépasse son seuil d'ancienneté. Cela
contraint volontairement la persistance et le gradient boosting au support de
la saisonnalité. Les agrégats s'abstiennent si un seul membre s'abstient ; on ne
remplace jamais une unité absente par zéro. La couverture rapportée est celle
de cette comparaison commune, pas la disponibilité maximale de chaque modèle.

MAE, RMSE et biais sont calculés pour chaque entité dans chaque répétition.
La synthèse fait la moyenne des entités d'un niveau dans une répétition, puis
des répétitions dans un hôpital, puis des hôpitaux. Ainsi un grand établissement
ne domine pas le score par son nombre de lignes. La RMSE synthétique est une
**moyenne des RMSE d'entité**, pas une RMSE globale calculée après réunion des erreurs.
Les niveaux et cibles gardent leurs unités distinctes. Le détail par unité,
pôle et établissement reste dans `metrics.json` pour détecter les dégradations.

Deux hôpitaux de validation ne permettent ni intervalle de confiance fiable entre
sites ni conclusion de généralisation. Les observations horaires ne sont pas
traitées comme des essais indépendants. Aucun seuil de phase 2, porte G1–G4 ou
porte SYN n'est déclaré franchi ; les intervalles prédictifs restent à ajouter.
Le dimensionnement des cohortes et les seuils absolus/relatifs du protocole final
restent ouverts. Ces données ne démontrent pas un transfert au réel.

## Reproduire

Exécuter depuis un checkout figé, avec les versions d'exécution du manifeste.
Ne pas modifier les sources pendant la génération ou entre le gel et le benchmark.

```bash
PYTHONPATH=src python -m hospitalos.synthetic.cohort freeze \
  --plan configs/synthetic/cohort_baselines_v1.json \
  --output runs/synthetic/lot05/registry
PYTHONPATH=src python -m hospitalos.synthetic.cohort generate \
  --registry runs/synthetic/lot05/registry \
  --output runs/synthetic/lot05/cohort --with-learning
PYTHONPATH=src python -m hospitalos.synthetic.benchmark freeze \
  --registry runs/synthetic/lot05/registry --cohort runs/synthetic/lot05/cohort \
  --protocol runs/synthetic/lot05/protocol.json
PYTHONPATH=src python -m hospitalos.synthetic.benchmark run \
  --registry runs/synthetic/lot05/registry --cohort runs/synthetic/lot05/cohort \
  --protocol runs/synthetic/lot05/protocol.json --output runs/synthetic/lot05/benchmark
```

La génération produit déjà les anciennes métriques de persistance du lot 02 ;
elles ne sont pas consommées par le benchmark. Le nouveau protocole est figé
avant tout ajustement ou score comparatif du lot 05, mais cela ne constitue pas
un préenregistrement externe. Le code du protocole est défini avant génération.

Le protocole lie les empreintes du registre, de la cohorte, du code et les versions
Python/NumPy/Pandas/Pydantic/scikit-learn. Il refuse l'écrasement et tout changement
au lancement. Les sorties sont publiées atomiquement dans un nouveau dossier :
protocole, trois modèles dans `models.pkl`, prévisions de validation par monde,
métriques détaillées et manifeste avec empreintes. Les modèles sont générés
localement ; aucun pickle entrant n'est chargé par ce pipeline. Ne charger que
des modèles de provenance vérifiée et avec leurs versions de dépendances.

Les sorties volumineuses sont régénérables sous `runs/`. Le dépôt conserve
les [preuves et résultats de cette exécution](evidence/lot05_validation.md),
le protocole, le registre et les manifestes. La reproductibilité exacte des
modèles est testée dans un même environnement ; elle n'est pas promise entre
versions de scikit-learn ou architectures matérielles.

## Suite de phase 0

Prochain lot proposé : interface de politique alimentée uniquement par les
observations disponibles, avec boucle recommandation–approbation–exécution.
Ce raccordement est nécessaire avant d'exercer le modèle hybride à règles
sans accès privilégié au simulateur. La diversité des arrivées, sorties et
effectifs, les parcours patients et le protocole final restent à terminer.
