# HOWM-1 — Proposition de tranche R0+R1 (une seule décision)

**Statut : NON APPROUVÉE.** Ce document ne déclenche rien. Le mandat de préparation n'autorise
aucune des actions suivantes :
- dépense ;
- installation ;
- génération de corpus ;
- entraînement ;
- lecture de réserve ;
- push.

## Ce que l'accord couvrirait

Une seule tranche, conduite **jusqu'au point d'arrêt** sans nouvelle demande par test ou
fichier. Les documents adoptés sont désignés par leur empreinte :

| Document | SHA-256 |
|---|---|
| `DESIGN_HOWM1_R0_R1.md` | `8cfa7b43c01d7f4adf1f299d58fb051794e220367b76c49e93d4a0a2d28bb57c` |
| `EXPERIMENT_HOWM1_R0_R1.json` | `7b3c9f29068608126f1c72bf367aeb9d02dacd894051cb6612c46bfc6ba7efe2` |
| `TEST_MATRIX_HOWM1.md` | `ef8605f0767b6e2d18246e17a6567ad403552ee473522b463e072ac25a5b3d76` |
| `COMPUTE_PLAN_HOWM1.md` | `87aa5d65546d48d17356aa44e4c155d24ca3d55887ebeceef63c1fb97252c4ea` |
| `INPUT_PROVENANCE.json` | `376aab1a92767e220872ebb4d1b2234b1c8e7da996e334e6172bfc9a722bdebe` |
| `RESUME_HOWM1_PREP.md` | `e33595f3b0d81df0244c14acd6cfdbdf34bf173f53013ac9cdc43c4da32418f2` |

Contenu de la tranche :

1. **Périmètre R0 :**
   - monde à 2 unités, contrat `HOWM1_EVENTS_1`, opérateur et vérificateur ;
   - générateur G_main (populations REF et DIAG), G_alt ;
   - exécuteur et registre HOWM-1 neufs ;
   - engagement G0, corpus TRAIN/VAL/DEVTEST/DIAG-DEV ;
   - précontrôle de marge sur VAL.
2. **Périmètre R1 :**
   - B0-pool, B0-local, B2, H1 (3 graines chacun pour B2 et H1) ;
   - pilote chronométré ;
   - sélection sur VAL, gel F1 ;
   - lecture **unique** de DEVTEST et DIAG-DEV ;
   - reçu de restauration.
3. **Budget :**
   - 0 € ;
   - registre neuf, plafond **21 600 s** de temps mural CPU ;
   - plafonds par lot du plan de calcul ;
   - **540 s** par commande, 120 s par commande de test ;
   - échelle de repli déclarée ;
   - aucun reliquat P5 ou P0–P4.
4. **Installation unique.** Venv `venv_howm` en Python 3.11.18 avec torch 2.4.1 CPU.
   Choisir **A, B ou C** :
   - A : index CPU, recommandée ;
   - B : PyPI standard, environ 3 Go ;
   - C : pas d'installation, numpy dégradé.
   - « A puis B si A est bloquée » est aussi possible.
5. **Valeurs à fixer.** Les propositions de `EXPERIMENT_HOWM1_R0_R1.json` sont adoptées comme
   valeurs, notamment :
   - tailles des partitions 48/12/24/12 et réserve 48+16 scellée ;
   - 8 jours par établissement ;
   - instants 07/11/15/19 ;
   - parts REF 0,3 et 0,5 ;
   - M = 16 ;
   - DIAG en évaluation seulement.

   Les valeurs encore marquées « à fixer » le sont **par moi, avant le gel concerné**, et
   journalisées. Ce sont U, δ_dec, w_k, la patience et les cibles de progrès. Elles ne sont
   jamais fixées après une lecture.

   Propositions par défaut :
   - **δ_dec** = 15 minutes-soignant par instant ;
   - **cible de progrès prédictive** : NLL de H1 inférieure d'au moins 10 % à celle de
     B0-local à H6 et H24 sur DEVTEST REF, borne basse de l'IC > 0 ;
   - **cible décisionnelle**, seulement si le précontrôle est informatif : regret de H1
     inférieur d'au moins 5 minutes-soignant à celui de B0-local, borne basse > 0.

   Ce sont des ambitions d'ingénierie, pas des seuils cliniques. Un échec est rapporté tel
   quel.
6. **Branche et dépôt :**
   - travail sur `claude/hospitalos-auto-first-p0-p4-s2dywn` ;
   - nouveau code sous `src/hospitalos/howm/`, `scripts/howm_*` et `evidence/howm1/` ;
   - v6, P5 et `mvp/computer-use` intouchés ;
   - aucun merge ni rebase.
7. **Item P, persistance.** Choisir :
   - **P1** : push vers `origin/claude/hospitalos-auto-first-p0-p4-s2dywn` aux seuls points
     d'arrêt G0, F1 et fin de R1 ;
   - **P0** : aucun push, avec un risque de perte si le conteneur est recyclé.

   Par défaut : P0.

## Point d'arrêt et livrables R1

**Point d'arrêt :** livraison des poids et des résultats de développement. Je ne fais ensuite
rien d'autre :
- ni réserve, ni H2/H3, ni boucle fermée ;
- ni seconde installation, ni dépassement.

**Livrables :**
- sources exécutables et tests ;
- checkpoints F1 restaurables (poids, optimiseur, RNG) ;
- manifeste du corpus et engagement G0 ;
- courbes H1/H6/H24 ;
- comparaison B0/B2/H1 en prévision, interventions et décisions par instant, avec coûts ;
- diagnostics : sondes, décomposition estimation/dynamique, cas d'erreur, d'ignorance et de
  conservation du plan ;
- reçu de restauration ;
- registre ;
- rapport.

Un modèle faible ou un résultat nul est un résultat. Il ne justifie ni abandon ni
agrandissement automatique.

## Arrêts anticipés

Ces cas arrêtent la tranche avec un reçu ; la suite demande une décision distincte :
- violation d'invariant de l'opérateur sur le vrai générateur ;
- échec d'un test bloquant de frontière d'information ;
- projection du pilote au-delà de l'enveloppe après repli ;
- refus réseau sans option couverte.

## Formulation d'accord suggérée

« J'adopte la tranche R0+R1 HOWM-1 selon les empreintes ci-dessus, installation **[A | B |
A puis B | C]**, persistance **[P0 | P1]**. »
