<!--
HospitalOS / CarePredict — Pull Request (contexte santé, enclave CHU).
Chaque PR est relue comme un dossier DSI : elle doit être auto-portante et prouvée.
Ne pas fusionner tant qu'une case obligatoire n'est pas cochée ou explicitement justifiée.
-->

## Ticket
- ID : HOS-___
- Objectif (1 phrase) :
- Chemin critique Gate A : oui / non

## Résumé du changement
<!-- Quoi, pourquoi, et le plus petit périmètre cohérent. -->

## Definition of Done (obligatoire)
- [ ] Tous les critères d'acceptation du ticket sont **prouvés** (test / artefact / revue identifiée).
- [ ] `ruff check` = 0 sur le code ajouté ; `ruff format` conforme.
- [ ] `mypy --strict` = clean sur le code ajouté.
- [ ] Tests unitaires/intégration ajoutés, **cas négatifs et fail-closed couverts**.
- [ ] Le job CI **gate-a-safety** est vert (si la couche sécurité est touchée).
- [ ] Aucune régression sur les checks existants (ou exception expliquée).
- [ ] Périmètre timeboxé respecté (pas d'élargissement).

## Sécurité & données (santé — obligatoire)
- [ ] **Privacy** : aucune donnée nominative / texte libre journalisée, échouée ou echoée. Fail-closed.
- [ ] **Temporal leakage** : `available_at` respecté ; aucune information future à l'origine de prédiction.
- [ ] **Provenance** : sortie reliée à `run_id` + `schema_version` (ou non applicable, documenté).
- [ ] **Pas de réparation silencieuse** des données ; pas de downgrade d'une violation critique en warning.
- [ ] **Offline** : la chaîne critique s'exécute sans réseau sortant (si applicable).
- [ ] Aucune revendication causale pour une simulation.

## Preuves d'exécution (coller les commandes ET leurs sorties)
```
# ex. ruff check <fichiers>            -> All checks passed!
# ex. mypy --strict <module>          -> Success: no issues found
# ex. pytest <tests> --cov ...        -> N passed, coverage X%
```

## Rollback / impact
- Migration de schéma ? oui / non — si oui, plan de restauration :
- Rollback : comment revenir à l'état N-1 :

## Revue AAA
- [ ] Head of Engineering : GO / GO-WITH-CHANGES (traité) / NO-GO
- [ ] Head of Product : GO / …
- [ ] Head of ML (si ML/données/world model) : GO / …
- Findings bloquants traités : oui / n/a

## Blockers & prochaine tâche débloquée
<!-- Blockers explicites, et le(s) ticket(s) que cette PR débloque. -->
