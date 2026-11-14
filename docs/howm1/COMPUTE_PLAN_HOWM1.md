# HOWM-1 — Plan de calcul R0+R1 : pilote, devis, enveloppe, étapes reprenables

**Statut :** devis proposé, **non approuvé**. Aucune durée ci-dessous n'est mesurée : ce sont
des estimations d'ingénierie. Le pilote R1.PILOT les remplace par des mesures avant toute
étape longue.

## 1. Ressources observées

Inventaire du 14 novembre 2026, voir `INPUT_PROVENANCE.json`.

| Ressource | Observé | Conséquence |
|---|---|---|
| CPU | 4 cœurs logiques | entraînement CPU seulement ; petits modèles |
| Mémoire | 16 Go | suffisante pour les tailles visées (< 1 M paramètres) |
| GPU | aucun | aucun GPU ; aucun GPU payant proposé |
| Disque | ≈ 29 Go disponibles annoncés ; allocation par session fixe | corpus hors dépôt (manifeste haché) ; checkpoints F1 versionnés |
| Python | 3.11.18 (venv P5) ; 3.13.18 (système) | nouveau venv dédié HOWM-1, le venv P5 et son couple D14 ne sont pas modifiés |
| Bibliothèques | numpy 2.4.6, scipy 1.17.1, scikit-learn 1.8.0, pydantic 2.14.3 ; **torch, lightning, jax absents** | B0 faisable sans installation ; B2 et H1 exigent une bibliothèque de différentiation automatique |
| Durée d'une commande au premier plan | 600 s au maximum dans cet outil | plafond proposé 540 s par commande ; entraînement découpé en segments reprenables |
| Exécution asynchrone | non disponible sous le mandat : aucun processus en arrière-plan | la tranche avance commande par commande ; la session doit rester active |
| Persistance | conteneur éphémère, recyclé après inactivité | sans push, un travail non sauvegardé peut être perdu (§ 6) |

## 2. Distinguer les coûts

| Nature | Ce que je peux dire |
|---|---|
| **Dépense monétaire déclenchée par la tranche** | 0 € : pas de GPU loué, pas d'API payante, pas de service externe |
| **Temps CPU du conteneur** | mesuré au registre HOWM-1, en secondes murales ; plafond proposé § 4 |
| **Crédits de l'assistant** (Claude Code) | consommés par l'écriture du code et par chaque commande ; je **ne peux pas** les mesurer ni les convertir en euros. Ordre de grandeur : 250 à 400 appels d'outils sur plusieurs tours, dont la majorité pour écrire le monde, les modèles et les tests |
| **Réseau** | une seule installation (torch CPU), soumise à l'accord de la tranche (§ 3) |

## 3. Environnement d'exécution proposé

- Nouveau venv `venv_howm` en Python 3.11.18, dans le scratchpad comme le venv P5. Il est
  reconstructible depuis son fichier de gel.
- Paquets : **torch 2.4.1, version CPU**, cohérent avec la contrainte du dépôt
  `torch>=2.3.1,<2.5.0`, plus numpy, scipy, pydantic et pytest aux versions du gel D14.
- Après installation, le couple (Python, empreinte du gel) est consigné et devient le seul couple
  accepté par l'exécuteur HOWM-1, comme D14 l'a fait pour P5.

**Inconnue qui change le plan (U1) : le chemin d'installation de torch.**

| Option | Taille approximative | Condition | Recommandation |
|---|---|---|---|
| A. Index CPU officiel (`download.pytorch.org/whl/cpu`) | ≈ 0,2 Go | l'hôte doit être autorisé par la politique réseau de l'environnement ; je ne l'ai pas sondé | **recommandée** |
| B. PyPI standard | ≈ 3 Go avec les dépendances CUDA inutiles ici | registres de paquets autorisés par défaut | acceptable si A est bloquée |
| C. Pas d'installation : B2 et H1 en numpy avec gradients écrits à la main | 0 | aucune | **dégradée** : modèles plus petits, risque d'erreur de gradient, délai d'écriture élevé ; à n'utiliser que si A et B sont refusées |

Si A échoue sur un refus réseau, je n'élargis pas la politique moi-même. Je passe à B si elle
est couverte par l'accord ; sinon je m'arrête et le signale.

## 4. Enveloppe proposée et plafonds par lot

Registre **neuf** `evidence/howm1/BUDGET_LEDGER_HOWM1.jsonl` :
- chaîné et ancré ;
- exécuteur dérivé de `scripts/p5_budget_run.py` ;
- **aucun reliquat P5 ni P0–P4 transféré**.

Plafond total : **21 600 s (6 h) de temps mural CPU cumulé**.

Plafonds par commande :
- **540 s** pour les commandes d'installation, de génération, d'entraînement et
  d'évaluation ;
- **120 s** pour les commandes de test.

