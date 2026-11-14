# Correctif P2/P3bis puis P4bis — après l'audit indépendant du 14 novembre 2026

Entrée : `HospitalOS_Audit_DS_20261114` (35/35 empreintes conformes ; rapport identique au fichier
transmis), portant sur `HospitalOS_DS_P0-P4_20261114.zip` (SHA-256 `431e2e44…cda4e`, arbre
`d7844ea`). Statut de livraison : **`PARTIAL_WITH_CHECKPOINT`** (portes restantes : § 6 et § 9). Ce rapport
interne au dépôt et au paquet fait foi ; une copie transmise séparément plus tôt était antérieure
au § 8 (exécution Python 3.11). Statut scientifique inchangé : `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`.

## 1. Reproduction avant modification (état rouge)

| Contrôle | Arbre `d7844ea` (restauré) | Branche `b5d09be` (avant correctif) |
|---|---|---|
| A01–A10 de l'audit | 9 échecs, A10 réussi | 9 échecs, A10 réussi |
| 44 tests DS + 86 hybrides | — | 130 réussis (+ A10 = 131) |

Le fichier `tests/decision_support/test_independent_acceptance.py` est la copie **octet pour
octet** de celui de l'audit (SHA-256 `bea463db…4adb`). Il n'a pas été modifié ni affaibli ; il est
seulement exclu du lint (style d'origine conservé). Journaux : `evidence/decision_support/runlogs/`.

## 2. Correctifs (priorité 1)

| Constat | Correction | Preuves |
|---|---|---|
| **F01** verrous contournant les préconditions | Une seule fonction `lock_precondition_issues` / `plan_precondition_errors` (`eligibility.py`) pour l'auto et le manuel. Un verrou `validated_instruction` dont un obstacle actif, une estimation de disponibilité ou un délai de transport contredit l'heure (certainement **ou** dans certains scénarios) est rétrogradé en `hypothesis_only` avec diagnostic ; l'heure n'est jamais déplacée. Dans le simulateur, une précondition manquée d'un verrou validé est une **violation** (plus un simple avertissement). À l'approbation, la revalidation est **systématique**, même sans changement d'empreinte. | A01, A02 ; `test_corrections::test_f01_*` (heure conservée, cas « possible », arrondi prudent, recommandation forcée `approvable=True` refusée à l'approbation, violation du simulateur, X1/X2 valide toujours approuvable) |
| **F02** prêts cumulés | `lending_violations` (`resources.py`) : comptage par unité prêteuse, compétence et heure (valeurs les plus prudentes si les déclarations divergent). Appliqué à l'énumération (combinaison rejetée et tracée dans `search.rejected`), aux verrous, aux invariants du simulateur et aux réservations entre demandes (créneaux `lend:<unité>:<compétence>` par heure, capacité = effectif − minimum). | A03 ; créneaux disjoints autorisés ; deux demandes distinctes ne dépassent pas la marge |
| **F03** réservations non atomiques | `ResourceLedger.reserve_all` : vérification sur copie, engagement uniquement si tout réussit. | A04 ; refus sans fuite, réservations d'autrui intactes, rejeu stable |
| **F05** 10 h 30 arrondi à 10 h | Refus explicite (`unsupported_time_precision`) des heures non entières dans `LockedDischarge`, `LockedExtension`, `CivilDeadline`. Les heures « pas avant » observées (disponibilité, départ prévu) sont arrondies **à l'heure suivante** (`hour_index_ceil`), jamais avancées. | A06 ; `test_f05_*`, `test_f01_possible…` |

## 3. Correctifs (priorité 2)

| Constat | Correction | Preuves |
|---|---|---|
| **F04** idempotence | La clé est liée à `request_fingerprint` = empreinte (recommandation, snapshot, décision). Même clé + même contenu : reçu historique inchangé, `replayed=true`, `current_validity` réévaluée maintenant. Même clé + autre contenu : `IdempotencyConflict` (HTTP 409 côté serveur, message affiché par les deux interfaces). | A05 ; T10 renforcé ; test Vitest du conflit |
| **F06** nettoyage inventé | Plus de valeur par défaut. Un lit qu'un plan peut libérer sans durée connue entraîne l'abstention `cleaning_duration_unknown:<lit>` ; une hypothèse de remplacement n'est possible que configurée et versionnée (`unknown_cleaning_assumption` du profil, `null` par défaut) et elle est signalée `assumed_cleaning_duration:<lit>:<id>@<version>`. Le simulateur refuse aussi (violation). | A07 ; `test_f06_*` |
| **F07** planning inconnu = 0 | Couverture du planning vérifiée pour **chaque compétence requise** (soins, tâches, admissions, tâche de sortie) ; sinon `roster_unknown:<compétence>`. Avec planning déclaré, un effectif nul est un vrai zéro. | A08 ; `test_f07_*` |
| **F08** identifiants | `settings_fingerprint` (profil, objectif, score complets + backend) et `run_fingerprint` (+ graines, horizon) entrent dans l'identité ; l'identifiant de bundle est calculé sur le contenu des évaluations. Le stockage du serveur refuse de remplacer un document par un autre sous le même identifiant. | A09 ; `test_f08_*` |

