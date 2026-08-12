# Dossier de review DSI — Nantes v0.1 (gabarit)

> À remplir et joindre à chaque livraison soumise à la DSI du CHU. Objectif : la DSI
> valide en lecture, sans avoir à exécuter, parce que les preuves sont dans le dossier.

## 1. Identité de la livraison
- Ticket(s) : HOS-___
- Commit / tag :
- Branche :
- Date :
- Auteur / relecteurs (AAA) :

## 2. Périmètre
- Ce qui change (1 paragraphe) :
- Ce qui **ne** change **pas** (garanties préservées) :
- Fichiers touchés :

## 3. Garanties de sécurité (santé)
| Garantie | Statut | Preuve (test / ligne / rapport) |
|---|---|---|
| Aucune donnée nominative / texte libre (logs, fixtures, rapports) | ✅ / ⛔ | |
| Privacy Gate fail-closed | ✅ / ⛔ / n/a | |
| Temporal-Leakage (`available_at`) fail-closed | ✅ / ⛔ / n/a | |
| Provenance `run_id` + `schema_version` | ✅ / ⛔ / n/a | |
| Aucune réparation silencieuse des données | ✅ / ⛔ | |
| Exécution offline (no outbound) | ✅ / ⛔ / n/a | |
| Aucune revendication causale (simulation) | ✅ / n/a | |

## 4. Preuves d'exécution (commandes + sorties réelles)
```
ruff check <fichiers>            -> …
ruff format --check <fichiers>   -> …
mypy --strict <modules>          -> …
pytest <tests> --cov ...         -> N passed, coverage X% (≥ 95% couche sécurité)
docker compose config / build    -> … (si applicable)
```
- Job CI `gate-a-safety` : lien + statut (vert requis).

## 5. Données & conformité
- Données persistées (volumes, contenu, rétention) :
- Chiffrement at-rest / résidence (enclave, France) :
- Champs `restricted` éventuels (ex. `avg_seniority_months`) et justification :
- Base légale / avis DPO (si applicable) :

## 6. Déploiement & réversibilité
- Enveloppe : `deploy/nantes/deployment_envelope.yaml` (version) :
- Gates de durcissement release appliqués (digests, bind 127.0.0.1, pas de bind-mount, secrets overridés) : ✅ / ⛔
- Procédure de rollback (digest N-1 + restauration dumps) :

## 7. Revue AAA (relecture hostile)
| Lens | Verdict | Findings bloquants traités |
|---|---|---|
| Head of Engineering | GO / … | |
| Head of Product | GO / … | |
| Head of ML | GO / … / n/a | |

## 8. Risques résiduels & limites connues
- …

## 9. Décision
- [ ] GO  [ ] RESTRICT  [ ] NO-GO — motif :
