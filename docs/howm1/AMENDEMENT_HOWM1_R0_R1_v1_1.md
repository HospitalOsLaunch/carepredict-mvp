# HOWM-1 — Amendement v1.1 de la préparation R0+R1 (clarifications après revue)

**Date :** 14 novembre 2026.
**Statut :** proposition, **NON APPROUVÉE**. Aucune installation, génération, aucun
entraînement, test produit, chargement de poids, lecture de réserve ni push.

**Origine.** Revue « HospitalOS_Revue_Proposition_HOWM1_R0_R1_20261114 », points 2 à 6 du
complément demandé.

**Originaux v1 conservés à l'identique**, avec leurs empreintes dans
`MANIFESTE_COMPLETUDE_v1_1.json`. Ce document **prévaut** sur les passages v1 qu'il cite.
`EXPERIMENT_HOWM1_R0_R1_v1_1.json` reprend v1 avec ces changements. Rien d'autre n'est modifié.

## A1. Score prédictif : conventions complètes (revue § 3.1)

**Changement :**
- la cible « NLL de H1 inférieure d'au moins 10 % » (proposition v1, item 5) est **retirée** ;
- la tête « besoin de soins » est **évaluée sur une grille discrète**. Sa paramétrisation
  log-normale est conservée pour l'entraînement (conception v1, § 2.2).

### A1.1 Score logarithmique apparié (critère prédictif principal)

**Supports, tous discrets :**
- probabilité d'un intervalle, sans densité continue ;
- aucune constante additive ;
- unité : nats par élément évalué.

| Famille f | Élément évalué à l'origine t, horizon h | Support | Loi prédictive |
|---|---|---|---|
| départ | chaque séjour publiquement autorisé, présent à t | intervalle de 15 min de l'événement observé dans (t, t+h], sinon censure S(h) | hazard discret (conception § 2.2) |
| transport | chaque transport demandé, non terminé à t | idem | idem |
| nettoyage | chaque lit en attente ou en cours de nettoyage à t | idem | idem |
| confirmation | chaque demande ou offre en attente de réponse à t | idem | idem |
| présence du renfort | chaque offre acceptée dont le créneau débute dans (t, t+h] | {présent, absent} | Bernoulli |
| arrivées | chaque unité × heure j ∈ (t, t+h] | entier ≥ 0 | binomiale négative |
| soins | chaque séjour présent à t et observé présent à l'heure j ∈ (t, t+h], × compétence | intervalles de 5 min, [0, 5), [5, 10), …, dernier intervalle ouvert à droite | P(intervalle) de la log-normale tronquée |

**Construction :**
- L'ensemble des éléments est fixé par l'état **public** à t. Il est identique pour tous les
  modèles, ce qui est vérifié par empreinte (nouveau test T-PLAN-07).
- Pour une origine t, chaque modèle donne sa loi prédictive sachant `I_public_W(t)` :
  - B0 : analytique ;
  - B2 et H1 : têtes appliquées à z_t, ou à z propagé sans observation pour les heures j > t
    (mode « marginal latent », conception § 2.3).
- Origines : toutes les heures des jours 2 à 6 de chaque établissement évalué.

**Agrégation :**
- L̄(m, e, f, h) = moyenne des −log p sur les éléments de la famille f de l'établissement e.
- L(m, e, h) = moyenne **non pondérée** de L̄ sur les 7 familles. Une famille sans élément est
  exclue pour cet établissement, et ce cas est rapporté.
- **Δ_LS(h) = moyenne sur e de [L(B0-local, e, h) − L(H1, e, h)]**, avec un poids égal par
  établissement. Δ_LS est une différence **appariée**, en nats par élément ; il ne s'exprime pas
  en pourcentage.

**Critère statistique principal :**
- borne basse de l'IC à 95 % de Δ_LS(6) > 0 **et** de Δ_LS(24) > 0 ;
- bootstrap par grappes : établissements rééchantillonnés, instants et fenêtres emboîtés ;
- graine du bootstrap engagée en G0.

Les autres paires (B2−H1, B0-pool−B0-local, B0-local−B2) et H1 sont rapportées de façon
descriptive.

### A1.2 CRPS relatif sur trajectoires (ambition d'ingénierie, secondaire)

- **Cibles horaires par unité à t+h, h ∈ {1, 6, 24} :**
  - occupation ;
  - lits compatibles libres ;
  - file de transport ;
  - file de nettoyage ;
  - minutes de soins demandées par compétence.
