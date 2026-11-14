# HOWM-1 — Résumé de préparation : réutilisable, inconnues, écarts au programme

## 1. Points d'architecture réutilisables

Ils ont été vérifiés dans le dépôt, avec les empreintes de `INPUT_PROVENANCE.json`.

| Source | Ce qui est repris | Comment |
|---|---|---|
| `decision_support/contracts.py`, `clock.py` | UTC partout, résolution civile Europe/Paris explicite, `None` = inconnu, modèles Pydantic fermés | conventions du nouveau contrat `HOWM1_EVENTS_1` |
| `decision_support/snapshot.py` | filtre `event_time ≤ t ∧ available_at ≤ t`, dernière version par (type, sujet), manques explicites | patron du constructeur unique `howm.history.build` |
| `decision_support/eligibility.py` | sortie automatique seulement pour une autorisation publiée ; jamais de décision médicale ; verrous manuels soumis aux mêmes préconditions | sémantique des préconditions de l'opérateur ; importé en lecture seule là où les types le permettent |
| `decision_support/resources.py` | couverture par compétence et par heure avec présence simultanée ; capacité par prêteur × compétence × heure (V5-R01) | règles de l'opérateur et du vérificateur |
| `decision_support/reference_forecaster.py` | vérificateur d'invariants indépendant du simulateur ; `PrivateTruth` séparée ; `check_isolation` à deux vérités ; refus des fournisseurs `reads_private` | T-OP-12, T-INF-03, T-INF-09 |
| `decision_support/planner.py` | auto et manuel sur un seul cœur ; verrous = contraintes ; hypothèse non autorisée non approuvable | même principe pour le planificateur HOWM ; v6 reste la référence V0 |
| `hybrid/innovations.py` | tirages indexés par clé SHA-256, indépendants de l'ordre | importé tel quel pour le générateur |
| `p5/generator.py`, `truth.py` | jumeaux par permutation, réalisations privées R1/R2 partageant les innovations, unicité `offer_key` | patrons pour les branches appariées et l'unicité des offres |
| `p5/pilot.py`, `integrity.py`, `scripts/p5_budget_run.py` | identité de run immuable, reçus d'arrêt, engagements successifs, couple (Python, gel) contrôlé, registre chaîné | exécuteur et registre HOWM-1 **neufs**, dérivés de ce code |
| `operational/contract.py`, `forecast.py` | contrat daté avec manques explicites ; petit prévisionniste à poids partagés entre nœuds (6 755 paramètres, lot 15) | antériorité de conception seulement ; non exécuté, non prolongé |
| `dynamics/jepa_rssm.py` | RSSM sur plongements TS-JEPA | référence de code pour une future variation de latent stochastique (R2) ; poids non chargés |

**Non réutilisé :**
- le cockpit, qui n'est pas reconstruit ;
- les graines P5 ;
- le registre P5 ;
- les poids antérieurs (`rssm_checkpoint.pt`, lots 15/16), hachés comme octets seulement ;
- A_detached et les lots B/C, hors mandat. A_detached est authentifié à 2000 ; son final 6000
  n'est pas attesté, ce qui n'est pas un échec scientifique.

## 2. Inconnues qui changent réellement l'expérience

| ID | Inconnue | Ce qu'elle change | Comment elle se résout |
|---|---|---|---|
| U1 | Chemin d'installation de torch : hôte de l'index CPU autorisé ou non | faisabilité de B2/H1 ; ≈ 0,2 Go ou ≈ 3 Go ; repli numpy dégradé | accord de la tranche (option A, B ou C), puis R0.ENV |
| U2 | Débit CPU réel pour H1 sur 4 cœurs : facteur ≈ 6 d'incertitude dans le devis | volumes, nombre de graines, nombre d'instants | pilote R1.PILOT et échelle de repli déclarée |
| U3 | Marge décisionnelle de la population REF (V_param + V_latent) | si elle est faible, la comparaison décisionnelle de R1 sur REF est non informative ; la comparaison prédictive reste | précontrôle R0.PRE, avant tout modèle appris ; aucune retouche du générateur |
| U4 | Persistance sans push dans un conteneur éphémère | perte possible d'heures de calcul | décision P (push aux points d'arrêt seulement, ou aucun) |
| U5 | Poids de l'objectif U et seuil δ_dec | choix des plans et lecture du diagnostic décisionnel ; pas les prévisions | fixés avant G0 et avant le précontrôle, jamais après lecture |
| U6 | Réalisme des mécanismes m0–m5 | portée de tout résultat : rien n'est calibré sur un hôpital | chantier réel parallèle (programme § 11) ; hors tranche |
| U7 | DIAG en entraînement ou seulement en évaluation | ce que DIAG-DEV mesure : apprentissage ou robustesse à des mécanismes non vus | proposition : évaluation seulement en R1 |

Les autres valeurs à fixer (tailles, instants, patience, M, fréquence des checkpoints) ont des
propositions déclarées dans `EXPERIMENT_HOWM1_R0_R1.json`. Elles changent les coûts plus que la
question posée.

## 3. Écarts assumés au programme, et pourquoi

1. **Pas de latent stochastique en R1.** Mémoire déterministe, têtes probabilistes et
   ensemble de 3 graines. Le programme demande « une variation à la fois ». Le latent
   stochastique est la première variation candidate en R2. Limite nommée dans le document de
   conception (§ 3).
2. **Diagnostic décisionnel par instant**, pas en boucle fermée. La boucle fermée est R3 dans
   le programme.
3. **B0 en deux versions** (commune et locale). Le programme exige un simulateur calibré sur
   les mêmes données ; B0-local reçoit exactement la même fenêtre publique que les modèles
   appris, pour ne pas cacher d'information à la référence.
4. **Aucune réserve lue en R1.** Le point d'arrêt du programme est la livraison des poids et
   des résultats de **développement**. La réserve neuve est scellée en G0 ; sa lecture
   demandera un protocole distinct.
