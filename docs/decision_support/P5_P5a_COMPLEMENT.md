# P5a — Complément de livraison (14 novembre 2026)

Relivraison des octets **originaux**, sans nouvelle expérience. Aucun changement du moteur v6, du
protocole, des seuils, des populations, des graines, des choix de plans ou des résultats gelés.
Rien n'a été régénéré ni relancé.

Entrées vérifiées :
- paquet historique `HospitalOS_P5a_20261114.zip` (`ca698f78…2602`), non modifié ;
- revue `HospitalOS_Revue_P5a_20261114.zip` (`544b87b7…c186`), 10/10 empreintes conformes ;
- prompt et rapport de revue identiques aux pièces jointes ;
- registre repris au dernier terminal (55 enregistrements, 98,221 s, `734ee0ad…c715c`).

## 1. P5A-D01 — dossiers de calcul absents : cause et correction

**Cause.** La règle `runs/` du `.gitignore` du dépôt (ligne 66) a exclu silencieusement les deux
dossiers de `git archive` et des patchs. Les fichiers n'ont jamais quitté le disque de la session
de calcul. Le défaut est le mien : mon contrôle de paquet vérifiait les fichiers **présents**, pas la
présence des fichiers **nécessaires**. Le complément ajoute donc une liste de complétude séparée,
vérifiée après extraction neuve.

**Fichiers originaux, horodatés pendant les commandes 45–46 et 50–52 :**

| Dossier | Fichiers | Contenu recompté depuis les fichiers |
|---|---|---|
| `evidence/decision_support/p5/p5a/P5a_dev/runs/0108da5768b4c2023181/` | `RUN_IDENTITY.json`, `pilot_parents.jsonl`, `structures.jsonl` | 100 parents, 10 structures × 10, R1 et R2, K = 3 ; 103 candidats, 3 exclusions |
| `evidence/decision_support/p5/p5a/P5a_eval/runs/ece90db4e6159a03bf84/` | `RUN_IDENTITY.json`, `pilot_parents.jsonl`, `structures.jsonl` | 300 parents, 30 structures × 10, R1 et R2, K = 3 ; 300 candidats, 0 exclusion |

Le nom `pilot_parents.jsonl` est imposé par `pilot.open_run`, réutilisé par l'exécuteur P5a. Ces
fichiers ne sont **pas** le pilote E0 de 20 parents, conservé à part dans
`evidence/decision_support/p5/pilot/`.

**Empreintes, identiques à celles consignées au registre n° 54 avant la première livraison :**

| Fichier | SHA-256 |
|---|---|
| réserve `pilot_parents.jsonl` | `445cf7de829c0ab69fd7c92c84247b0191ee417291687507d95d587423c64347` ✓ |
| réserve `structures.jsonl` | `3d965995e291ffbcc41a87bb83e9e34ee38288876a975acf286a967eaa968c89` ✓ |
| `RESULTS_P5a.json` | `1a7974176def47c24c6ee929e357de56824a43cf77ffa78148bbd2cc15d85c89` ✓ |
| `F_a.json` | `055a4d2692472f6a6f64f51bea876bd5be808acc90c50bb9891f606af9b7a6bc` ✓ |

Les fichiers du développement n'avaient pas d'empreinte au registre avant cette relivraison. Leur
empreinte actuelle figure dans `COMPLETENESS_P5a.json`. Leur intégrité repose sur l'identité
d'exécution et les comptes, cohérents avec les commandes n° 45–46 (50 puis 100 parents).

**Contrôles de cohérence** (`scripts/p5_complement_check.py`, lecture JSON seule, aucun module
HospitalOS importé, commande n° 56, 0,11 s) :
- identifiant d'exécution égal au dossier ;
- partition, K = 3, régimes R1 et R2 conformes ;
- identifiants de structure égaux à l'identité, 10 parents par structure, aucun doublon ;
- forme des plans et des résultats correcte (3 réalisations × n plans par régime) ;
- plan 0 = HABITUAL-1 ;
- 0 problème.

La même vérification est rejouée sur une extraction neuve du complément (§ 5).

## 2. P5A-D02 — contrôle d'isolation T03/T04 sur 50 épisodes : **non exécuté**