- CRPS estimé sans biais à partir des M = 16 déroulés (mode 1), mêmes graines d'échantillonnage
  pour tous les modèles. Score non négatif, en unités métier.
- **Normalisation :** chaque cible est divisée par son écart-type s_c, calculé **sur TRAIN
  seulement**. La règle est fixée ici ; la valeur est calculée après génération de TRAIN et
  avant tout entraînement, puis journalisée.
- **R(h) = 1 − Σ_e C̄(H1, e, h) / Σ_e C̄(B0-local, e, h)**, où C̄ est la moyenne par établissement
  des CRPS normalisés. C'est un ratio de sommes, à poids égal par établissement.
- **Ambition, ponctuelle :** R(6) ≥ 0,10 et R(24) ≥ 0,10.
- **Lecture statistique :** borne basse de l'IC à 95 % de R(h) > 0.
- **Libellés imposés au rapport :**
  - « ambition atteinte (estimation ponctuelle) » ;
  - « gain positif (borne basse > 0) ».
  - « gain d'au moins 10 % démontré » ne peut être écrit que si la borne basse est ≥ 0,10. Ce
    n'est **pas** une cible adoptée.

### A1.3 δ_dec et ambition décisionnelle : deux objets distincts

| Objet | Définition | Rôle |
|---|---|---|
| **δ_dec = 15** minutes-soignant par instant | seuil sur la **marge accessible** V_param + V_latent (moyenne par instant sur VAL), mesurée **avec les seuls contrôleurs privilégiés** en R0 | décide **avant tout modèle appris** si la comparaison décisionnelle de R1 sur REF est informative. Ce n'est pas un critère de réussite d'un modèle |
| **Ambition décisionnelle = 5** minutes-soignant par instant | D_dec = moyenne par instant de [regret(B0-local) − regret(H1)] contre C_full, sur DEVTEST REF, sur K_eval réalisations fraîches | lue **seulement si** la marge est informative. Ambition ponctuelle D_dec ≥ 5 ; lecture statistique : borne basse > 0. Mêmes libellés qu'en A1.2 |

5 < 15 est cohérent : un modèle public ne capture pas, en général, toute la marge mesurée avec
une information privilégiée. Si la marge est faible, on ne retire aucun cas facile et l'étude
prédictive (A1.1, A1.2) continue.

## A2. Objectif U-HOWM-1 (fixé ici, donc avant G0)

Pour un instant de décision τ, sur (τ, τ + 24 h], sous la vérité privée réalisée :

**U = Σ_{compétence, heure} minutes de soins non couvertes + 15 × heures-patient d'attente d'un
lit compatible**

- Unités : minutes-soignant et heures-patient.
- Le premier terme reprend le palier 1 d'OBJ-LEX-1 de v6 et la définition de P5 : demande
  moins capacité **présente**, par compétence et par heure, minorée à 0, travail d'admission dû
  compris.
- Le poids 15 par heure d'attente est une **hypothèse d'ingénierie**, non validée. U est aussi
  rapporté avec ce poids à 0, de façon descriptive.

**Sélection du planificateur**, identique pour tous les modèles ; c'est OBJ-LEX-1 de v6 appliqué
à U :
1. E[U] dans une tolérance de 15 minutes autour du meilleur ;
2. puis le moins d'heures de renfort **acceptées** ;
3. puis le moins d'interventions ;
4. puis l'ordre canonique.

Les heures de renfort acceptées et présentes sont rapportées séparément.

## A3. Ordre normatif (revue § 3.2, demande 3)

| Rang | Ce qui est fixé ou exécuté | Avant quoi | Où c'est défini |
|---|---|---|---|
| 1 | U, poids, tolérance ; δ_dec ; ambitions ; scores, supports, agrégations et critères (A1, A2) ; règle de précontrôle ; tailles et mélanges des populations ; M = 16 ; K_eval = 4 ; w_k ; patience et règle de sélection (A4) | **G0** et toute lecture de VAL | ce document ; JSON v1.1 |
| 2 | **G0** : empreintes du code, des lois, des parts, des graines (RESERVE scellée) | génération | conception § 6 |
| 3 | Génération du corpus ; constantes s_c sur TRAIN | précontrôle et entraînement | A1.2 |
| 4 | **Précontrôle** sur VAL, contrôleurs privilégiés seulement, lu une fois, consigné | tout modèle appris | conception § 5.4 |
| 5 | Pilote ; seule l'échelle de repli déclarée peut s'appliquer ; normalisations λ par la règle déterministe | entraînements | plan de calcul § 5 ; conception § 4.1 |
| 6 | Entraînements B2 et H1 : lr choisi sur VAL (graine 0), puis graines 1 et 2 au lr retenu | **F1** | A4 |
| 7 | **F1** : poids, λ, w_k, cibles, empreintes | DEVTEST et DIAG-DEV | conception § 4.4 |
| 8 | Lecture **unique** de DEVTEST et DIAG-DEV ; **aucune** sélection, aucun réglage et aucune retouche du générateur ensuite ; DIAG-DEV ne sert jamais à choisir un modèle | rapport | conception § 6 ; JSON `partitions` |