Compléments demandés :

- **A10 conservé** : le besoin IDE ne dépend pas des offres de renfort (toujours vert).
- **T19 à seuil** : fixture `staff_threshold.json` (deux séjours, 1 IDE par heure), oracle écrit à
  la main dans `build_fixtures.staff_threshold` : minutes non couvertes = 100 + 10 t et
  7 + t heures à 2 IDE requis ; le besoin repasse à 1 IDE l'heure suivant le départ de X2.
  Vérifié pour t = 0…7.
- **Comptabilité des admissions** : chaque heure-patient est comptée une seule fois (attente ou
  unité), le travail d'admission dû n'est ajouté qu'une fois en fin d'horizon pour un patient non
  admis, et la demande IDE dans l'unité est re-dérivée indépendamment heure par heure. Aucun test
  n'impose qu'une admission améliore chaque score.

## 4. Chiffres de la fixture nominale (sorties, pas objectifs)

Identiques avant et après correctif : pratique habituelle 1040 minutes non couvertes ;
coordination S01 seule 905 ; R1 + R2 seuls 640 ; combinaison 435 ; combinaison sans R1
(non confirmé) 795. Les statuts des scénarios exportés sont inchangés ; seuls les identifiants
changent (F08). Ce ne sont pas des preuves de bénéfice réel.

## 5. P4bis

L'écran React « Plan 24 h » (`#/plan`) existait déjà : il a été intégré auparavant, après l'accord
explicite de l'utilisateur pour `npm ci` dans `web/`. **Aucune nouvelle installation** n'a été faite
dans ce cycle ; les `node_modules` présents ont été réutilisés hors ligne. Mises à jour : conflit
409 affiché, rejeu et validité courante affichés, hypothèses de remplacement listées. Contrôles :
typecheck, Vitest 72/72 (66 existants + 6), build, e2e React 17/17 et page autonome 19/19 contre le
moteur corrigé. Ces e2e sont exécutés par l'auteur ; ils ne valent pas revalidation indépendante.
Dans un environnement neuf, relancer les tests du cockpit exige toujours `npm ci` (réseau).

## 6. Portes ouvertes et limites

