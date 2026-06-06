# Architecture - Passe 1

## Decisions

- Monorepo unique pour garder les contrats donnees proches des connecteurs, dbt, Feast et Dagster.
- Redpanda est utilise comme broker Kafka-compatible sans dependance GAFAM.
- TimescaleDB porte les evenements canoniques et les marts temporels, avec hypertables et compression native.
- Feast utilise TimescaleDB comme offline store et Redis comme online store local.
- Dagster orchestre uniquement ingestion, normalisation, dbt, validations et materialisation Feast pendant la passe 1.
- MLflow est declare dans Compose mais aucun pipeline training n'est implemente avant la passe 2.

## Trade-offs Passe 1

- Le registry Feast est local pour minimiser l'infrastructure. Un registry SQL ou objet souverain pourra etre introduit plus tard si le deploiement l'exige.
- Les conteneurs applicatifs Python sont construits localement afin de figer les versions Dagster/dbt/Feast sans dependre d'une image applicative externe.
- La generation MIMIC-IV demo devra respecter la DUA PhysioNet : le loader echouera proprement si les donnees ne sont pas disponibles localement.

## Passe 2 Prevue

- API FastAPI `/predict/charge`.
- Modeles ML de prevision charge SIIPS/AAS.
- Pipelines MLflow de training et registry.
- Dashboard cadre de sante.
- Monitoring Evidently et sensors Dagster de drift.

## Decisions ML Passe 2

- L'encodeur d'etat hybride est implemente comme un module PyTorch autonome afin de pouvoir etre reutilise par le TFT, l'API de prediction et les tests de latence sans couplage a Feast ou MLflow.
- La branche temporelle conserve la specification produit : GRU 2 couches, hidden size 256, dropout 0.1 et dernier etat temporel.
- La branche statique projette les attributs service/hopital en 128 dimensions, puis la fusion produit un vecteur d'etat 512D normalise par `LayerNorm`.
- Le test de latence p99 CPU cible moins de 20 ms sur batch 1, avec un marker pytest `performance` pour rendre ce contrat explicite en CI.
- Le wrapper Moirai est concu en mode souverainete stricte : il ne declenche aucun telechargement de poids et bascule explicitement sur un baseline seasonal-naive si `uni2ts` ou les checkpoints locaux ne sont pas disponibles.
- `uni2ts` est expose comme extra optionnel `foundation` pour eviter de casser les tests air-gapped tout en gardant le point d'integration Moirai dans le code.
- Le TFT est expose via `CarePredictTFT`, avec un backend `pytorch-forecasting` optionnel et un fallback interpretable pour les tests, l'API et les environnements sans checkpoint local.
- La calibration conforme est stockable comme artefact JSON et applique un intervalle symetrique base sur le quantile de residus de validation.
- L'API FastAPI garde le fetch Feast et le chargement MLflow derriere des dependances injectables pour pouvoir mocker les tests et remplacer les fallbacks sans changer les routes.
- Le dashboard React reste une page operationnelle unique, optimisee pour le scan quotidien d'un cadre de sante.
