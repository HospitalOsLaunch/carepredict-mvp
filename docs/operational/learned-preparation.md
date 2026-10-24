# Premier délai appris : préparation résiduelle avant les files de ressources

Statut : expérience synthétique reproductible, 24 octobre 2026. Le composant
est optionnel. Aucun apprentissage sur des données hospitalières réelles,
passage de G1 ou gain clinique n'est établi.

## Frontière de la cible

La cible `residual_preparation_before_resource_queue` mesure le temps entre D
et la fin de préparation opérationnelle d'un patient déjà autorisé à sortir.
Le moteur ajoute ensuite les attentes d'aval et de transport, le transport
effectif, puis le nettoyage avant l'admission suivante. Il garde les contrôles
médicaux et logistiques attestés dans les faits.

Les cibles de durée restante jusqu'au départ de `synthetic/patient_learning.py`
ne sont pas réutilisées : elles comprennent des délais que le moteur représente
déjà. Les substituer à la préparation ferait compter ces délais deux fois.
Un futur raccordement nécessite un événement de fin de préparation distinct,
son heure de disponibilité dans le SI et une politique explicite de censure.

Le modèle ne prédit ni l'autorisation médicale, ni la compatibilité, ni
l'acceptation clinique d'aval. Il couvre les patients présents et éligibles à D,
y compris ceux dont le transport reste à demander. Les nouveaux admis pendant
la simulation ne reçoivent pas de durée de séjour par ce composant.

## Estimation et référence

`survival.py` compare deux modèles de risque discret aux bornes
30, 60, 120, 240, 480 et 1 440 minutes :

- référence : risque par intervalle, avec lissage `(événements + 0,5)/(à risque + 1)` ;
- candidat : `HistGradientBoostingClassifier`, appliqué aux lignes patient–intervalle.

Les entrées sont la charge en lits occupés et la demande en attente rapportées
à la capacité soignante positive observée, l'heure UTC cyclique, le week-end et
l'indice d'intervalle. Les plages de charge et les établissements/unités admis
sont ajustés sur l'entraînement uniquement. Les identifiants ne sont pas des
variables prédictives. Aucune vérité future du générateur n'entre dans ces variables.

Un événement est placé dans son intervalle. Une censure ne produit des zéros que
pour les intervalles intégralement observés ; sa portion d'intervalle incomplète
ne devient jamais un faux départ ou un faux négatif. Le générateur de ce lot
produit les événements exactement aux bornes. Des timestamps continus exigeraient
d'évaluer le biais de discrétisation et le traitement des intervalles partiels.

Le risque conditionnel `h_j` donne la masse `S_(j-1) × h_j`, puis
`S_j = S_(j-1) × (1-h_j)`. La survie après 24 h est conservée : une trajectoire
tirée dans cette queue ne force aucun départ dans l'horizon. Un quantile situé
dans cette queue renvoie `None`, pas une extrapolation inventée.

## Séparation temporelle

Les périodes sont fixées dans `learning_demo.protocol()` avant l'expérience :

| Usage | Origines UTC, début inclus / fin exclue | Effectif synthétique |
|---|---|---:|
| Entraînement | 1–15 septembre 2026 | 600 |
| Recalibrage | 17–20 septembre 2026 | 200 |
| Sélection | 22–25 septembre 2026 | 200 |
| Test réservé | 27–30 septembre 2026 | 300 |

Chaque fenêtre est suivie d'au moins 24 h d'embargo pour disposer de ses labels
avant la suivante. `features_available_at <= origin` et les dates de disponibilité
des labels sont contrôlées. Un patient n'apparaît qu'à une origine et dans une
seule partition ; les doublons et les épisodes hors fenêtres sont refusés.

Le recalibrage ajuste un décalage global de logit par modèle sur une grille fixe.
La sélection utilise la vraisemblance censurée sur la période suivante ; la
référence gagne les égalités. `select_model` ne reçoit aucun jeu de test. Le
modèle sélectionné n'est disponible qu'après la date de disponibilité des labels
de sélection. Les hyperparamètres sont fixes, sans arrêt anticipé aléatoire.

La graine et les flux aléatoires de contexte, d'événement et de censure sont
séparés. Le générateur produit une censure indépendante des covariables et des
événements. Les quatre périodes partagent le même mécanisme : cette séparation
vérifie le protocole, sans démontrer de robustesse à un changement d'hôpital ou
de régime. Consulter plusieurs fois ce test pour régler le modèle le transformerait
en validation ; réserver alors un nouveau test avant de conclure.