1. **Python 3.11** — exécution complète sous **3.11.18** (voir § 8) : 163/163. Reste ouvert le
   seul niveau exact **3.11.9** (télécharger cet interpréteur n'est pas couvert par les accords).
2. **Ré-audit indépendant** des correctifs.
3. `test_decision_guard.py` non lancé : `fit_benchmark()` sélectionne et ajuste des modèles
   (dont un gradient boosting), ce qui est un apprentissage hors périmètre.
4. `mypy --strict` non exécuté ; e2e navigateur non revalidés de façon indépendante.

## 7. Budget et registre

L'audit a exécuté 21,102 s ailleurs ; elles ont été imputées au registre (note chaînée), qui
était à 125,249 s : reprise à 146,351 s. Le plancher prudent de l'audit (64,702 s) est inférieur au
registre réel. Le registre a désormais une **ancre** (`BUDGET_LEDGER.anchor.json` : longueur,
dernière empreinte, total) : une troncature ou une perte du fichier sont détectées (test dédié).
Limite déclarée : si registre **et** ancre disparaissent ensemble, seule la copie terminale du paquet
(`LEDGER_TERMINAL.json`, listée dans `SHA256SUMS.post`) prouve le compteur. `restore.sh` vérifie
désormais `SHA256SUMS`, `SHA256SUMS.post` et que le compteur restauré égale le terminal.

## 8. Addendum — exécution sous Python 3.11 (après le scellement du paquet v3)

Accord explicite de l'utilisateur : installation de pydantic, numpy et pytest pour Python 3.11.
Environnement virtuel isolé (dossier de travail de la session, Python système inchangé),
`/usr/bin/python3.11` = **3.11.18**, contraintes du `pyproject.toml` : pydantic 2.14.3
(pydantic_core 2.50.4), numpy 2.4.6, pytest 8.4.2, plus leurs dépendances directes
(`evidence/decision_support/py311_venv_freeze.txt`). Installation : 11,986 s, imputée au registre.

| Contrôle sous 3.11.18 | Résultat |
|---|---|
| Suite DS + 86 hybrides, hors `test_p1_contracts.py` | **153 réussis**, 0 échec (`pytest_py311.xml`) |
| `test_p1_contracts.py` (10 tests), 1er passage | non collecté : `ModuleNotFoundError: jsonschema` |
| Après accord pour `jsonschema` (4.26.0, même version que sous 3.13 ; 1,943 s imputées) : suite **complète** DS + 86 hybrides | **163 réussis**, 0 échec, 0 ignoré (`pytest_py311.xml`) |
| 11 résultats régénérés vs index livré | **identiques octet pour octet** |

Ces exécutions sont postérieures au scellement du
paquet v3 : elles figurent dans le registre du dépôt, pas dans le terminal de v3.

## 9. Correctif v5 — après le ré-audit indépendant de la v4

Entrée : `HospitalOS_Audit_DS_v4_Correctifs_20261114.zip` (SHA-256 `4bec5b3d…ac1c2`, 37/37
empreintes conformes ; rapport et prompt identiques aux fichiers transmis), portant sur la v4
(SHA-256 `c8885375…045e`, arbre `bebb95b`).

**Budget (étape 0).** Le registre de l'audit prolonge **exactement** le terminal v4 (105 lignes
identiques, chaîne et ancre valides avec le vérificateur du dépôt) et ajoute 22,885 s
(`HospitalOS_DS_v4_independent_20261114`). Le dépôt n'ayant rien enregistré après le scellement
de la v4, cette lignée a été adoptée telle quelle : 114 enregistrements, 260,024 s, sans double
comptage. Les journaux 107–114 de l'audit sont copiés dans `runlogs/` (leurs chemins enregistrés
renvoient à l'environnement de l'auditeur).

**Rouge.** Tests de l'audit copiés octet pour octet : `test_v4_resource_boundaries.py` = B01, B02,
B03 en échec, B04 réussi ; `test_v4_restoration_counter.py` contre la vraie restauration v4 =
échec « Restored 102 records, sealed terminal 105 ».

| Constat | Correction | Preuves |
|---|---|---|
| **V4-R01** fenêtres décalées | Une fenêtre de renfort hors grille horaire est **refusée** (`unsupported_time_precision:reinforcement_window_not_on_whole_hours`), jamais arrondie. En défense, cumul et réservations utilisent une **grille commune** (`touched_hours` : toute heure touchée compte). Même règle pour l'énumération, les verrous et l'approbation (`plan_precondition_errors` réutilise `option_admissibility`). | B01 ; `test_corrections_v5::test_r01_*` (raison exacte, R1 aligné toujours utilisable, chevauchement détecté même si l'admissibilité était contournée, clés communes, témoin sans chevauchement autorisé) |
| **V4-R02** prêteur inconnu | `shared_unit` sans `lending_unit` : offre refusée (`lending_unit_unknown`), violation dans le cumul, et réservation à capacité inconnue (donc refusée) au lieu d'un contrôle sauté. Les autres sources ne sont pas touchées. | B02 ; `test_r02_*` |
| **V4-R03** capacité historique conservée | `reserve_all` applique la capacité **courante** de l'instantané (y compris inconnue), conserve les engagements existants, refuse le nouvel engagement incompatible et trace le conflit (`capacity_below_existing_holds`, `capacity_now_unknown`) dans `ResourceLedger.conflicts`. | B03 ; `test_r03_*` |
| **V4-D01** compteur restauré antérieur | `restore.sh` choisit le registre le plus récent du paquet (final > terminal scellé > copie de construction), vérifie que la copie de l'arbre en est un **préfixe exact**, l'installe dans `evidence/decision_support/` de la cible avec une note tracée, puis exécute les tests et l'export **via le compteur de la cible**. Le reçu donne le `--status` de la cible après rejeu. | `test_v4_restoration_counter.py` vert contre la restauration post-scellement ; `RESTORE_RECEIPT_POSTSEAL.json` |

Les chiffres nominaux restent 1040 / 905 / 640 / 435 / 795 (sorties de fixture).
