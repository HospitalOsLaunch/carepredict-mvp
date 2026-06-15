# MTS-JEPA fédéré et calibration conforme sous régimes

Ce sous-module reproduit un forecaster JEPA multi-échelle, une simulation de
fédération FedProx et une calibration conforme adaptative. Les deux volets
n'ont pas le même statut scientifique et doivent être interprétés séparément.

## Statut scientifique

### Calibration conforme : résultat

Sous dérive synthétique de régime, le conformal statique calibré en période
calme s'effondre, avec une couverture observée d'environ `0,22–0,41`. L'ACI et
sa variante à pas adaptatif récupèrent une couverture de long terme proche de
`0,88`. La validité multi-niveaux a été vérifiée sur quarante graines : les
points restent sur la diagonale nominale, avec un écart maximal inférieur à
`0,004` dans le protocole de référence.

L'unité conforme est la trajectoire complète. Le score de non-conformité est
la norme-sup des résidus absolus sur l'horizon, puis le quantile applique la
correction de finitude. Cette construction garantit une couverture marginale
au niveau trajectoire sous échangeabilité ; elle ne revendique pas une
couverture conditionnelle exacte à chaque instant.

### Fédération : proof-of-mechanism

FedProx réduit mécaniquement la dérive des clients par rapport à FedAvg dans le
setup synthétique testé. Son bénéfice prédictif reste négligeable sur ce même
setup : aucune amélioration de loss test n'est revendiquée. La fédération est
donc présentée comme une preuve de bon fonctionnement du mécanisme proximal,
pas comme un résultat de supériorité prédictive.

La moyenne de poids de Transformers reste exposée au problème d'alignement de
permutation décrit par Ainsworth et al. (2023). Cette limite structurelle est
assumée et la dérive student-vers-global est rendue observable dans les logs.

## Garanties implémentées

- Cibles JEPA horaires, journalières et bi-journalières non dégénérées.
- Décodage parallèle par queries positionnelles, sans masque causal factice.
- Baseline saisonnière alignée sur les dernières 24 heures du contexte.
- Split-conformal par trajectoire avec correction de finitude.
- ACI et DtACI en predict-avant-update, sans intervalle magique au démarrage.
- Teacher EMA mis à jour une seule fois par round, après FedAvg des students.
- Terme FedProx réel sur les paramètres entraînables.
- Garde anti-collapse par suivi de `emb_std` et composantes de loss séparées.
- Cohérence inter-échelle imposée dans l'espace observable décodé.
- Couverture roulante de longueur strictement identique à l'entrée.

## Exécution

Entraînement fédéré et évaluation :

```bash
python -m src.forecasting.mts_jepa_federated
```

Configuration courte :

```bash
python -m src.forecasting.mts_jepa_federated \
  --rounds 2 --epochs 1 --clients 2 --quiet
```

Génération des figures :

```bash
python -m src.forecasting.make_figures --outdir /tmp/figs
```

Tests des garanties :

```bash
pytest tests/test_mts_jepa_federated.py -v
```

## Figures

1. **Convergence ACI** : couverture roulante et évolution de l'alpha adaptatif.
2. **Couverture par régime** : couverture Mondrian, Wilson et largeur moyenne.
3. **Stress de dérive** : statique, ACI et DtACI sur calme → crise → calme.
4. **Fédération** : composantes de loss, `emb_std` et dérive client.
5. **Sweep de validité** : couverture empirique contre couverture nominale.
6. **Efficacité** : frontière couverture trajectoire / largeur normalisée pour
   le modèle et la baseline saisonnière.

Les PNG sont produits à 150 dpi avec un style volontairement sobre : grille
pointillée, légendes sans cadre et axes supérieur/droit masqués.

## Limites

- L'ACI peut sous-couvrir pendant une transition rapide. La borne de Gibbs et
  Candès (2021) est asymptotique et ne constitue pas une garantie uniforme en
  échantillon fini.
- Le setup est synthétique ; aucune validité n'est encore établie sur des
  données SIIPS hospitalières réelles.
- Le bootstrap du run court ne montre pas encore de supériorité du modèle sur
  la baseline saisonnière. Cette absence de résultat positif est conservée et
  rapportée honnêtement.
- L'agrégation par moyenne de poids ne résout pas l'alignement de permutation
  des Transformers.

## Références

- Gibbs & Candès (2021), *Adaptive Conformal Inference Under Distribution Shift*.
- Vovk, Gammerman & Shafer (2005), *Algorithmic Learning in a Random World*.
- Romano, Patterson & Candès (2019), *Conformalized Quantile Regression*.
- Li et al. (2020), *Federated Optimization in Heterogeneous Networks*.
- Assran et al. (2023), *Self-Supervised Learning from Images with a Joint-Embedding Predictive Architecture*.
- Grill et al. (2020), *Bootstrap Your Own Latent*.
- Bardes, Ponce & LeCun (2022), *VICReg*.
- Nie et al. (2023), *A Time Series is Worth 64 Words*.
- Zaffran et al. (2022), *Adaptive Conformal Predictions for Time Series*.
- Bhatnagar et al. (2023), travaux sur DtACI et la calibration conforme en ligne.
- Ainsworth, Hayase & Srinivasa (2023), *Git Re-Basin*.