| Lot | Contenu | Devis bas–haut (s) | Plafond (s) |
|---|---|---:|---:|
| R0.ENV | création du venv, installation torch CPU, gel, couple approuvé | 60–400 | 600 |
| R0.TEST | toutes les exécutions de tests R0 et R1, lint compris | 400–1 000 | 1 200 |
| R0.GEN | G0 (gel), puis génération TRAIN/VAL/DEVTEST/DIAG-DEV (96 établissements × 8 j), branches appariées des instants évalués, G_alt, manifeste | 300–1 000 | 1 200 |
| R0.PRE | précontrôle C_pub-snap/C_param/C_full/oracle sur VAL (12 établissements × 4 instants × 16 candidats) | 300–1 000 | 1 200 |
| R1.PILOT | construction, comptes exacts, 50 pas chronométrés par modèle, mémoire, test de reprise T-CKPT-02, étiquettes permutées T-INF-08, projection | 200–700 | 900 |
| R1.B0 | estimation par vraisemblance (B0-pool) et rétrécissement (B0-local) | 30–200 | 300 |
| R1.B2 | 2 taux d'apprentissage × arrêt précoce, puis 3 graines retenues | 600–2 500 | 3 000 |
| R1.H1 | idem pour H1 | 1 800–6 500 | 7 200 |
| R1.F1 | sélection sur VAL, gel F1 (poids, λ, w_k, cibles), sondes privilégiées post-gel | 60–250 | 300 |
| R1.EVAL | lecture **unique** de DEVTEST et DIAG-DEV : prévisions, interventions, décisions par instant, coûts | 900–3 000 | 3 600 |
| R1.REST | reçu de restauration depuis une extraction neuve | 120–450 | 600 |
| RÉSERVE | imprévus, sur décision journalisée | — | 1 500 |
| **Total** | | **≈ 4 800–17 000** | **21 600** |

**Hypothèses du devis, non mesurées :**
- environ 1 000 événements par établissement et par jour, hors soins horaires ;
- un déroulé vrai de 24 h prend 0,03 à 0,1 s ;
- une époque H1 sur 48 établissements × 168 h prend 10 à 60 s sur 4 cœurs ;
- 100 à 300 époques avant arrêt précoce ;
- B2 est 3 à 5 fois moins coûteux que H1.

La largeur de ces fourchettes est la raison du pilote.

## 5. Pilote et échelle de repli, déclarés avant le pilote

Le pilote mesure :
- comptes exacts de paramètres ;
- temps par pas d'entraînement et par époque, pour B2 et H1 ;
- pic mémoire ;
- débit de déroulés (trajectoires/s) et latence du planificateur par instant ;
- temps de génération par établissement ;
- durée des tests ;
- coût d'un checkpoint et d'une reprise.

**Règle de projection.** La durée projetée d'un lot est le temps mesuré par unité × le volume
prévu × 1,25.

Si un lot projeté dépasse son plafond, les paliers ci-dessous s'appliquent **dans l'ordre**,
**à tous les modèles appris de la même façon** :
1. Diagnostic décisionnel réduit : 4 → 2 instants par établissement, M = 16 → 8.
2. TRAIN réduit de 48 à 32 établissements, pour tous les modèles, B0 compris.
3. Graines réduites de 3 à 2 pour B2 et H1. Les ensembles deviennent de 2.
4. **Arrêt** et rapport avec les coûts mesurés. Pas de nouveau plafond implicite.

**Non permis :**
- réduire un seul modèle ;
- retirer B0 ;
- retirer les cas simples ;
- toucher à DEVTEST après G0.

## 6. Étapes reprenables et persistance

| Étape | Point de reprise | Ce qui est versionné (git local) |
|---|---|---|
| R0 code | commit par module (contrat, opérateur, vérificateur, générateur, G_alt, historique, exécuteur) | sources et tests |
| G0 | engagement `COMMITMENT_G0.json` : empreintes du code, des lois, des parts, des graines de chaque partition, dont l'empreinte des graines scellées de RESERVE | engagement, graines sauf RESERVE |
| Corpus | un fichier compressé par établissement ; manifeste des empreintes ; régénérable | manifeste seulement ; corpus hors dépôt, environ 20 Mo |
| Entraînement | checkpoint toutes les ≤ 400 s et à la fin de chaque commande : poids, optimiseur, ordonnanceur, RNG, position, empreintes | dernier et meilleur checkpoint par graine, quelques Mo chacun |
| F1 | `F1.json` : empreintes des checkpoints retenus, λ, w_k, cibles de progrès | F1 et checkpoints retenus |
| Évaluation | un fichier de résultats par établissement ; reprise par établissement manquant | résultats et analyse |
| Restauration | `RESTORE_RECEIPT_R1.json` | reçu |

**Risque de persistance (U4).** Sans push, les commits restent locaux. Si le conteneur est
recyclé, plusieurs heures de calcul peuvent être perdues. La tranche demande donc une décision
explicite (`PROPOSITION_TRANCHE_R0_R1.md`, item P) :
- soit le push vers `origin/claude/hospitalos-auto-first-p0-p4-s2dywn` **uniquement aux points
  d'arrêt** G0, F1 et fin de R1 ;
- soit aucun push, en acceptant ce risque.

Le comportement par défaut, si rien n'est dit, est **aucun push**.

## 7. Ce qui n'est pas dans l'enveloppe

- Toute lecture de réserve, nouvelle ou P5.
- H2, H3, JEPA, latent stochastique, boucle fermée, 3 unités en entraînement, courbes d'échelle.
- Tout GPU, toute API payante, toute donnée réelle.
- Une seconde installation.
- Un dépassement de plafond, qui demanderait une décision distincte, motivée par les mesures.
