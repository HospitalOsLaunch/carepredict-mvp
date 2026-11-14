# HospitalOS — ré-audit indépendant de la livraison v4
14 novembre 2026 — audit technique local, données synthétiques uniquement.

## Verdict
**Les contre-exemples initiaux A01–A10 sont corrigés dans leurs cas testés.** Le fichier de tests est identique octet pour octet à celui du premier audit. La suite annoncée est reproductible : **163 réussites** sous Python 3.13.5, dont **77 tests DS et 86 tests hybrides ciblés**. Les dix A01–A10 sont inclus dans ces 163, et ont aussi été rejoués séparément.

La clôture reste **PARTIAL_WITH_CHECKPOINT** : trois cas voisins de prêts de personnel restent acceptés à tort, et le dossier restauré récupère un compteur antérieur au terminal du paquet. Ce sont des contre-exemples supplémentaires, pas des régressions des dix tests d'origine.

Statut scientifique inchangé : `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`. Aucun entraînement, poids, inférence AJ-H, P5/P6, installation réseau, écriture distante ou action SIH. Les 922 fichiers du source extrait comparés à l'archive sont inchangés.

## 1. Sources, intégrité et niveau de preuve
Archive examinée : `HospitalOS_DS_P0-P4_20261114_v4.zip` (22 059 203 octets).

SHA-256 calculé sur les octets reçus :
```
c88853750b80a085d1dfd7ed9b9db8a8b6ccf6c3c79b1c428598e646160e045e
```
Cette empreinte est calculée ici ; aucune seconde empreinte externe indépendante n'était fournie pour cette v4. Intégrité ZIP et correspondance aux manifestes internes : PASS.

Arbre déclaré dans le paquet : `bebb95bba231536331bcf80f658efddc99e44196` ; pas de comparaison à un dépôt distant.

| Contrôle | Reproduction indépendante |
|---|---|
| Manifeste principal | 179/179 entrées conformes |
| Manifeste détaché | 6/6 entrées conformes |
| Références | 8/8 entrées conformes |
| Fichier A01–A10 identique à l'audit initial | Oui, SHA-256 `bea463dba724f9c78389612d0481539a2e1c89eef0feea7117a66f8bb8a64adb` |
| A01–A10 | 10 réussites |
| Suite DS + trois fichiers hybrides ciblés | 163 réussites, aucun échec ni test ignoré |
| Restauration réelle dans un dossier neuf | 77 tests DS réussis ; 11 sorties régénérées identiques octet pour octet |
| Contrôle TypeScript de la page autonome | Réussi (`tsc --noEmit`) |
| Nouveaux tests de ressources V4-R01/R02/R03 + témoin | 3 échecs, 1 réussite |
| Test de conservation du terminal dans le dossier restauré | Échec |

Les fichiers JUnit, commandes exactes, journaux et empreintes figurent dans `evidence/`. Le succès du script de restauration ne prouve pas le transfert correct du compteur : ce dernier a été contrôlé séparément ci-dessous.

## 2. Correctifs acquis sur le périmètre testé
Les tests inchangés confirment : contradiction de disponibilité et obstacle en manuel non approuvables ; cumul des prêts sur des heures identiques refusé ; réservations tout-ou-rien en cas de refus ; conflit explicite des clés d'idempotence ; sortie à la demi-heure refusée ; nettoyage inconnu et planning inconnu traités explicitement ; changement des paramètres reflété dans les identifiants ; besoin IDE indépendant des offres disponibles.

Les tests supplémentaires livrés couvrent aussi le franchissement d'un seuil d'effectif de X2 et la comptabilité des admissions. Ils passent dans la suite. Il s'agit d'une vérification de ces exemples et assertions, pas d'une preuve universelle du moteur.

Les sorties nominales se régénèrent exactement : 1 040 minutes non couvertes en référence ; 905 avec la coordination de S01 seule ; 640 avec R1+R2 seuls ; 435 avec la combinaison ; 795 dans la branche sans R1 non confirmé. Les correctifs n'ont pas artificiellement amélioré ces valeurs. Elles restent des sorties d'une fixture, pas un bénéfice hospitalier réel.

## 3. Trois cas de ressources encore bloquants
### V4-R01 — Deux prêts qui se chevauchent échappent au cumul si leurs débuts sont décalés
**Reproduction.** Unité prêteuse : 4 IDE, minimum 3. R1 couvre 14 h–20 h à Paris ; R2 couvre 14 h 30–19 h 30. Les deux prêts se chevauchent, y compris pendant plusieurs heures complètes. Le contrat accepte ces horaires de renfort.

