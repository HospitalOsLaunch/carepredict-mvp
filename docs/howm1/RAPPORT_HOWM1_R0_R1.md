# HOWM-1 — Rapport de la tranche R0+R1

**Période :** 14 au 16 novembre 2026.
**Accord :** `inputs/accord/ACCORD_HOWM1_v1_1_ADOPTE.txt`, avec installation « A puis B » et persistance
« P2, sans push ». Relevé de décision au registre HOWM n° 2.
**Point d'arrêt atteint :** poids, résultats de développement et reçu de restauration livrés.
Rien d'autre n'est lancé : ni réserve, ni H2/H3, ni JEPA, ni boucle fermée, ni push.

Les statuts restent inchangés :
- `PROTOTYPE_UNVALIDATED` ;
- `clinical_validation=false` ;
- `G2=NO-GO`.

Données synthétiques seulement. Aucun bénéfice hospitalier réel n'est revendiqué.

## 1. Résultat principal

Le résultat est négatif sur le critère principal.

**Dans ce monde synthétique, sur 24 établissements REF jamais vus (DEVTEST, lecture unique après
F1), le world model par entités H1 ne prévoit pas mieux que les mécanismes explicites recalibrés
localement (B0-local).** Il fait légèrement moins bien.

| Lecture pré-déclarée | Valeur (IC 95 % bootstrap par établissement) | Verdict |
|---|---|---|
| Δ_LS(6) = L(B0-local) − L(H1), en nats par élément | **−0,020 [−0,039 ; +0,001]** | critère principal **non atteint** |
| Δ_LS(24) | **−0,022 [−0,041 ; −0,002]** | B0-local **meilleur** que H1 |
| R(6), CRPS normalisé, 1 − H1/B0-local | −0,021 [−0,058 ; +0,004] | ambition non atteinte ; gain positif non établi |
| R(24) | −0,020 [−0,052 ; +0,006] | idem |
| D_dec = U(choix B0-local) − U(choix H1), par instant | −0,2 [−7,9 ; +6,1] | ambition non atteinte ; gain positif non établi |

Lectures descriptives :
- B2 et H1 sont très proches : B2 − H1 = +0,005 [−0,001 ; +0,012] à H6.
- B0-local fait mieux que B0-pool : −0,023 [−0,040 ; −0,002] à H6, en faveur de B0-local.
- **L'estimation locale explicite est ce qui apporte quelque chose dans ce monde. Les mémoires
  apprises B2 et H1 ne la retrouvent pas.**

## 2. Déroulé (registre HOWM-1)

Le registre compte 92 enregistrements et 81 commandes.
- **Temps mural :** 6 895 s sur 21 600 s.
- **Temps CPU :** 13 913 s, rapporté séparément.
- **Dépense :** 0 €.
- **RÉSERVE :** non utilisée.

| Lot | Utilisé / plafond (s) | Contenu |
|---|---:|---|
| R0.ENV | 56 / 600 | venv dédié ; route A (index CPU officiel, 2 hôtes autorisés par vous sur carte) ; torch 2.15.0+cpu ; checkpoint et RNG validés en `weights_only=True` |
| R0.TEST | 118 / 1 200 | tests (38/38 à F1), tests v6 95 passés + 1 ignoré, lint |
| R0.GEN | 51 / 1 200 | G0, corpus de 96 établissements (49 Mo), échelles CRPS sur TRAIN, paquet G0 |
| R0.PRE | 268 / 1 200 | précontrôle sur VAL, contrôleurs privilégiés seulement |
| R1.PILOT | 112 / 900 | pilote v1 (infaisable), optimisation, pilote v2 ; diagnostic T-INF-08 |
| R1.B0 | 35 / 300 | B0-pool, τ_f et s_f (TRAIN 0–31) |
| R1.B2 | 261 / 3 000 | 3 exécutions et paquets |
| R1.H1 | 2 201 / 7 200 | 3 exécutions et paquets |
| R1.F1 | 56 / 300 | sélection, contrôle du code d'évaluation sur VAL, F1, sondes |
| R1.EVAL | 3 269 / 3 600 | lecture unique de DEVTEST (24) et DIAG-DEV (12), analyses |
| R1.REST | 468 / 600 | paquet final et reçu de restauration |

