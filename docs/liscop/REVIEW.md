# Revue de `feat/liscop-ars` (2 novembre 2026) et plan de correction

Trois revues indépendantes, en lecture seule : qualité du code, sécurité, tests et CI.
Chaque constat ci-dessous a été reproduit par le relecteur (sonde ou test). Deux agents
corrigent, sur des fichiers disjoints : `fix-ingest` (mouvements, sécurité, agent) et
`fix-platform` (définitions urgences, prévision, export, CI, simplifications).

## `fix-ingest` — branche `feat/liscop-3-fix-ingest`

| # | Gravité | Constat | Correction attendue |
|---|---|---|---|
| S-H1 | Haute | MSH-10 réutilisé avec un autre contenu : AA « déjà reçu » et mouvement perdu (`movement_service.py:66-73`) | Comparer l'empreinte ; si différente : AE « MSH-10 réutilisé avec un contenu différent », journalisé. Lier chaque compte `ingestion` à une liste de `source_system` autorisés (réglage du groupe ou de l'utilisateur ; refus sinon) |
| S-H2 | Haute | Pseudonymes NDA/IPP sans domaine d'identification : deux établissements, même NDA → patients fusionnés (`pseudonym.py:24`, `movement_service.py:76-78,143,344,384`) | Inclure le domaine (autorité d'affectation PV1-19.4 / PID-3.4, sinon `source_system`) dans l'entrée HMAC ; refuser (AE) un mouvement dont le patient diffère de celui de la venue |
| S-H3 | Haute | Empreinte SHA-256 non clé du JSON agent contenant IPP/NDA en clair (`routes_hl7.py:152,168`) | Empreinte HMAC (clé dérivée distincte) sur le message, ou calculée après remplacement des identifiants par leurs pseudonymes ; idem pour le message HL7 ; corriger `HL7_PAM.md` |
| S-M1 | Moyenne | Horodatages extrêmes / octets NUL → 500 sans ACK (`hl7_pam.py:141,193,197-203`) | `ValueError`/`OverflowError` → AE 102 ; rejeter les caractères de contrôle C0 ; borner `occurred_at` (ex. −400 j / +1 j, réglable) |
| S-M2 | Moyenne | L'agent recopie du texte d'écran brut (noms possibles) dans les erreurs visibles (`playbook.py:179`, `api_client.py:63`, `router.py:258-265,297`) ; les 422 renvoient l'entrée pydantic | Jamais la valeur brute : nom du champ + format attendu ; gestionnaire `RequestValidationError` qui retire `input`/`ctx` (au moins sur `/ingest/*`) |
| S-M3 | Moyenne | Clé de pseudonymisation de développement acceptée si `ADM_ENV` ≠ `production` exact (`config.py:54,93,95`) | Échouer fermé : clés de dev refusées sauf `ADM_ENV` ∈ {development, test} et base SQLite ; même règle pour `seed-demo*` |
| S-L1 | Basse | Valeurs brutes de l'émetteur recopiées dans ACK/journal (`hl7_pam.py:233,276`, `movement_service.py:212`) | Messages fixes avec l'emplacement HL7 ; au plus un jeton tronqué `[A-Z0-9]` |
| S-L2 | Basse | `AGENT_API_URL` accepte `http://` (`admissions_agent/config.py:66`) | Refuser hors https sauf boucle locale / nom interne compose |
| S-L3 | Basse | Une seule clé HMAC pour tous les groupes, sans version | Clé par groupe dérivée (HKDF-SHA256 de la clé maître et du group_id) ; préfixe de version dans le pseudonyme ou constante documentée |
| S-L5 | Basse | Analyse HL7 faite sous le verrou d'écriture du groupe (`routes_hl7.py:95-103`) | Parser avant de prendre le verrou |
| T-4 | Haute | ZBE-5 = Y (mouvement historique) accepté | Refuser (AE) sauf correction Z99 ; test |
| T-5 | Haute | Annulation renvoyée sous un nouveau MSH-10 → AE au lieu de doublon (`movement_service.py:121-135`) | Reconnaître le doublon (même ZBE-1 et même action) → AA `duplicate` ; test |
| T-16 | Basse | Mouvement daté dans le futur accepté | Couvert par la borne de S-M1 ; test |
| C-1 | Haute | « Hébergés » inversé : A01/A06 écrase l'unité cible de la décision (`hl7_pam.py:432`) | Conserver la cible de la décision ; test du cas d'école (décision ortho, admission en médecine) |
| C-2 | Haute | Réadmission le même jour rejetée par l'ancienne clé unique SMR (`movement_service.py:364-373`, `models.py:151`) | Rendre l'index unique partiel (`encounter_ref IS NULL`) dans la migration 0003 (non publiée : la modifier) ; supprimer la requête de conflit ; test |
| C-3 | Haute | Demande SMR avec code MCO → 500 `KeyError` (`routes_requests.py:210`) | Les demandes SMR restent sur `MENTIONS` (schéma `RequestCreate`) ; `StayCreate` sur `UNIT_CODES` ; test |
| C-4 | Haute | 2–3 balayages du journal par message sous verrou (pas d'index) | Index (`group_id`,`encounter_ref`) et (`group_id`,`source_system`,`movement_ref`) dans 0003 |
| C-5 | Moyenne | Une admission HL7 efface un blocage de lit, qui redevient « libre » après la sortie | Lit bloqué : enregistrer le séjour sans lit avec avertissement (comme un lit occupé) |
| C-7 | Moyenne | Une ligne invalide bloque toute la synchronisation agent (`routes_hl7.py:176`) | Validation par élément côté serveur, rejet par ligne ; l'agent continue |
| C-9 | Basse | `_release` ne met pas à jour `beds.updated_at` | `bed.updated_at = now` |
| T-6/7/8 | Haute | Pas de tests : annulations en chaîne, branches d'erreur Z99, rien de partiel après rejet | Ajouter les tests nommés dans le rapport de tests |
| T-13 | Moyenne | Isolation des tenants non testée sur `/movements` et sur une annulation d'un autre groupe | Tests |
| T-15 | Moyenne | Heure inexistante du passage à l'heure d'été non épinglée | Test |
| T-17 | Basse | Concurrence sur un même MSH-10 non testée | Test PostgreSQL à deux fils si faisable, sinon gestion propre de l'`IntegrityError` → AA `duplicate` |
| T-18 | Basse | `demo_bedsoft` utilise l'horloge réelle | Horloge injectable, figée dans le test |
| Simpl. | — | `_sex_warnings` réimplémente `domain.beds.accepted_sexes` | Réutiliser le domaine |

## `fix-platform` — branche `feat/liscop-3-fix-platform`

| # | Gravité | Constat | Correction attendue |
|---|---|---|---|
| T-2 / C-10 | Haute | Trois définitions de « présent / en attente / brancards à 10 h » (`forecast_engine/data.py:123-135,154` vs `domain/ed.py:91`) | Une seule définition dans `domain/ed.py` ; le moteur l'importe ; test d'équivalence sur visites aléatoires couvrant les deux changements d'heure |
| T-1 | Critique | Critère (c) du backtest : borne flottante exclut 75 % (`backtest.py:253`) ; `backtest.py` non testé | Comparaison inclusive robuste ; tests des règles des critères, des origines et de la rupture ; **ne pas relancer ni réécrire les résultats publiés** ; ajouter dans `BACKTEST.md` un erratum daté (le verdict publié de (c) reste « réussi », il était juste) |
| T-3 | Haute | Tests du moteur en échec sur PostgreSQL (fixture de session partagée) | `demo_engine` sur son propre fichier SQLite |
| T-9 | Haute | Contrat moteur → base → API jamais exercé | Test : `compute` → `save_run` → `/api/forecast/liscop` et `/api/ror/export` (« disponibles attendus », J+1/J+2/J+7) |
| T-10 | Moyenne | Chemin d'échec du moteur non testé | Tests (run échoué journalisé, dernier bon run servi ; groupes suivants traités) |
| T-11 / C-6 | Moyenne | J+n relatif à `as_of` sur la page Prévision mais à aujourd'hui dans l'export ROR | Une seule fonction d'étiquetage relative à aujourd'hui ; tests run périmé et unités absentes du run |
| T-12 | Moyenne | Garde CSV incomplète (`domain/oru.py:189`) | Neutraliser aussi `\t` et `\r` en tête ; tests |
| T-13 | Moyenne | Isolation non testée sur `/beds/availability`, `/ed/boarding`, `GET /ed/snapshots` | Tests |
| T-14 | Moyenne | Pas de couverture des changements d'heure dans les séries du moteur | Test |
| C-8 | Moyenne | `POST /ror/outbox` construit l'export sous le verrou d'écriture | Construire en lecture, verrouiller seulement pour l'insertion |
| S-M4 | Moyenne | Le moteur charge tous les secrets et migre la base ; dépendances non épinglées | Chargeur de réglages minimal (URL de base, fuseau) ; plus de migration au lancement (le moteur vérifie la révision et s'arrête si elle manque) ; versions exactes dans `forecast_engine/requirements.txt` ; documenter le rôle base dédié (SELECT + INSERT `forecast_*`) |
| S-L4 | Basse | Motifs libres de blocage de lit (noms possibles) visibles et audités | Liste de motifs codés (vocab) + texte libre court hors audit |
| S-L6 | Basse | L'AIPD ne couvre pas les nouvelles données | Mettre à jour `docs/AIPD.md` (catégories, durées de conservation) ; tâche de purge documentée |
| T-19 | Basse | Rétrogradation 0003 testée seulement à vide | Test avec lit et séjour liés |
| T-20 | Basse | Pages : run périmé et erreur API non rendus en test | Tests web |
| CI | Haute | La CI ne lance ni les tests ni mypy du moteur ; démo sans contrôle LISCOP | Modifs du rapport de tests : install `forecast_engine/requirements.txt`, mypy incluant le moteur, tests moteur SQLite + PostgreSQL, `tools/tests`, `testpaths`, build de l'image moteur ; `tools/demo_check.py` étendu (HL7 AA, prévision présente, export « disponibles attendus », census et disponibilités 200) ; CI et images restent en Python 3.11 |
| Simpl. | — | Anciens `Ror*` dans `schemas.py` et `types.ts` ; réexports de `domain/ror.py` ; imports entre routes ; six fonctions d'heure locale ; `build_forecast` appelé pour `.model`/`.slip` seulement ; `SCOPES`/`TARGETS` en double | Supprimer, déplacer vers un module de service et `vocab`, une seule aide d'heure locale, appeler `fit_hazard`/`estimate_plan_slip` directement |

Hors correction (noté pour le pilote) : CVE des dépendances non vérifiées (proxy) ;
`demo_bedsoft` n'est jamais déployé ; rôle base dédié et purge à mettre en œuvre à
l'hébergement HDS.