**Couplage et indépendance**, déjà définis dans la conception (§ 6) et le JSON
(`partitions.unit`, `analysis`) :
- L'**établissement** est le système couplé : ses deux unités, tous ses jours, fenêtres
  chevauchantes, branches et instants restent dans une seule partition.
- Les instants et les fenêtres sont **emboîtés** : seuls les établissements sont rééchantillonnés.
- Les graines d'entraînement forment un ensemble, pas des répétitions indépendantes.
- B0-local, comme tous les comparateurs publics, n'utilise que `I_public_W(t)` à l'origine,
  calibration locale comprise (conception § 3, B0 ; JSON `information_sets`).

## A4. Valeurs techniques fixées maintenant (au lieu de « après pilote » ou « sur VAL »)

- **w_k = 1** pour k ∈ {1, 6, 24}, après normalisation des termes. **Aucun réglage sur VAL.**
  Cela supprime une recherche et donc des entraînements.
- **Patience** : 20 époques sans amélioration de la perte de VAL. Le nombre d'époques est
  borné par le plafond du lot. Checkpoint retenu par graine : meilleure perte de VAL.
- **Choix du lr** dans {3e-4, 1e-3} : plus petite perte de VAL à la graine 0. En cas d'égalité
  à 1e-4 relatif près, le plus petit lr.
- **Fréquence de checkpoint** : toutes les ≤ 400 s et à la fin de chaque commande. C'est une
  valeur technique, inchangée.

## A5. Installation : version, avis de sécurité, route d'accès

**Faits vérifiés le 14 novembre 2026, sans téléchargement de paquet :**

| Fait | Source |
|---|---|
| L'index CPU `download.pytorch.org` est **refusé par le proxy réseau de cet environnement** (403 sur une simple requête d'index). L'option A n'est donc **pas disponible en l'état** | `pip index versions torch --index-url …/whl/cpu` |
| PyPI est accessible. torch **2.15.0** est publié pour cp311 manylinux x86_64 : roue de 539 Mo, déposée le 2026-10-28, `requires_python >= 3.11`. Ses métadonnées déclarent sur Linux des dépendances CUDA : composants `cuda-toolkit` 13.2.2, `nvidia-cudnn-cu13`, `nccl`, `nvshmem`, `cusparselt`, `triton` | API JSON de PyPI (métadonnées) |
| GHSA-53q9-r3pm-6pq6 : affecte ≤ 2.5.1 | revue, S3 |
| GHSA-63cw-57p8-fm3p : affecte ≤ 2.9.1, corrigé ≥ 2.10.0 | page de l'avis, consultée |
| **GHSA-v32g-mr63-3j83** (publié le 10 novembre 2026) : `torch.load(weights_only=True)` permet une lecture arbitraire de fichiers ; affecte **≥ 2.14.0**, corrigé en **2.15.0** | page de l'avis, consultée |

**Version proposée : torch == 2.15.0**, la seule version hors des plages affectées de ces trois
avis.
- Ce constat vaut **pour ces avis**, pas comme garantie globale.
- Le pin 2.4.1 de v1 est **abandonné** : il est affecté par 53q9 et 63cw.
- Le venv HOWM est séparé, donc la contrainte `<2.5.0` de `pyproject.toml` ne s'applique pas.
  Le couple (Python 3.11.18, empreinte du gel) est consigné avant toute exécution HOWM.

**Politique de chargement :**
- `torch.load` seulement sur des checkpoints **produits par la tranche** ;
- empreinte SHA-256 comparée au registre **avant** chargement ;
- `weights_only=True` ;
- jamais de `.pt` antérieur ou externe (T-V0-05).

**Routes proposées :**

