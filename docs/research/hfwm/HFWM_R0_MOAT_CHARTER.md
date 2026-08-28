# HFWM-R0 — MOAT Charter

Version du document : `hfwm-r0.moat-charter.v1`  
Baseline de code : `HospitalOsLaunch/carepredict-mvp@06914578a4e88257ecf44e7fede72a20852f443a`  
État : `PREREGISTRATION_FROZEN — INTERNAL_SYNTHETIC_MAIN_RUNS_AUTHORIZED`

## Question et hypothèse pré-enregistrées

Question primaire : à information réellement disponible au temps `t`, un état latent hiérarchique, partagé et conscient du processus d’enregistrement permet-il de prédire des trajectoires opérationnelles jointes, de rester cohérent en rollout libre et de s’adapter à un site non vu avec moins de données qu’un modèle local ?

Hypothèses secondaires bornées :

1. le pré-entraînement partagé améliore l’efficacité d’adaptation locale ;
2. une dynamique jointe respecte mieux les contraintes qu’un ensemble de forecasters indépendants ;
3. un modèle du processus d’observation améliore la robustesse aux retards, corrections, données manquantes et sources silencieuses.

Aucune autre thèse majeure ne peut entrer dans R0 sans décision humaine et nouvelle version reliée à ce document.

## Périmètre scientifique

HFWM-R0 représente séparément le belief state `S_t`, les observations disponibles `O_t`, le processus d’enregistrement `R_t`, les actions observées `A_t`, le contexte disponible `C_t` et la hiérarchie hospitalière `H_t`. Les prédictions sont rétrospectives, point-in-time et observationnelles.

Le premier bake-off est limité à trois familles :

1. une dynamique mécanistique explicite de type file/conservation/semi-Markov légère ;
2. une dynamique apprise localement from scratch, sans pré-entraînement partagé ;
3. un candidat HFWM partagé, multi-tâche et hiérarchique.

Les trois familles utilisent les mêmes snapshots, partitions, tâches, horizons et métriques gelés. Les architectures restent interchangeables derrière les contrats de `src/hfwm/contracts`. JEPA, RSSM, Transformer, SSM, graph model, diffusion, DES et semi-Markov sont des options, pas des exigences.

## Actifs du MOAT

- **HTL** : sémantique hospitalière commune versionnée, séparée des mappings locaux par site.
- **HDC** : épisodes point-in-time reproductibles, liés au ledger et dotés d’un hash sémantique stable.
- **DOS** : décisions et outcomes séparant options, exposition, choix, intention et exécution observée.
- **HDB** : benchmark privé versionné, splitté avant fenêtrage, avec holdouts et contrôles anti-contamination.
- **SAS** : mapping local, calibration, adaptation low-shot, backbone gelé et contrôle from-scratch au même budget.

La propriété d’un actif n’est revendiquée que lorsque ses données et dérivés sont explicitement autorisés. Un poids de modèle seul ne constitue pas le MOAT.

## Règles de vérité et de droits

- Toute observation utilisée par un snapshot `as_of=t` doit satisfaire `available_at <= t`.
- Une correction ajoute un événement ; elle ne réécrit pas silencieusement l’historique.
- Les splits suivent `organisation → établissement → unité → épisode → temps → fenêtres`.
- Une source non déclarée ou aux droits incomplets est refusée par défaut.
- Les données agrégées ne sont pas présentées comme des trajectoires d’unité.
- Aucune donnée nominative, aucun secret et aucun identifiant sensible ne sont admis.
- Aucune donnée hospitalière n’est transmise à un service externe non autorisé.

La fixture `hfwm_r0_internal_synthetic_fixture`, créée de première main dans cette mission sans donnée externe, est autorisée uniquement pour les entraînements, évaluations et benchmarks locaux HFWM-R0. La publication, la redistribution et la persistance de poids restent interdites. Toutes les autres sources inventoriées demeurent refusées. Cette autorisation bornée permet les runs principaux synthétiques ; elle ne prouve ni propriété intellectuelle définitive, ni validité externe, ni disponibilité de données Nantes.

## Actions et décisions

La branche action-conditionnée est séparée de la question primaire. Les données inspectées ne prouvent pas encore l’exécution avec type, scope, dose, timing, déviation, actions concurrentes et support suffisants. Son statut pré-enregistré est donc :

```text
ACTION_CONDITIONING_NOT_IDENTIFIABLE
```

Une intention, prescription, recommandation ou ouverture d’écran ne vaut jamais preuve d’exécution. Aucun rollout observationnel ne peut servir à classer une action comme meilleure et aucun claim causal n’est autorisé.

## Transfert et Foundation

R0 ne dispose pas de preuves portant sur trois organisations indépendantes, un établissement intégralement non vu et une adaptation à budget local gelé face au même backbone from scratch. Le statut obligatoire est :

```text
FOUNDATION_EVIDENCE_INSUFFICIENT
```

`Foundation` reste une ambition architecturale, pas un résultat.

## Claims

Claims éventuellement autorisables après leurs gates respectifs :

```text
EXPERIMENTAL_HOSPITAL_WORLD_MODEL
HOSPITAL_WORLD_MODEL_CANDIDATE
FOUNDATION_ARCHITECTURE_CANDIDATE
BEHAVIOR_CONDITIONED_DYNAMICS_MODEL
OBSERVATIONAL
SHADOW_ONLY
UNVALIDATED_AT_NANTES
```

Claims interdits dans R0 sans gate humain dédié :

```text
VALIDATED_WORLD_MODEL
PROVEN_FOUNDATION_MODEL
VALIDATED_AT_NANTES
CAUSAL_EFFECT
COUNTERFACTUAL_EFFECT
BEST_ACTION
PROVEN_OPERATIONAL_IMPACT
AUTONOMOUS_EXECUTION
CERTIFIED
GUARANTEED
FIRST_OR_UNIQUE
```

## Autorité et évolution

Les seuils, partitions, budgets et métriques deviennent immuables pour un run principal après gel des documents de bake-off associés. Une modification postérieure crée une nouvelle version liée à l’ancienne ; elle ne réécrit pas la pré-inscription. Les résultats insuffisamment puissants sont `INCONCLUSIVE`, jamais un PASS.

Aucun agent ne peut prononcer un PASS humain, une validation Nantes, une preuve causale, une preuve de Foundation Model ou une autorisation d’exécution.
