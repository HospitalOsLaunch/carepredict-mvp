# Vérification exécutée — lot 05

Exécution locale du 15 octobre 2026. Cohorte nouvelle `C_BASELINES_V1`, graine
481516 ; protocoles, code et paramètres fixés avant ajustement. Le benchmark a
été exécuté une fois sur cette cohorte annuelle, sans sélectionner de réglage
après lecture des scores. Le gel est local, pas un préenregistrement externe.

## Contrôles

- 150 tests du socle passent, dont 21 nouveaux ; 54 tests historiques passent.
- Lint sur tout le dépôt, format et typage strict du socle réussis (18 fichiers typés).
- Altérer les cibles de validation dans une fixture laisse les poids et les
  prévisions identiques octet pour octet ; seuls les scores changent.
- Mutations détectées : observation d'un autre monde, doublon, trou dans la grille,
  source d'une autre unité, horizon, cible censurée révélée, NaN, protocole modifié,
  empreinte et chemin de cohorte, ouverture du test.
- Invariance des variables passées quand les observations futures changent ;
  saisonnalité à t-144 vérifiée ; sommes hiérarchiques et abstentions communes.
- 103 empreintes de fichiers vérifiées après exécution, y compris les modèles
  et prévisions annuels ; aucun écrasement d'entrée ni fichier de test généré.
- 81,792 heures hospitalières contrôlées avec la chauffe, zéro violation des
  invariants de lits et de flux.

## Population réellement exécutée

Deux hôpitaux d'apprentissage de 2 pôles/4 unités (102 et 106 lits standard),
deux de validation de 3 pôles/6 unités (152 et 165 lits). Deux répétitions de
2025 par établissement : huit trajectoires annuelles au total, après 61 jours
de chauffe chacune. Quatre configurations annuelles de test restent réservées
pour deux autres hôpitaux de 4 pôles/8 unités ; aucune trajectoire ni mesure de test.

595,680 lignes de variables, 595,680 lignes de cibles
(censures comprises), 412,273 livraisons et 1,420,757 événements.
Les trois régressions sont entraînées chacune sur les mêmes **137,006 lignes d'unité**,
issues exclusivement des quatre trajectoires d'apprentissage.

## Résultats de validation à 24 h

MAE en unités naturelles : lits, patients en attente, minutes de soins par heure.
Moyenne des entités par réalisation, puis des réalisations par hôpital, puis des
deux hôpitaux. La réduction compare le gradient boosting à la meilleure des deux
références simples pour cette cible/niveau ; un signe négatif indique une dégradation.
Les trois méthodes partagent exactement les mêmes décisions évaluées.

| Niveau | Cible | Persistance | Saison hebdomadaire | Gradient boosting | Réduction vs meilleure référence simple | Couverture commune |
|---|---|---:|---:|---:|---:|---:|
| unit | lits_occupes | 1.8819 | 3.6237 | 1.8469 | +1.86 % | 99.9271 % |
| unit | attente_urgences_nb | 0.3022 | 0.3064 | 0.1932 | +36.07 % | 99.9271 % |
| unit | charge_soins_min_h | 40.7164 | 52.6253 | 24.3795 | +40.12 % | 99.9271 % |
| pole | lits_occupes | 2.8810 | 5.2934 | 2.7904 | +3.15 % | 99.9241 % |
| pole | attente_urgences_nb | 0.5207 | 0.5289 | 0.3774 | +27.52 % | 99.9241 % |
| pole | charge_soins_min_h | 68.9404 | 85.0510 | 36.7241 | +46.73 % | 99.9241 % |
| hospital | lits_occupes | 5.9116 | 9.5296 | 5.7507 | +2.72 % | 99.9183 % |
| hospital | attente_urgences_nb | 1.0789 | 1.0959 | 1.0820 | -0.29 % | 99.9183 % |
| hospital | charge_soins_min_h | 172.6308 | 196.6417 | 76.7288 | +55.55 % | 99.9183 % |

**Lecture du résultat :** le gain est net sur la charge de soins dans cette
cohorte, mais limité sur l'occupation (1,86 % à l'unité). Le repère de 10 % de
la roadmap pour les lits n'est donc pas atteint ici ; ce repère n'est pas une
porte formellement évaluée par ce protocole. Le gain sur l'attente à l'unité
ne se retrouve pas à l'hôpital : la MAE y augmente de 0,29 % et le biais vaut
−1,043 patient, contre −0,003 pour la persistance. Les biais hospitaliers du
gradient boosting valent aussi +3,322 lits et +25,485 minutes de soins par heure.
Ces biais sont conservés, sans recalibrage sur la validation. Les métriques
moyennes ne suffisent pas à juger la détection des épisodes rares ou des pics.

Les premières 168 h servent de contexte. Par entité et réalisation, il reste
8 569 décisions à cible disponible et 23 décisions censurées en fin d'année.
Le dénominateur de couverture est 8 569, avant abstentions communes. Les erreurs
par unité/pôle, les MAE/RMSE/biais par hôpital, répétition et méthode ainsi que
les dénominateurs figurent dans [les métriques détaillées](lot05_metrics.json).

## Portée

Les résultats portent sur deux établissements de validation, une structure par
partition et un seul mécanisme v041. Ils ne prouvent ni généralisation G1–G4,
ni qualité clinique, ni gain d'une intervention, ni transfert au réel. Pas
d'intervalle de confiance ou de test de significativité sur les heures corrélées.
Les intervalles prédictifs et les seuils finaux restent ouverts. Le benchmark
ne déclenche aucune validation automatique de porte de la roadmap.

Il s'agit de références de prévision agrégée, sans représentation latente de
patient ni dynamique apprise sous actions. Le modèle hybride à règles et le
world model couplé restent à construire.

## Artefacts

- [Protocole figé](lot05_protocol.json), [registre](lot05_registry.json),
  [manifeste du registre](lot05_registry_manifest.json).
- [Manifeste de cohorte](lot05_cohort_manifest.json),
  [manifeste du benchmark](lot05_benchmark_manifest.json),
  [résultats détaillés](lot05_metrics.json).
- Trois modèles, prévisions et données volumineuses sous `runs/synthetic/lot05/`,
  régénérables avec les commandes et limites de versions du [lot 05](../lot05.md).
