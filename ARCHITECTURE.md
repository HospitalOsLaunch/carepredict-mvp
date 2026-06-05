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