**Observé.** Trois plans contenant les deux prêts restent admissibles. Le plan automatique principal comprend S01, R1 et R2 ; `review` retourne `APPROVED_IN_DEMO`. Pendant le chevauchement, le prêteur conserverait 2 IDE au lieu du minimum déclaré de 3.

**Cause dans le code.** `resources.lending_violations` crée les clés à partir de chaque début de renfort puis ajoute une heure. Les clés 14 h / 15 h / … ne rencontrent jamais les clés 14 h 30 / 15 h 30 / … ; `_reservation_requests` répète cette grille décalée. Les contrats des verrous ont été corrigés, pas ceux des offres de renfort.

**Correction attendue.** Dans ce prototype horaire, refuser explicitement les fenêtres de renfort non alignées est suffisant. Sinon, utiliser une grille commune ou une vérification des intersections d'intervalles, conservatrice sur les engagements du prêteur. Ne pas arrondir silencieusement pour rendre l'offre favorable. Appliquer la même décision aux contrats, à l'énumération et à l'approbation.

Test : `tests/test_v4_resource_boundaries.py::test_b01_offgrid_loan_overlap_is_blocked`.

### V4-R02 — Une unité prêteuse inconnue n'empêche pas l'approbation
**Reproduction.** `source="shared_unit"`, effectif 4 et minimum 3 déclarés, mais `lending_unit=null`.

**Observé.** Aucun diagnostic de snapshot ; l'option peut être retenue et approuvée en auto ou en manuel. Les réservations ne contiennent aucun créneau `lend:...`. Le moteur ne peut pourtant pas identifier l'unité dont il doit cumuler les engagements.

**Cause.** `option_admissibility` vérifie les nombres mais pas l'identité du prêteur. `lending_violations` et `_reservation_requests` sautent le contrôle partagé lorsque l'identifiant est absent.

**Correction attendue.** Une offre `shared_unit` sans identité du prêteur doit être refusée explicitement ou rester hypothétique/non approuvable, même si des nombres d'effectif sont fournis. Les offres d'autres sources ne doivent pas être bloquées sans raison.

Test : `tests/test_v4_resource_boundaries.py::test_b02_shared_unit_requires_identified_lender`.

### V4-R03 — Une baisse de la marge de prêt n'est pas répercutée dans le registre existant
**Reproduction.** Premier instantané : 5 IDE, minimum 3 ; R1 est réservé, marge initiale 2. Un nouvel instantané corrige l'effectif à 4, minimum toujours 3 : la marge n'est plus que 1, déjà consommée par R1. On recalcule et soumet R2 sur ce nouvel instantané, en conservant le registre des engagements existants.

**Observé.** R2 est encore approuvé. Le registre conserve une capacité 2 et deux titulaires, alors que la marge actuelle est 1. Ce n'est pas la simple approbation d'une vieille recommandation : R2 a été recalculé avec le nouvel instantané.

**Cause.** `ResourceLedger.reserve_all` utilise `staged.capacity.setdefault((resource, slot), cap)` ; une capacité déjà mémorisée n'est donc jamais réduite par le nouveau contexte fourni.

**Correction attendue.** Réconcilier les capacités courantes et les engagements existants avant une nouvelle réservation, y compris une capacité devenue inconnue. Refuser l'engagement supplémentaire incompatible, garder les engagements antérieurs traçables et signaler leur éventuel conflit. Ne pas réécrire l'historique ni effacer arbitrairement les réservations existantes.

Test : `tests/test_v4_resource_boundaries.py::test_b03_new_snapshot_reconciles_capacity_with_existing_holds`.

**Témoin positif B04.** Dans un instantané inchangé, deux prêts aux mêmes heures sont bien gérés : le premier est approuvé, le second refusé, et les réservations du premier restent intactes. La correction initiale F02 n'est donc pas annulée ; il lui manque ces cas de bord.

## 4. V4-D01 — Le compteur réellement repris n'est pas le compteur terminal
Le registre terminal du paquet est complet et sa chaîne est valide : **105 lignes, 237,139 s**. Mais `source_head.tar` contient l'état antérieur : **102 lignes, 229,062 s**. Le dossier effectivement restauré contient lui aussi ces 102 lignes.

