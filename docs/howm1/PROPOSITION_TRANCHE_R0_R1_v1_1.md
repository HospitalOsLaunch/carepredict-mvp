# HOWM-1 — Proposition finale de tranche R0+R1 (v1.1, une seule décision)

**Statut : NON APPROUVÉE.** Ce document remplace `PROPOSITION_TRANCHE_R0_R1.md` (v1), qui est
conservée. Il ne déclenche rien.

## Paquet adopté par empreintes

| Document | SHA-256 | Version |
|---|---|---|
| `DESIGN_HOWM1_R0_R1.md` | `8cfa7b43c01d7f4adf1f299d58fb051794e220367b76c49e93d4a0a2d28bb57c` | v1 |
| `EXPERIMENT_HOWM1_R0_R1.json` | `7b3c9f29068608126f1c72bf367aeb9d02dacd894051cb6612c46bfc6ba7efe2` | v1, remplacé par v1.1 |
| `TEST_MATRIX_HOWM1.md` | `ef8605f0767b6e2d18246e17a6567ad403552ee473522b463e072ac25a5b3d76` | v1, plus T-PLAN-07 |
| `COMPUTE_PLAN_HOWM1.md` | `87aa5d65546d48d17356aa44e4c155d24ca3d55887ebeceef63c1fb97252c4ea` | v1 |
| `INPUT_PROVENANCE.json` | `376aab1a92767e220872ebb4d1b2234b1c8e7da996e334e6172bfc9a722bdebe` | v1 |
| `RESUME_HOWM1_PREP.md` | `e33595f3b0d81df0244c14acd6cfdbdf34bf173f53013ac9cdc43c4da32418f2` | v1 |
| `AMENDEMENT_HOWM1_R0_R1_v1_1.md` | `d41f44a0cb3a94fd86788fafd9a738c691825b275c7b1e28fb9026b7a8f82063` | v1.1, **prévaut** sur les passages v1 cités |
| `EXPERIMENT_HOWM1_R0_R1_v1_1.json` | `5cbd41421fb997ade256f93e7eef29cb47413e53bc366f12ca060aaa94a3b442` | v1.1 |
| `CHANGEMENTS_v1_v1_1.md` | `32b593cc2be46c1ba243c41c1e7b12af10d56181b80b32aafa503b3f60295093` | v1.1 |

## Ce que l'accord couvre

1. **R0 :**
   - monde à 2 unités, contrat `HOWM1_EVENTS_1`, opérateur et vérificateur indépendant ;
   - G_main (REF et DIAG) et G_alt ;
   - exécuteur et registre HOWM-1 neufs ;
   - G0 ; corpus 48/12/24/12 ; RESERVE 48+16 **scellée, non générée** ;
   - précontrôle de marge sur VAL.
2. **R1 :**
   - B0-pool, B0-local, B2 et H1 (3 graines chacun pour B2 et H1) ;
   - pilote ;
   - entraînement selon les règles fixées (amendement, A4) ;
   - F1 ;
   - lecture **unique** de DEVTEST et DIAG-DEV ;
   - reçu de restauration depuis le paquet livré.
3. **Critères et objectif fixés** (amendement, A1–A3) :
   - Δ_LS apparié, borne basse > 0 à H6 et H24 ;
   - ambition CRPS R(h) ≥ 0,10, ponctuelle ;
   - δ_dec = 15 (marge) ;
   - ambition décisionnelle 5, lue si la marge est informative ;
   - U-HOWM-1 et OBJ-LEX-1.
4. **Budget :**
   - 0 € ;
   - **21 600 s** de temps mural au total ;
   - plafonds par lot (plan de calcul, § 4) ; 540 s par commande, 120 s par commande de test ;
   - temps CPU rapporté ;
   - échelle de repli déclarée (plan, § 5), seule adaptation permise ;
   - aucun reliquat P5 ni P0–P4.
5. **Installation unique de torch == 2.15.0** dans un venv dédié en Python 3.11.18, avec la
   politique de chargement d'A5. **Choisir :**
   - **A** : index CPU. Demande l'autorisation de l'hôte `download.pytorch.org` dans
     l'environnement : je vous la soumettrai sur une carte après l'adoption. Il est
     actuellement bloqué.
   - **B** : PyPI, avec les dépendances CUDA inutiles, plusieurs Go.
   - **A puis B** : B seulement si A est refusée ou indisponible.

   En cas d'échec de la route adoptée : arrêt propre.
6. **Persistance. Choisir :**
   - **P2** (recommandée) : paquets de jalon envoyés comme fichiers à G0, F1 et fin de R1 ;
   - **P1** : push en avance rapide aux mêmes jalons, sur un dépôt **public** ;
   - **P1+P2** ;
   - **P0** : rien. C'est le défaut si rien n'est dit.
7. **Branche et dépôt :**
   - `claude/hospitalos-auto-first-p0-p4-s2dywn` ;
   - nouveau code sous `src/hospitalos/howm/`, `scripts/howm_*` et `evidence/howm1/` ;
   - v6, P5 et `mvp/computer-use` intouchés ;
   - ni merge ni rebase.

## Point d'arrêt

Livraison des poids, des résultats de développement et du reçu de restauration. **Ensuite,
rien d'autre :**
- ni réserve, ni H2/H3, ni boucle fermée ;
- ni seconde installation, ni dépassement.

Un résultat nul ou défavorable est rapporté tel quel.

**Arrêts anticipés**, chacun avec un reçu :
- violation d'invariant de l'opérateur ;
- échec d'un test bloquant de frontière d'information ;
- projection au-delà de l'enveloppe après repli ;
- échec de la route d'installation adoptée.

## Formulation d'accord suggérée

« J'adopte la tranche R0+R1 HOWM-1 v1.1 selon les empreintes ci-dessus, installation
**[A | B | A puis B]**, persistance **[P2 | P1 | P1+P2 | P0]**. »
