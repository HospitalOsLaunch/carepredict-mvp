# MVP hybride HospitalOS — socle et parcours libérer → attribuer

Décision : 24 octobre 2026. Statut : prototype local sur scénarios fictifs,
à relire en PR. Aucune mesure d'efficacité hospitalière réelle.

## Problème traité

Un lit vide peut être inutilisable faute de nettoyage, de compatibilité ou de
capacité soignante. Une recommandation ne doit pas confondre disponibilité
estimée et précondition confirmée, ni être exécutée après changement de l'état.

Cette tranche relie les faits horodatés, la simulation sous hypothèses, le choix
d'une action immédiate et un workflow d'approbation persistant. Elle réutilise
les conventions UTC, identifiants et modèles fermés du contrat opérationnel.
Les observations agrégées OPERATIONAL_V2 ne permettent pas de déduire des
identités, compatibilités ou lits individuels : HYBRID_MVP_2 est une extension
explicite nécessitant un flux patient/ressource distinct.

## Exécuter

Python 3.11+, Pydantic 2. Démonstrateur sans PyTorch, TFT, JEPA ou réseau :

```bash
PYTHONPATH=src python -m hospitalos.hybrid --demo
PYTHONPATH=src python -m hospitalos.hybrid --demo --show-input > /tmp/hybrid-input.json
PYTHONPATH=src python -m hospitalos.hybrid --request /tmp/hybrid-input.json
```

API locale séparée (FastAPI/Uvicorn sont déjà dans les dépendances du dépôt) :

```bash
PYTHONPATH=src:. uvicorn services.api.hybrid_app:app --host 127.0.0.1 --port 8010
curl -H 'Content-Type: application/json' --data-binary @/tmp/hybrid-input.json \
  http://127.0.0.1:8010/hybrid/plan
```

Les résultats sont étiquetés `simulation_under_declared_assumptions`. Les entrées
déclarent `synthetic_hypothesis`. La sortie expose chaque candidat, le coût moyen
et le coût du pire décile de scénarios, les avertissements, le budget de recherche
et son éventuelle troncature. Ces statistiques ne sont pas des intervalles calibrés.

## Périmètre livré

- Journal SQLite à ajouts seuls, identité/version contrôlées et lecture par hôpital.
- Reconstitution à D via `event_time` ET `available_at`. Une correction reçue
  après D ne modifie pas l'état connu à D. Les sources contradictoires ou périmées
  entraînent l'abstention, sans remplacement par zéro ou vérité synthétique.
- Manifeste explicite des entités attendues. Sa complétude doit être établie par
  le connecteur ; le prototype ne découvre pas des patients absents de tous les flux.
- Lits, patients, compatibilités attestées, réservations, capacité soignante agrégée
  et équipes de nettoyage. La priorité patient est donnée par le métier.
- Trois actions : réserver un lit propre compatible, prioriser le nettoyage d'un
  lit sale, demander un transport dont les prérequis sont confirmés ; plus la
  référence sans intervention. Aucune décision clinique.
- Simulation événementielle d'une cohorte fermée : autorisation médicale et
  logistique attestées, préparation, aval fini et transport partagé si nécessaires,
  départ, nettoyage puis admission. Le contrat détaillé et ses limites sont dans
  [le lot libérer → attribuer](release-allocate.md).
- Innovations aléatoires indexées par graine/scénario/mécanisme/entité, et facteur
  commun de ralentissement. Les plans partagent les mêmes innovations ; les
  événements endogènes changent avec l'ordre de nettoyage et les affectations.
- Notateur séparé du moteur, qui reconstruit le parcours à partir du journal et
  contrôle les admissions, départs, ressources et conservation des patients.
- Approbation/refus, expiration après 15 minutes, recontrôle de fraîcheur et
  empreinte juste avant émission. État `sent` persisté avant retour de commande.
  Résultat `unknown` : réconciliation obligatoire, jamais de retry automatique.

La démonstration contient deux lits sales et un patient nécessitant de l'oxygène.
Changer l'ordre de nettoyage peut réduire son attente dans ce scénario. Les durées
de nettoyage ne deviennent pas artificiellement plus courtes sous intervention.

## Choix de solveur pour cette tranche