Le garde-fou 2 du protocole (« 0 fuite : contrôle d'isolation T03/T04 sur 50 épisodes tirés ») **n'a
pas été exécuté** pendant P5a. Il n'existe ni reçu, ni commande, ni liste de cas. Je n'en fabrique
pas.

Preuves d'isolation qui existent réellement, sans remplacer ce contrôle :
- **n° 6** : les deux tests v6 T03/T04 sur les fixtures nominales ;
- **tests P5** (n° 43, 69/69) :
  - F1 : les variables ne lisent pas la vérité ;
  - T-P5-R1 : présence différente ⇒ couverture différente et recommandation inchangée ;
  - signature de `recommend` sans paramètre de vérité ;
- **par construction** : l'exécuteur P5a appelle `recommend(snapshot, settings)` sans la
  réalisation privée.

Conséquence : dans `RESULTS_P5a.json`, les garde-fous calculés sont violations, univers, exclusions
et dégradation. **Le garde-fou de fuite sur 50 épisodes est à lire comme « non vérifié ».** Le
verdict R1 reste `exploratory`, fixé par la précision avant F_a. Il n'aurait de toute façon pas pu
être « démontré » sans ce garde-fou. Un contrôle ultérieur devra être autorisé, tracé et présenté
comme postérieur au gel. Il n'est pas lancé ici.

## 3. Précisions de lecture (aucun résultat gelé modifié)

**Minima par classe.** Les minima « coordination seule / renforts seuls / combinaison » de
`RESULTS_P5a.json` sont des moyennes **sur les seuls parents où la classe existe**.

| Classe | Parents supports (réservé, sur 300) | Développement (sur 100) |
|---|---:|---:|
| C (coordination seule) | 269 | 85 |
| R (renforts seuls) | 176 | 61 |
| CR (combinaison) | 151 | 51 |

Ils ne sont pas comparables entre eux, ni au U\* global, calculé sur les 300 parents. Les supports
sont identiques en R1 et R2, l'univers ne dépendant que de l'instantané public. Le complément ajoute
aussi les classes des plans choisis (127 C, 45 R, 109 CR, 19 HABITUAL-1), recomptées depuis les
fichiers.

**Précision de P5b.** Le critère principal de P5b est une autre différence appariée :
U(choix M_agg) − U(choix M_ent). Sa précision doit être projetée sur **sa propre** variabilité
entre structures, estimée sur la partition de validation P5b, comme le prévoit le protocole.
L'écart-type de P5a (94,8, sur le gain plan v6 − pratique habituelle) **ne doit pas être
réutilisé**. P5b n'est donc ni condamné d'avance à la même conclusion exploratoire, ni assuré
d'une précision suffisante.

## 4. Correction dans le dépôt

Les deux dossiers sont ajoutés au suivi Git de la branche (`git add -f`, règle `runs/` inchangée
pour le reste du dépôt), avec le script de contrôle, `COMPLETENESS_P5a.json` et cette note. Le
patch correspondant est inclus dans le complément.

## 5. Complément livré

`HospitalOS_P5a_Complement_20261114.zip` contient :
- les dossiers originaux ;
- `F_a.json`, `RESULTS_P5a.json`, `PRECISION_DEV.json` ;
- `COMPLETENESS_P5a.json` ;
- `REQUIRED_FILES.txt`, la liste de complétude séparée ;
- le script de contrôle, cette note et le patch ;
- `MANIFEST.json` et `SHA256SUMS`, couvrant explicitement les dossiers d'exécution.

Après création, l'archive est **extraite à neuf** et contrôlée sous compteur (lot P5.5) : présence
de chaque fichier de la liste de complétude, octets identiques aux empreintes, contrôle de
cohérence. Le registre après ce contrôle est livré à part
(`HospitalOS_P5a_Complement_POST_20261114.zip`) pour ne pas modifier l'archive contrôlée.

## 6. Budget

Lot P5.5 (vérification de livraison P5a) : 2,304 s au départ, plus le contrôle du dépôt (n° 56)
et celui de l'extraction neuve. Aucune réallocation de plafond, aucune remise à zéro, P0–P4
inchangé.

Statuts inchangés : `PARTIAL_WITH_CHECKPOINT`, `PROTOTYPE_UNVALIDATED`,
`clinical_validation=false`, `G2=NO-GO`. P5b, D16, P6, AJ-H, installation et push restent fermés.
Arrêt après cette relivraison.
