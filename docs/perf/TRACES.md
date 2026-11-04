# Traces de l'API (OpenTelemetry)

Règle 18 de l'audit de performance. Une trace dit où passe le temps d'un appel lent :
chaque requête SQL, et les étapes nommées du calcul (lecture des séjours, ajustement du
modèle de sortie, prévision par unité, contexte des demandes…).

## Activer

Désactivées par défaut : rien n'est envoyé tant que le groupe ne nomme pas son propre
collecteur (Jaeger, Grafana Tempo, OpenTelemetry Collector), sur son réseau.

| Variable | Effet |
|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT=http://collecteur:4318` | envoi OTLP/HTTP au collecteur du groupe |
| `ADM_TRACES=console` | chaque étape affichée dans la sortie de l'API (diagnostic local) |
| `OTEL_SERVICE_NAME` | nom du service (par défaut `hospitalos-api`) |
| `OTEL_TRACES_SAMPLER=parentbased_traceidratio`, `OTEL_TRACES_SAMPLER_ARG=0.1` | garder un appel sur dix |

## Données de santé : ce qui sort, ce qui ne sort jamais

Une trace quitte l'API avec une **liste fermée** d'attributs (`services/admissions_smr/tracing.py`).
Tout le reste est retiré avant l'envoi, quoi qu'enregistrent les bibliothèques
d'instrumentation.

| Sort | Ne sort jamais |
|---|---|
| méthode, modèle de route (`/api/requests/{request_id}`), statut | la chaîne de requête (une recherche peut contenir le nom d'un patient) |
| texte SQL avec ses paramètres `?` | les valeurs SQL |
| durées, comptes `hospitalos.*` (nombre de séjours, d'unités) | l'adresse IP et le navigateur de l'appelant |
| type d'une exception | son message (il peut citer une valeur) |

Des tests vérifient qu'une recherche « Martin Dupont » ne laisse aucune trace de ce nom,
de la chaîne de requête, du navigateur ni de l'adresse de l'appelant.

## Ce que les traces ont montré (démo LISCOP, 4 novembre 2026)

Les trois appels lents repérés sur téléphone (`APPAREIL_LENT.md`) et la prévision ont
le même coût, qui n'était pas celui qu'on soupçonnait :

| Appel | Total | SQL | `forecast.read_stays` | `forecast.fit_hazard` |
|---|---|---|---|---|
| `/api/dashboard` | 366 ms | 11 requêtes, 2 ms | **324 ms** | 12 ms |
| `/api/requests?scope=a_traiter` | 362 ms | 11 requêtes, 7 ms | **319 ms** | 11 ms |
| `/api/forecast` | 374 ms | 9 requêtes, 1 ms | **336 ms** | 11 ms |
| `/api/stays` | 360 ms | 8 requêtes, 7 ms | (même lecture) | 11 ms |

Le modèle de sortie s'ajuste en 11 ms. Le temps part dans la lecture des 10 955 séjours
du groupe, chargés en objets ORM complets à chaque appel pour n'en garder que sept
colonnes. La durée « SQL » d'une trace ne compte que l'exécution, pas la construction des
objets : c'est l'étape nommée qui l'a révélé.