## 3. Ce qui a été construit (R0)

Paquet `src/hospitalos/howm/` ; v6, P5 et `mvp/computer-use` intouchés. T-V0-01 vérifie que le
diff v6 est vide.

- **Monde à 2 unités.**
  - Opérateur explicite au pas de 15 min, partagé par la vérité et par tous les déroulés de
    modèles. Une précondition violée donne un événement rejeté et compté, jamais corrigé.
  - Ressources partagées : transport, nettoyage, renfort de pool, prêt sous le minimum du prêteur.
  - Cycle de vie des actions : demandée, confirmée, exécutée, résultat.
  - Aucune action médicale.
- **Vérificateur indépendant.** Il relit le journal et vérifie :
  - conservation ;
  - un lit = un état ;
  - nettoyage seulement après départ ;
  - capacités ;
  - personnel compté seulement s'il est présent ;
  - minimum du prêteur ;
  - exécution seulement après acceptation.

  Résultat : 0 violation sur les vérités, et sur les déroulés de modèles testés.
- **Générateur G_main.**
  - Populations REF et DIAG, mécanismes m0–m5 (tous hypothétiques).
  - Tirages indexés par clé.
  - Réserve de 48+16 établissements scellée en G0, jamais générée.
- **G_alt.** File de service à pas fixe, écrite indépendamment ; utilisée **seulement** comme
  contrôle de mécanisme du générateur (T-GEN-08). Les modèles n'ont **pas** été évalués sur des
  mondes G_alt : c'est un écart à la conception § 1.7.
- **Frontière d'information.** Un seul constructeur d'historique (`available_at ≤ t`).
  Invariances testées au renommage, à l'ordre et au décalage de semaines. Deux passés publics
  identiques donnent des prédictions identiques (T-INF-03).
- **Régression P5b.** Un parent réservé déjà lu redonne le même choix v6 et les mêmes U
  (T-V0-03).
- **Précontrôle de marge (VAL, 48 instants)** :
  - V_param = −7,6 ;
  - V_latent = +61,8 ;
  - **marge observée sous information privilégiée : 54,2 ≥ 15**, donc lecture décisionnelle
    informative.
  - La marge vient de l'état courant vrai : régime caché et événements non encore publiés.
    Connaître θ_h seul n'apporte rien ici.
  - C_full n'est pas un optimum certifié.

## 4. Modèles (R1)

| Système | Paramètres | Entraînement |
|---|---:|---|
| B0-pool / B0-local | ~400 (lois explicites) ; τ_f choisis sur TRAIN | vraisemblance censurée (numpy/scipy) |
| B2 (mémoire agrégée) | 53 902 | taux 1e-3 retenu ; graines 0 et 1 ; meilleures époques 6 et 6 |
| H1 (graphe typé + mémoire par entité) | 138 127, dont 74 496 pour les messages | taux 3e-4 retenu ; graines 0 et 1 ; meilleures époques 6 et 20 |

**Pertes de validation (VAL, normalisées) :**
- B0-pool : environ 7,215 (point de départ commun) ;
- meilleurs B2 : 7,210 et 7,208 ;
- meilleurs H1 : 7,211 et 7,205.

**Les réseaux n'apprennent presque rien au-delà de leur initialisation B0-pool.** C'est un fait
d'entraînement, pas un défaut d'exécution.

## 5. Écarts et décisions consignés (tous avant la lecture concernée)

1. **Auth en intervalles d'une heure.** La famille « autorisation », non notée, utilise des
   intervalles de 1 h sur 192 h. Avec 15 min sur 48 h, les séjours longs n'auraient jamais pu sortir
   en déroulé.
2. **Vérificateur.** Journal de vérité côté privé avec ordre d'émission ; règle de présence alignée
   sur l'opérateur. Aucun changement de l'opérateur.
