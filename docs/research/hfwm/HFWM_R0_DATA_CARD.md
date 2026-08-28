# HFWM-R0 — Data Card

Version : `hfwm-r0.data-card.v1`  
État : `SYNTHETIC_CORPUS_BUILT — INTERNAL_SYNTHETIC_MAIN_RUNS_AUTHORIZED`

## Usage prévu

Le Hospital Dynamics Corpus (HDC) doit produire des épisodes rétrospectifs point-in-time pour l’estimation d’état, la dynamique jointe, les événements, le time-to-event, l’occupation, les flux, le staffing, la tension, l’anomalie et le scoring de trajectoire. Il ne sert ni à estimer un effet causal, ni à choisir une meilleure action, ni à exécuter une action.

## Unité d’observation

Un épisode HDC relie :

```text
historique disponible au cutoff
→ référence de belief state
→ futur conjoint observé
→ contexte
→ décisions/actions seulement si observables
→ outcomes
→ provenance du ledger
→ partition HDB
```

Le contrat `hdc.episode.v1` porte un `snapshot_hash`, un `htl_registry_hash`, les identifiants d’événements source, la version du code de build, les versions de schéma et le cutoff `as_of`. Son hash sémantique utilise le JSON canonique local et SHA-256.

## Point-in-time et corrections

- `event_time` décrit le fait ;
- `recorded_at` décrit la saisie source ;
- `available_at` décrit le premier instant où HospitalOS pouvait connaître le fait ;
- `ingested_at` décrit l’entrée dans HospitalOS ;
- un snapshot exclut tout événement avec `available_at > as_of` ;
- une correction ajoute un nouvel événement lié à l’original ;
- les timezones sont explicites ;
- l’ordre de replay est déterministe.

Le P-0D local matérialise ces invariants et le corpus synthétique par défaut est reproductible en mémoire. Aucun épisode réel n’est revendiqué par ce document.

## Hiérarchie, splits et contamination

La séparation précède le fenêtrage et suit :

```text
organisation → établissement → unité → épisode → temps → fenêtres
```

Les partitions doivent conserver les sources, périodes, sites, unités, hashes sémantiques, règles de déduplication, gaps temporels, transformations, versions de code/schéma et exposition éventuelle à un checkpoint externe. Les corrections quasi identiques et les fenêtres d’un même épisode ne peuvent traverser train et test.

Les règles de partition, cohortes et fenêtres sont gelées dans `HFWM_R0_SPLITS.yaml` ; le contrat HDB refuse `split_before_windowing=false`.

## Processus d’observation

Le corpus doit exposer fréquence de saisie, retards, corrections, sources silencieuses, changements de SI/codage, missingness, fraîcheur et fiabilité par source. Le modèle d’observation est séparé de la dynamique hospitalière.

## Sources inventoriées

| Source candidate | Granularité démontrée | Droits vérifiés dans la baseline | Décision R0 |
|---|---|---:|---|
| fixture synthétique HFWM-R0 interne | pseudo-trajectoires horaires d’unités, sans donnée externe | autorisation de mission bornée | autorisée pour train/eval/benchmark locaux uniquement |
| DREES agrégé | agrégat, pas trajectoire d’unité | non | refusée |
| générateur synthétique CarePredict | synthétique ; provenance/licence à établir | non | refusée |
| Synthea | source/version/licence non figées localement | non | refusée |
| MIMIC-IV | accès sous DUA ; autorisation de dérivés non démontrée | non | refusée |
| données partenaire/site | aucune autorisation jointe | non | refusée |

Une source agrégée ne sera jamais présentée comme une trajectoire d’unité. Hormis la fixture synthétique interne explicitement bornée, les sources ci-dessus restent interdites jusqu’à une révision étayée de `HFWM_R0_DATA_RIGHTS.yaml`.

## Corpus synthétique gelé

Le profil par défaut produit 25 680 événements P-0D, 60 épisodes, 240 fenêtres, 60 corrections append-only et 60 intervalles silencieux. Les partitions contiennent 42/9/9 épisodes train/validation/test. Son build de référence en mémoire a donné le hash `edc3b9e357d766d590e31bd7dec88069362a08091519482ffc122068b47045ed`. Les trois pseudo-organisations sont des scénarios synthétiques, pas des organisations indépendantes réelles.

## Actions et décisions

Le DOS conserve séparément options, information exposée, ouverture, choix humain, motif, exécution, dose, timing, déviation, actions concurrentes, outcome, support et incertitude. Le contrat refuse de joindre des détails d’exécution à un statut `not_observed` ou `intention_only`.

État courant : `ACTION_CONDITIONING_NOT_IDENTIFIABLE`. Les décisions humaines sont des observations comportementales et non une ground truth optimale.

## Données sensibles

Sont interdits : données nominatives, secrets, identifiants sensibles, upload vers un service externe non autorisé et publication de données ou dérivés sans droit explicite. Les identifiants du corpus devront être des identifiants techniques non directement identifiants et contrôlés par la politique de droits.

## Limites connues

- aucune donnée hospitalière réelle ni Nantes ;
- propriété intellectuelle externe de la fixture encore à confirmer avant publication ;
- aucune mesure de validité externe ;
- aucun gate multi-organisation ;
- aucune preuve d’exécution d’action ;
- aucun claim causal, Nantes, Foundation ou impact opérationnel.
