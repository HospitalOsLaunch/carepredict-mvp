# MLflow

MLflow is declared in Docker Compose for pass 2 readiness only.

Pass 1 does not define training pipelines, model registry workflows, or inference code. The service runs with a local SQLite backend store and a local artifact directory so the stack remains sovereign and air-gapped.
