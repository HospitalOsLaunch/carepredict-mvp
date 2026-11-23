# HospitalOS — Ré-audit indépendant de la v6

14 novembre 2026. Périmètre : clôture du défaut V5-R01 (capacité du prêteur dépendant de l'offre approuvée), non-régression et restauration. Aucun changement du code produit.

## 1. Verdict

**V5-R01 : corrigé et confirmé indépendamment sur les cas testés. Aucun nouveau défaut du produit n'a été reproduit dans ce périmètre.**

Les 182 tests livrés ciblés passent ici sans test ignoré, dont les tests indépendants A/B/C conservés à l'identique. Les neuf contrôles complémentaires de capacité passent également. La restauration exécute 96 tests et reproduit les 11 fichiers de résultats octet pour octet ; les 96 tests ne s'ajoutent pas aux 182, ils en constituent un sous-ensemble.

**Le défaut ciblé peut être clos.** Le statut global reste `PARTIAL_WITH_CHECKPOINT` au regard des réserves d'environnement prévues : Python exact 3.11.9 et tests React/navigateur indépendants non exécutés ici. Cette réserve n'est pas un nouveau défaut de logique des prêts de personnel. Aucun lot de correction supplémentaire de ce mécanisme n'est demandé sur la base de cet audit.

Statuts scientifiques inchangés : `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`. P5/P6 restent fermés, aucun entraînement autorisé ou exécuté par ce reçu.

## 2. Entrée et intégrité

- Archive : `HospitalOS_DS_P0-P4_20261114_v6.zip` ; 27135979 octets.
- SHA-256 calculé : `4fca8aecde4fa35a47bc18696785d28df7465b5191b48e8a2881b0ec1e117f90`.
- Arbre livré : `856a57c65fb0d55190addf6c39a45c57913eac07`.
- ZIP : CRC conformes, chemins sans traversée ; extraction isolée. Arbre TAR inspecté : uniquement fichiers réguliers et répertoires.
- Manifestes : 259/259 principaux, 6/6 post-scellement, 6/6 finaux, 8/8 références conformes.
- `CORRECTIONS_REPORT (2).md`, rapport du paquet et rapport de l'arbre source identiques octet pour octet.
- Les quatre fichiers de tests indépendants A, B, compteur et C ont les empreintes d'origine. Les sources produit n'ont pas été modifiées durant cet audit.

## 3. Preuves exécutées ici

| Contrôle | Résultat indépendant |
|---|---|
| `tests/decision_support` + `test_mvp.py`, `test_pathway.py`, `test_future.py` | **182 réussis, 0 échec, 0 erreur, 0 ignoré** |
| Restauration réelle, environnement `AUDIT_PACKAGE` et `AUDIT_RESTORED` renseigné | **96 réussis**, 11 fichiers identiques |
| Compteur de la cible | Registre final du paquet installé ; préfixe exact conservé après les vérifications |
| Neuf contrôles complémentaires sur la capacité canonique | **9 réussis** |
| TypeScript de la page autonome | Réussi, `--noEmit` |
| Rejeu React / navigateur indépendant | Non exécuté : dépendances du cockpit absentes, aucune installation réseau |

Au total : 191 tests distincts réussis après finalisation de la suite supplémentaire. A01–A10, B01–B04, C01–C04 et les tests de restauration ne sont pas additionnés une seconde fois.

### Transparence sur la préparation des tests indépendants

Le premier passage de mes neuf contrôles supplémentaires a donné 7 échecs et 2 réussites. Il s'agissait d'une erreur dans mes assertions : elles incluaient les capacités d'un prêteur tiers (`U-CARDIO-SYN`, offre R3) alors que l'oracle ne concernait que `U-LOAN/IDE`. Le dictionnaire indexé seulement par heure mélangeait également ces prêteurs.

J'ai borné les assertions à `U-LOAN/IDE` ; les calculs du produit conservent l'instantané complet. Aucun code produit, observation de la fixture ou test d'auteur n'a été changé. Les neuf tests passent après cette correction. Le fichier initial, le JUnit rouge et le journal sont conservés dans `evidence/`. Ces échecs initiaux ne sont pas présentés comme des défauts de v6.

## 4. V5-R01 : reproduction exacte et résultat

Même instantané, même unité prêteuse `U-LOAN`, compétence IDE, créneau 14–20 h Paris le 17 novembre 2026. R1 déclare 4 IDE / minimum 3 ; R2 déclare 5 IDE / minimum 3. Les déclarations simultanées sont contradictoires.

| Parcours | Résultat v6 reproduit |
|---|---|
| R1 + R2 dans le même plan | Combinaison non admissible |
| Approuver R1 puis R2 | `APPROVED_IN_DEMO`, puis `REFUSED` |
| Approuver R2 puis R1 | `APPROVED_IN_DEMO`, puis `REFUSED` |
| Engagement du premier prêt après le refus du second | Conservé dans les deux ordres |

La capacité partagée est **1** dans les deux parcours, selon la règle explicite `min_scheduled - max_minimum`, soit min(4,5) − max(3,3). La provenance inclut l'empreinte d'instantané, la politique prudente et les deux offres. La dernière offre approuvée ne remplace plus la capacité commune.

La relecture des sources confirme l'utilisation de cette capacité par les candidats, les préconditions, les verrous, les invariants du simulateur et les réservations. Les cinq modules modifiés sont conservés dans `reference_extracts/`.

Cette politique est une convention prudente du prototype. Elle ne prouve pas que la valeur réelle de l'effectif est connue ; l'incohérence doit rester signalée à l'utilisateur. Les tests positifs C02/C03/C04 conservent la possibilité de deux prêts lorsque la capacité concorde, d'une hausse justifiée dans un nouvel instantané et de capacités différentes sur des créneaux disjoints.

## 5. Contrôles complémentaires bornés

Les neuf tests supplémentaires vérifient :

- permutation de l'ordre des offres dans la construction de la capacité ;
- minima contradictoires, dans les deux ordres d'approbation ;
- effectif ou minimum inconnu dans une offre non sélectionnée du même prêteur ;
- chevauchement partiel sur des horaires entiers, dans les deux ordres ;
- prêts de deux unités différentes, qui doivent rester distincts ;
- deux écritures de fuseau horaire représentant les mêmes instants.

Ils passent tous après correction de l'erreur de périmètre de mes assertions. Ce sont des tests fonctionnels synthétiques, pas une campagne statistique, ni une preuve générale d'absence de bogue ou de concurrence distribuée sûre.

## 6. Résultats nominaux conservés

Les 11 documents régénérés sont identiques aux 11 documents de la v6 livrée. Sur la fixture nominale, les minutes de soins non couvertes restent :

| Plan | Minutes non couvertes | Attente cumulée, patients·h |
|---|---:|---:|
| Pratique habituelle | 1040 | 21,5 |
| Coordination S01 à 10 h seule | 905 | 14,5 |
| Renforts R1 + R2 seuls | 640 | 21,5 |
| Coordination + R1 + R2 | 435 | 14,5 |
| Coordination + R2, sans R1 non confirmé | 795 | 14,5 |

Ce sont des sorties du démonstrateur synthétique ; aucune nouvelle précision prédictive, généralisation, calibration réelle ou efficacité clinique n'est démontrée. La v6 améliore la cohérence des contraintes, pas un réseau appris.

## 7. Restauration et lignée de budget

| Étape | Enregistrements | Consommation cumulée |
|---|---:|---:|
| Final livré avec v6 | 166 | 396,451 s |
| Fin de cet audit | 175 | 421,325 s |
| Ajout indépendant | 9 | 24,874 s |
| Reliquat au plafond de 600 s | — | 178,675 s |

Les 166 enregistrements de la v6 restent un préfixe exact. La lignée de l'audit précédent (146 enregistrements) est également confirmée par son empreinte terminale. Les commandes internes de restauration sont déjà imputées ; seule l'enveloppe extérieure supplémentaire est ajoutée, sans double comptage. Le premier passage erroné de mes tests supplémentaires est conservé et imputé.

Dernière empreinte : `9056a4a1052d0ab1deb6be7a6befa37704b61d05a43c1088187c071811c8b973`.

Le registre complet, son ancre, le registre source v6 et les nouveaux journaux sont fournis dans ce dossier. Ne pas reprendre le compteur de construction de l'arbre, ni réappliquer un ancien registre par-dessus une lignée plus récente. L'audit suit le budget déclaré des commandes de tests et de vérification exécutables ; le temps de lecture et de rédaction n'est pas un temps d'entraînement.

## 8. Environnements et réserves exactes

Rejeu indépendant : Python **3.13.5**, Pydantic **2.13.5**, NumPy **2.3.5**, pytest **9.0.2**, jsonschema **4.26.0**, plugins automatiques pytest désactivés. Le Python exact **3.11.9** n'est pas disponible dans cet environnement ; aucune installation n'a été tentée.

Les JUnit d'auteur sous 3.11.18 et 3.13 présents dans le paquet comportent chacun 182 tests, dont 1 ignoré : **181 réussis**. Le test ignoré est celui du compteur, prévu pour une vraie restauration. Ici, les variables de restauration réelle étaient fournies, d'où **182 réussis sans ignoré**. Il ne s'agit pas d'une augmentation artificielle du nombre de tests.

Les 72 tests Vitest, les 17 vérifications navigateur React et les 19 autonomes restent des preuves d'auteur annoncées et accompagnées de journaux ; je ne les ai pas réexécutés. Le typecheck autonome ne les remplace pas. `mypy --strict` n'est pas exécuté. `test_decision_guard.py` est exclu, car il ajuste des modèles et sort du mandat sans entraînement.

Petite mise à jour documentaire à faire lors de la prochaine clôture : une phrase de `STATUS.json/open_gates` conserve le compteur historique 163 sous Python 3.11.18 alors que le bloc de résultats et le rapport v6 donnent 181 réussis + 1 ignoré. Ce décalage de résumé ne change ni les JUnit ni le résultat de cet audit.

## 9. Suite proposée, non exécutée

1. Enregistrer la clôture indépendante **de V5-R01 et des contre-exemples couverts**, sans renommer tout P0–P4 en validation clinique ou scientifique.
2. Terminer la vérification du cockpit dans l'environnement disposant des dépendances autorisées et traiter formellement la version Python de référence (vérifier 3.11.9, ou décider explicitement de modifier la référence avant de la retester). Aucune installation n'est autorisée par ce document.
3. Préparer le protocole P5 et son budget séparé ; ne pas l'exécuter ni entraîner de modèle avant autorisation distincte.

La v6 peut servir de référence conservée pour ces dernières vérifications. **Cet audit ne demande pas une v7 du moteur de ressources faute de défaut nouveau reproduit.** Il ne promet pas qu'aucun autre défaut n'existe ; sa portée est le contrat et les cas contrôlés.
