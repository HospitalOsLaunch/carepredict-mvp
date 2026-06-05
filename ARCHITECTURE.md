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