3. **Règle post-G0 (n° 33).** Fichiers générateur et frontière gelés en G0, vérifiés par chaque
   commande R1 ; modules de modèles et d'évaluation gelés en F1.
4. **Pilote v1 infaisable (n° 42).** H1 projeté à 7 828 s, au-delà de 7 200 s après les paliers.
   - Optimisation d'implémentation seulement, à fonction et paramètres identiques, testée par
     égalité numérique : environ 2,7 fois plus rapide.
   - Pilote v2 faisable **après les trois paliers déclarés** (n° 51) :
     - diagnostic décisionnel réduit à 2 instants (07 h, 11 h) et M = 8, pour la décision
       seulement ;
     - TRAIN réduit à 32 établissements pour tous les modèles, B0 refait ;
     - 2 graines au lieu de 3.
   - Les origines du score prédictif (120 par établissement, M = 16) n'ont **pas** été réduites.
5. **Famille « présence ».** Aucun élément dans les origines TRAIN, donc s_f indéfini et famille
   exclue de la perte (n° 42), sans epsilon. Elle est aussi absente de DEVTEST : score 0 sur 0
   élément.
6. **Règle métier renforcée.** Implémentée dans le code gelé en F1 : coordination, nettoyage
   « compatibilité d'abord », renfort IDE vers l'unité de plus forte pression publique.
7. **Corpus du reçu.** Les fichiers gzip portent un horodatage dans leur en-tête : l'identité du
   corpus régénéré est vérifiée sur le **contenu décompressé**, et les octets utilisés viennent du
   paquet G0.

## 6. Résultats détaillés (`evidence/howm1/RESULTS_R1_*.json`)

### 6.1 DEVTEST REF (24 établissements, 2 880 origines)

**Score logarithmique moyen (nats) :**

| Horizon | B0-pool | B0-local | B2 | H1 |
|---|---:|---:|---:|---:|
| H1 | 1,156 | **1,135** | 1,155 | 1,153 |
| H6 | 2,069 | **2,047** | 2,072 | 2,067 |
| H24 | 2,263 | **2,239** | 2,268 | 2,261 |

- **Par famille à H24 :** l'avantage de B0-local vient de la sortie prête, du transport et du
  nettoyage, grâce à l'ordonnée locale. Arrivées et soins sont quasi identiques pour tous.
- **Strates (Δ_LS H24) :**
  - simple : −0,017 ;
  - m2 actif : −0,018 ;
  - m3 seul : −0,046.

  H1 ne gagne dans **aucune** strate, y compris là où les mécanismes cachés sont actifs.
- **Couverture des intervalles à 90 %** : environ 0,72 à H1, 0,82 à H6, 0,87 à H24, pour tous les
  systèmes. Les déroulés sont **sous-dispersés à court terme**.
- La dispersion de l'ensemble (8 à 11 unités) est rapportée à part ; elle n'est pas une
  calibration.
- **Événements rejetés par l'opérateur** : 135 à 150 par système, sur 46 080 déroulés de 24 h.

**Décisions (48 instants, U en minutes-soignant par 24 h) :**

| Système | Gain contre l'habituel | Regret contre C_full |
|---|---:|---:|
| B0-pool | 186,8 | 27,4 |
| B0-local | 186,7 | 27,5 |
| B2 | 189,9 | 24,4 |
| H1 | 186,5 | 27,7 |
| **Règle renforcée** | **200,2** | **14,1** |
| C_param | 185,6 | 28,7 |
| C_full | 214,3 | — |

- Oracle (plafond) : gain de 236.
- **La règle métier simple fait mieux que tous les planificateurs à modèle.**

**Effets d'actions** (erreur moyenne sur Δ en minutes, exactitude du signe, effets nuls reconnus) :
- B0-local : 64,6, 0,815, 0,81 ;
- H1 : 64,8, 0,815, 0,71.