`python scripts/ds_budget_run.py --status` exécuté dans ce dossier affiche donc **229,062 s utilisées et 370,938 s restantes**, au lieu d'au moins **237,139 s utilisées et 362,861 s restantes**, avant même de comptabiliser le coût de la restauration. Les trois dernières commandes historiques, numéros 103–105, représentent **8,077 s**.

Le script `restore.sh` vérifie bien le terminal du **paquet**, puis extrait l'arbre ancien sans installer ce terminal dans le chemin utilisé par le runner du **dossier cible**. Son message `match=true` concerne donc le paquet, pas le compteur de reprise.

**Correction attendue.** Après extraction, installer de manière explicitement tracée le registre terminal et son ancre dans le chemin d'exécution cible, puis comptabiliser les nouvelles vérifications sans remettre le compteur à zéro. Tester le `--status` du dossier cible et la présence du terminal comme préfixe exact de son historique. L'arbre de code peut rester identique ; le registre d'exécution est un état de reprise distinct.

Test : `tests/test_v4_restoration_counter.py`, à lancer après une vraie restauration avec `AUDIT_PACKAGE` et `AUDIT_RESTORED`. Le test échoue ici sur **102 < 105**. Aucun calcul scientifique ni source produit n'est perdu : c'est un défaut de transfert du suivi de consommation.

## 5. React, Python et divergence entre les deux rapports
**React.** L'intégration n'est plus seulement une page autonome : `web/src/App.tsx` importe `DecisionPlan`, déclare « Plan 24 h » et la route `#/plan`, puis rend le composant. Les sources de l'interface, de ses tests et les journaux de l'auteur sont présents. Les 72 tests Vitest, 17 contrôles e2e React et 19 contrôles autonomes sont des résultats de l'auteur, pas des résultats navigateur réexécutés ici. Aucune installation réseau n'a été faite ; le paquet restauré ne contient ni `node_modules` ni `web/dist`.

**Python.** L'audit présent a exécuté sous **Python 3.13.5**. Le paquet v4 contient bien un addendum, le journal d'installation, un inventaire de dépendances et un JUnit annonçant **163 réussites sous 3.11.18**, plus la comparaison des 11 sorties. Cette exécution de l'auteur n'a pas été reproduite sous 3.11 ici. La version exacte 3.11.9 demandée par `.python-version` reste non testée dans ces preuves.

Le `CORRECTIONS_REPORT.md` joint séparément (8 007 octets) est plus ancien que `docs/CORRECTIONS_REPORT.md` dans la v4 (9 095 octets). Le premier dit encore que les dépendances de Python 3.11 manquent ; le second contient le §8 d'exécution et corrige le §6. Cette divergence est documentaire : utiliser le rapport interne de v4 pour décrire l'état annoncé par l'auteur, sans lui attribuer une validation indépendante.

`test_decision_guard.py` reste volontairement hors de cette recette : l'ajustement de modèles mentionné dans son chemin d'exécution n'est pas autorisé par ce ré-audit. Pas de `mypy --strict` ni de test React indépendant ici.

## 6. Suite recommandée
Un correctif **ressources + restauration**, sans nouvelle architecture : couvrir V4-R01/R02/R03 et V4-D01, préserver A01–A10 et les 163 tests, conserver les scénarios nominaux et les résultats conditionnels. Puis refaire la clôture technique et les contrôles du cockpit sur l'environnement approuvé. Ni nouvelle campagne P5/P6, ni reprise d'A_detached, ni grand entraînement.

Ces contrôles ne sont pas une preuve exhaustive de sécurité ou de qualité prédictive. Ils démontrent les cas explicitement rejoués et les contre-exemples livrés.

## 7. Budget et restauration de l'audit
Point de départ conservateur et vérifié : **237,139 s**. Audit supplémentaire comptabilisé : **22.885 s**. Total de la lignée livrée ici : **260.024 s**, reliquat **339.976 s** sur 600. Plafond de commande : 30 s. L'audit a travaillé avec une copie du registre terminal, pas avec le compteur sous-évalué du dossier restauré.

`evidence/BUDGET_LEDGER.jsonl` et son ancre prolongent le terminal de la v4. Si d'autres exécutions ont été effectuées ailleurs, il faudra réconcilier les branches de preuves avant toute reprise, sans perdre ni compter deux fois cet audit `HospitalOS_DS_v4_independent_20261114`. Ces chiffres ne constituent pas une nouvelle autorisation de calcul.