## Mesures

- Log-vraisemblance négative des intervalles observés, moyenne par patient,
  avec nombre de cas informatifs, événements et censures.
- Brier IPCW à 60, 120, 240 et 480 minutes ; distribution de censure estimée
  sur l'entraînement seulement par Kaplan–Meier inversé.
- Taux d'événement prédit et taux pondéré observé aux mêmes horizons.

Un horizon sans support de censure suffisant (`G < 0,1`, ou suivi insuffisant)
est signalé comme non mesurable. Les poids ne sont pas écrêtés pour fabriquer
un score. Les événements gagnent les égalités événement/censure ; leur poids
utilise `G(T-)`, les survivants observés après l'horizon utilisent `G(h)`.
La censure du générateur ne coïncide pas avec les quatre horizons de mesure.

Ces mesures et le recalibrage ne prouvent ni couverture conforme, ni calibration
par sous-groupe, ni validité sous censure informative. Il n'y a pas d'intervalle
de confiance ou de preuve de supériorité statistique dans ce lot.

## Raccordement au moteur

`forecast_preparation` produit `PREPARATION_FORECAST_1`, un contrat JSON contenant
les masses, la queue, l'identité du modèle, sa date de disponibilité et l'empreinte
de l'état d'origine. L'API reçoit ce contrat ; elle ne charge aucun estimateur,
pickle ou modèle depuis un chemin fourni par le client. L'identité est une
empreinte de reproductibilité, pas une signature d'authenticité.

Le contrat doit couvrir exactement les patients éligibles de cet état. Le calcul
hors établissement/unité ou hors plage de charge d'entraînement est refusé. Cela
ne constitue pas un détecteur complet de changement de distribution.

La même innovation par patient/scénario est utilisée pour toutes les actions.
La préparation apprise remplace le délai de préparation hypothétique ; elle
n'est pas multipliée une seconde fois par le facteur commun de charge. Les
durées de transport et de nettoyage continuent à utiliser leurs hypothèses.
Les contrôles de ressources et le notateur indépendant restent actifs. Le notateur
vérifie la mécanique du parcours, pas la justesse statistique des prévisions.

Sans champ `preparation`, les anciennes démos conservent leurs durées déclarées.
Avec ce champ, une prévision incompatible est refusée sans repli silencieux.
Les sorties `HYBRID_PLAN_4` incluent le contrat dans l'identité et le contenu
persisté. Les propositions v1/v2/v3 doivent être régénérées ; conserver l'historique
et réconcilier une émission inconnue avant toute nouvelle émission sandbox.

## Exécution

L'apprentissage utilise scikit-learn `>=1.5,<1.9`, déjà déclaré dans le dépôt.
L'API et les anciennes démos n'importent pas ce module d'apprentissage.

```bash
PYTHONPATH=src python -m hospitalos.hybrid.learning_demo
PYTHONPATH=src python -m hospitalos.hybrid --demo-learned --show-trace
PYTHONPATH=src python -m hospitalos.hybrid --demo-learned --show-input
PYTHONPATH=src:. pytest -q tests/hybrid
```

Le premier programme imprime les mesures de l'expérience en sortie standard.
Le deuxième entraîne sur synthétique et branche la distribution retenue au
parcours à un lit. Aucun dataset, modèle sérialisé ni rapport de mesures n'est
versionné. Le code, les tests et ce contrat suffisent à reproduire l'expérience.

## Suite scientifique

Établir la sémantique de fin de préparation sur un flux réel autorisé, vérifier
les horloges et le suivi, puis conduire une évaluation rétrospective temporelle.
Étudier ensuite la censure informative, les risques concurrents, les origines
répétées, la calibration par service et les dépendances résiduelles entre patients.
Ici les tirages de préparation sont indépendants conditionnellement aux variables
de charge ; les futurs changements de capacité ne modifient pas leur distribution.
La validité causale d'une intervention et les plans multistades restent à établir.

Références méthodologiques :

- [Gensheimer et Narasimhan — survie en temps discret](https://pmc.ncbi.nlm.nih.gov/articles/PMC6348952/).
- [scikit-learn — HistGradientBoostingClassifier](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html).
- [scikit-survival — Brier IPCW, hypothèses et support](https://scikit-survival.readthedocs.io/en/latest/api/generated/sksurv.metrics.brier_score.html).