**Limites du diagnostic décisionnel :**
- Aucun modèle ne choisit pire que l'habituel (« se trompe » = 0).
- L'indicateur « ne sait pas » vaut 1,0 partout : l'écart entre les deux meilleurs candidats est
  toujours inférieur à la dispersion d'échantillonnage. **Il n'est pas informatif tel que défini.**

### 6.2 DIAG-DEV (12 établissements, diagnostic, jamais utilisé pour choisir)

- **Prévision :** B0-local nettement meilleur que H1. Δ_LS(24) = −0,156 [−0,282 ; −0,046]. Le
  nettoyage (capacité qui baisse sans annonce) est le principal écart.
- **Décision :** D_dec = +18,8 [+1,5 ; +41,2]. Les choix de H1 sont meilleurs que ceux de B0-local
  dans cette population, en estimation ponctuelle et avec une borne basse positive.
- Mais la règle renforcée a un regret de 1,8, contre 53,7 pour H1.
- **Lecture descriptive seulement** ; ce n'est pas le critère principal.

### 6.3 Diagnostics privilégiés (après gel, VAL)

- **Sonde linéaire du régime caché de ralentissement (m2)** à partir des représentations figées.
  AUC en validation croisée par établissement : B2 0,47, H1 0,43.
  **Les mémoires apprises ne codent pas le régime caché.**
- **T-INF-08** (entrées permutées entre établissements) : gain de 0,009 sur 7,41, aucun signe de
  fuite.

## 7. Capacités manquantes diagnostiquées

Ce sont des pistes, **non exécutées**.

1. **Adaptation locale.** La recalibration explicite de B0-local bat la mémoire apprise sur
   24 h : les réseaux n'ont pas de mécanisme d'estimation locale des paramètres d'établissement.
   C'est précisément la variation H2 (contexte c_h) du programme, désactivée en R1 par la règle
   « une variation à la fois ».
2. **Estimation d'état latent.** Les sondes montrent que le régime caché n'est pas représenté.
   Deux candidats en R2 : un latent stochastique, ou une perte orientée vers les durées récentes.
3. **Signal d'apprentissage.** Il est faible : arrêt précoce à l'époque 6 à partir de B0-pool. Le
   choix d'initialiser à B0 et de normaliser par B0-pool peut avoir rendu les corrections apprises
   peu rentables. Cela relève d'un protocole distinct.
4. **Calibration à court terme** : sous-dispersion à H1 pour tous les systèmes, y compris B0.
5. **Diagnostic décisionnel peu discriminant.** Les candidats diffèrent peu face au bruit, et
   l'indicateur « ne sait pas » est à redéfinir.

Aucune de ces pistes ne justifie l'abandon d'HospitalOS ni un agrandissement automatique. Toute
suite est une nouvelle question, avec un protocole distinct.

## 8. Persistance et restauration (P2, sans push)

**Paquets livrés comme fichiers :**
- G0, avec le corpus ;
- après chaque exécution (6) ;
- F1 ;
- fin de R1 ;
- chacun vérifié par extraction dans un dossier neuf.

**Reçu `RESTORE_RECEIPT_R1.json` (ok)**, produit depuis les paquets `R1_END` et `G0` seuls, dans
un dossier neuf, sans accès à l'espace de travail :
- empreintes intactes ;
- 37 tests sur 38 dans l'arbre restauré. Le seul échec, T-V0-01, exige un dépôt git ; il passe
  dans l'espace de travail ;
- régénération de 2 fichiers DEVTEST identique en contenu ;
- **réévaluation complète des 2 établissements (120 origines, décisions) identique aux résultats
  livrés.**

## 9. Ce que R1 ne permet pas de conclure

- Pas de résultat confirmatoire : aucune réserve n'a été lue.
- Pas de transfert hospitalier, de calibration réelle ni de causalité réelle.
- Rien sur la boucle fermée, le contexte d'établissement ou JEPA.
- Les mécanismes et poids, dont 15 minutes-soignant par heure d'attente, sont des hypothèses
  d'ingénierie.