La recommandation cible CP-SAT/MILP reste la trajectoire pour les plans combinés.
Cette première version énumère les actions immédiates admissibles, dans une limite
explicite de 32 candidats, puis les évalue sur les mêmes scénarios. Le meilleur
candidat est sélectionné selon `(1-w)*attente_moyenne + w*pire_décile`, avec `w`
déclaré. L'inaction gagne les égalités. Le coût est mesuré en patients-minutes
d'attente depuis D, pas en taux d'occupation ni en efficacité économique.

C'est une optimisation sur ce catalogue borné, pas une planification multistade
ni un optimum global de l'hôpital. Le moteur de compatibilité reste indépendant
du simulateur et doit être réutilisé lors du futur raccordement CP-SAT.

## Workflow de validation sandbox

```python
from hospitalos.hybrid.demo import demo_request
from hospitalos.hybrid.planning import plan
from hospitalos.hybrid.workflow import Workflow

request = demo_request()
proposal = plan(request)
workflow = Workflow('/tmp/hospitalos-sandbox.sqlite')
workflow.propose(proposal)
workflow.approve(proposal.plan_id, request.state(), request.at, 'demo-reviewer')
command = workflow.dispatch(proposal.plan_id, request.state(), request.at)
# command décrit une commande sandbox. Aucun logiciel hospitalier n'est modifié.
workflow.outcome(proposal.plan_id, request.at, 'demo-operator', 'unknown', 'timeout-test')
# Une seconde émission est refusée, y compris après redémarrage.
workflow.outcome(proposal.plan_id, request.at, 'demo-operator', 'confirmed', 'sandbox-readback')
workflow.close()
```

Les noms d'acteurs sont des métadonnées de test, pas une authentification. La
confirmation ci-dessus est une déclaration sandbox, pas une vérification d'un DPI.
L'API expose seulement la planification, aucun endpoint d'exécution. Ne pas
exposer ce serveur hors loopback sans authentification, limites de requête,
isolation des établissements et politique de conservation des données.

## Limites et prochaines tranches

1. **Données et incertitude** : durées discrètes hypothétiques, pas de modèle de
   survie entraîné ni calibration. Ajouter les distributions empiriques/survie
   après contrat et données adaptés, avec censure et séparation temporelle.
2. **Dynamique** : aucune nouvelle arrivée après D, pas de transfert entre lits,
   de durée de séjour des nouveaux admis, ni de travail de nettoyage déjà en cours
   à D. Les lits dont l'état n'est pas représentable doivent être marqués inconnus.
   Les sorties autorisées ne sont pas décidées ou accélérées médicalement.
3. **Ressources** : capacité soignante agrégée attestée, pas de simulation fine
   des compétences, ratios ou fatigue. Le transport et l'aval sont des pools
   résiduels attestés à D, sans réservations préexistantes ni services en cours
   dans la cohorte. Ajouter ces cas avant raccordement à un flux réel.
4. **Boucle opérationnelle** : chaque demande replanifie depuis un nouvel état ;
   pas de polling autonome ni raccordement à un SI. Le gateway est sandbox.
5. **Évaluation** : notateur distinct mais même famille de simulation pour
   sélectionner les plans. Aucun gain hors mécanismes ni causalité réelle établi.
   Ajouter régimes/mécanismes réservés, scénarios de faible adhésion, observation
   réelle sans action, puis évaluation prospective assistée.
6. **Stockage** : SQLite local pour la tranche ; avant exploitation, adapter les
   journaux à PostgreSQL, permissions, rétention, sauvegardes et accès concurrents.

Les anciens TFT/RSSM et les preuves figées restent des chemins de recherche
distincts. Cette tranche ne change ni leur comportement ni le périmètre Nantes.

## Vérification reproductible

```bash
PYTHONPATH=src:. pytest -q tests/hybrid
ruff check src/hospitalos/hybrid services/api/hybrid_app.py tests/hybrid
ruff format --check src/hospitalos/hybrid services/api/hybrid_app.py tests/hybrid
PYTHONPATH=src:. mypy --strict src/hospitalos/hybrid services/api/hybrid_app.py tests/hybrid
```

Les tests ciblent la fuite du futur, les corrections, les contradictions,
l'absence de données, la surcharge observée, les réservations, les limites de
ressources, la conservation, la reproductibilité, les budgets et la reprise
après résultat inconnu. Un passage de tests ne constitue pas une validation réelle.