| Option | Contenu | Condition |
|---|---|---|
| **A** | `torch==2.15.0+cpu` depuis l'index CPU (environ 0,2 Go selon l'ordre de grandeur habituel ; disponibilité de 2.15.0 pour cp311 **non vérifiable** car l'hôte est bloqué) | ajout de l'hôte `download.pytorch.org` aux hôtes autorisés de l'environnement, approuvé par vous sur une carte. Je ne le demanderai qu'après adoption de la tranche |
| **B** | `torch==2.15.0` depuis PyPI, avec ses dépendances CUDA, inutiles sur CPU ; plusieurs Go, taille totale non mesurée | aucun changement réseau ; espace disque de la session |
| ~~C~~ | **retirée** : un B2/H1 en numpy n'est pas équivalent et changerait l'expérience | — |

**Si la route adoptée échoue** (refus réseau, import impossible, version absente) : arrêt
propre, livraison de l'état et du manque exact. Aucun basculement non autorisé, aucune autre
version.

**Contrôle R0.ENV :**
- import ;
- `torch.__version__ == "2.15.0"` (suffixe `+cpu` admis en A) ;
- un produit matriciel sur CPU ;
- `set_num_threads(4)` ;
- gel et empreintes des roues consignés.

## A6. Calcul : temps mural, temps CPU, crédits (revue § 5, demande 5)

Les plafonds par lot et l'échelle de repli sont dans `COMPUTE_PLAN_HOWM1.md` (§ 4 et § 5),
désormais joint.

| Mesure | Définition | Plafond |
|---|---|---|
| **Temps mural** | horloge monotone, du lancement à la fin de chaque commande, mesurée par l'exécuteur | **21 600 s au total** ; par lot (plan § 4) ; 540 s par commande, 120 s par test |
| **Temps CPU** | utilisateur + système des processus enfants (`getrusage`) ; il peut atteindre environ 4 × le temps mural avec 4 fils | **rapporté**, sans plafond séparé |
| **Parallélisme** | une seule commande à la fois ; `torch.set_num_threads(4)` ; aucun processus en arrière-plan | — |
| **Crédits d'assistant** | non mesurables par moi | aucun plafond que je puisse garantir |

- Le pilote est **inclus** dans l'enveloppe (lot R1.PILOT).
- Le plafond de 21 600 s **ne prouve pas** la faisabilité. Après chronométrage, seuls les
  paliers déjà déclarés peuvent s'appliquer ; sinon, arrêt.
- Aucun plafond ne sera relevé et aucune règle assouplie après un résultat.

## A7. Persistance et récupération des octets (revue § 5, demande 6)

**Fait vérifié :** le dépôt `HospitalOsLaunch/carepredict-mvp` est **public**. Un push publie
donc le contenu, données synthétiques comprises.

| Option | Contenu | Visibilité |
|---|---|---|
| **P0** | aucun push, aucun envoi ; risque de perte si le conteneur est recyclé | — |
| **P2** (recommandée) | à G0, F1 et en fin de R1, **un paquet envoyé comme fichier dans cette conversation**, pas un chemin interne. Contenu : `git bundle 68320a8..HEAD` (code exact et historique depuis la base distante), checkpoints (dernier et meilleur par graine, avec optimiseur, ordonnanceur, états RNG torch, numpy et python, position d'échantillonnage), corpus compressé ou sa recette exacte (G0 + code), manifeste, gel de l'environnement, `RESTORE.md` et script de reprise | privée (vous) |
| **P1** | push **avance rapide seulement** vers `origin/claude/hospitalos-auto-first-p0-p4-s2dywn` aux seuls jalons G0, F1 et fin de R1 ; corpus non poussé | **public** |

**Conditions de P1 :**
- Avant chaque push :
  - vérification que le distant est un ancêtre de HEAD ;
  - liste `git log origin/…..HEAD --stat` consignée au registre ;
  - pas de `--force`, de merge ni de rebase ;
  - aucune écriture sur `main` ni `mvp/computer-use`.
- Les ancêtres sont déjà sur le distant, jusqu'à `68320a8` : seuls les nouveaux commits sont
  transmis.

**P1 et P2 sont cumulables. Défaut si rien n'est dit : P0.**

**Taille du paquet** : estimée < 100 Mo, non mesurée. Si l'envoi d'un fichier échoue pour cause
de taille, le paquet est découpé, sans rien omettre.

**Reçu de restauration** (`RESTORE_RECEIPT_R1.json`) :
- produit **depuis le paquet livré**, dans un dossier neuf, et non depuis l'arbre de travail ;
- étapes : restauration, reprise d'un pas égale au pas ininterrompu, recalcul d'un sous-ensemble
  de métriques DEVTEST à l'identique.
