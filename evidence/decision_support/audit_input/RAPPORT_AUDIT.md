# HospitalOS — audit indépendant de la livraison DS P0–P4

**14 novembre 2026 — revue de code, restauration et contre-exemples exécutés.**

## Verdict

**Conserver le travail livré, mais ne pas accepter la clôture P0–P4 en l’état.** La livraison est restaurable et les résultats nominaux sont reproductibles. Des défauts de contraintes, de réservation et de traçabilité passent cependant au travers des tests fournis. Mon statut recommandé est **`PARTIAL_WITH_CHECKPOINT`**. Il s’agit du verdict de cet audit ; le `STATUS.json` original, qui annonce `P0_P4_TECHNICAL_PASS`, n’a pas été modifié.

Le statut scientifique reste `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`. Aucun résultat présenté ici n’est une mesure d’efficacité clinique ou opérationnelle réelle.

La prochaine étape n’est plus seulement « intégrer la page au cockpit React ». Il faut d’abord un correctif ciblé du moteur et de la revue des décisions (**P2/P3bis**), puis la clôture de l’intégration (**P4bis**). Les campagnes P5/P6 restent fermées.

## 1. Pièce réellement inspectée

- Archive : `HospitalOS_DS_P0-P4_20261114.zip`, 12 733 073 octets.
- SHA-256 recalculé : `431e2e446def7f244603d4541eb68dc42a4adbd7fbc39055f931c9c1704cda4e`.
- L’empreinte est identique à celle annoncée dans la conversation. Elle garantit cette correspondance d’octets, pas une signature indépendante de l’auteur.
- Arbre livré : `d7844ea760505b57cbf31d1a3f8ae179eac30d85` selon `HEAD.txt`, le commentaire PAX du TAR et le dernier patch. La branche finale `282ee85` annoncée dans le compte rendu n’est pas incluse dans la série de huit patches.
- Extraction isolée : chemins relatifs contrôlés, doublons refusés, pas de liens ni de fichiers spéciaux dans le TAR. Vérification CRC du ZIP réussie.
- Tous les fichiers originaux de l’arbre extrait sont restés identiques aux octets du TAR après les contrôles. Les nouveaux tests et preuves résident hors de cet arbre.

L’audit est fondé sur cette archive et son plan de référence. Aucun dépôt distant ni résultat d’une autre conversation n’a servi à remplacer ses contenus.

## 2. Contrôles indépendants exécutés

| Contrôle | Résultat indépendant |
|---|---|
| Manifeste principal `SHA256SUMS` | 88 entrées sur 88 conformes |
| Manifeste détaché `SHA256SUMS.post` | 4 entrées sur 4 conformes |
| Références `reference/SHA256SUMS.txt` | 8 entrées sur 8 conformes ; comptage séparé, pas une affirmation de 100 fichiers uniques |
| Tests `tests/decision_support` | **44 réussis** |
| Non-régression hybride : `test_mvp`, `test_pathway`, `test_future` | **86 réussis** |
| Restauration T30 dans un dossier neuf | Tests réussis ; **11 résultats régénérés identiques octet par octet** |
| Altération volontaire de `docs/NEXT_STEP.md` dans une copie du paquet | `restore.sh` s’arrête avec le code 2 ; aucun dossier cible créé |
| TypeScript `tsc ... --noEmit` | Réussi |
| Nouveaux contrôles indépendants A01–A10 | **9 échecs et 1 réussite** sur l’arbre livré |
| Contrôles navigateur | Non revalidés : navigation locale bloquée par l’environnement (`ERR_BLOCKED_BY_ADMINISTRATOR`) |

Les dix tests supplémentaires sont des contre-exemples ciblés et un contrôle positif. Ils ne constituent ni une campagne statistique ni un échantillon représentatif d’hôpitaux. Leurs échecs ne contredisent pas la réussite des 44 tests initiaux : ils montrent ce que ces derniers ne couvrent pas.

### Conditions d’exécution

Python **3.13.5**, Pydantic 2.13.5, NumPy 2.3.5, pytest 9.0.2. Le dépôt fixe **3.11.9** : cette compatibilité reste à vérifier. `mypy` et `ruff` n’étaient pas disponibles dans l’environnement d’audit ; aucune installation réseau n’a été effectuée.

Le test historique `test_decision_guard.py` n’a pas été lancé : sa fixture `models()` appelle `fit_benchmark()`. La présence locale de scikit-learn ne constitue pas une autorisation de relancer cet apprentissage.

Le rejeu e2e a adapté uniquement les chemins du lanceur, l’emplacement des sorties et l’exécutable Chromium préinstallé ; les assertions n’ont pas été changées. La première navigation a été bloquée par la politique de l’environnement. Aucune tentative de contournement n’a suivi, et le serveur local a été arrêté. Les captures **livrées** ont été consultées, mais elles ne sont pas de nouvelles captures de validation indépendante.

## 3. Défauts reproduits

### F01 — Les verrous manuels contournent certaines préconditions

**Priorité : bloquant pour l’acceptation technique de la validation des plans. Tests A01 et A02.**

Deux variantes ont été construites via les observations publiques puis `build_snapshot`, sans falsifier manuellement un état Pydantic :

1. Sortie de S01 verrouillée à 10 h, alors que l’estimation publique de disponibilité la plus précoce est fixée à 18 h avec un délai nul. Le moteur signale `ready_after_locked_hour`, mais n’en fait qu’un avertissement. Le scénario reste `approvable=true` et la revue retourne `APPROVED_IN_DEMO`.
2. Ajout d’un obstacle logistique actif `destination_unavailable` pour S01. Une sortie manuelle déclarée `validated_instruction` ignore cet obstacle ; le scénario reste approuvable, sans violation ni avertissement, et la revue retourne également `APPROVED_IN_DEMO`.

Ces observations ne signifient pas qu’une autorisation médicale a réellement été contournée sur le terrain : ce sont des sorties synthétiques du moteur de démonstration. L’erreur est la confusion entre une hypothèse que l’on peut explorer et un plan que le système déclare admissible et approuvable.

**Source :** `reference_forecaster.py:206–214` (les branches verrouillées ne réutilisent pas `eligible_for_auto_discharge`), à comparer aux lignes 215–218 pour l’automatique ; `planner.py:667–680` ne revalide les obstacles que lorsque l’empreinte a changé, et non systématiquement pour un scénario construit sur un état déjà bloqué.

**Correction attendue :** préserver les verrous, mais évaluer les mêmes contraintes dures dans les deux modes. Une hypothèse contredisant une disponibilité estimée peut rester simulable avec une hypothèse explicite ; elle ne doit pas être approuvée comme si la précondition était satisfaite. Un obstacle opérationnel actif doit être levé par une information autorisée ou rendre le plan non approuvable. Ne pas modifier silencieusement l’heure imposée.

### F02 — Deux prêts de personnel peuvent violer ensemble le minimum de l’unité prêteuse

**Priorité : bloquant pour les ressources. Test A03.**

Dans le contre-exemple, une unité prêteuse dispose de **4 IDE** et doit en conserver **3**. Deux options R1/R2 empruntent chacune une IDE sur le même créneau. Chaque option passe le contrôle individuel `4 - 1 >= 3`. La combinaison en retire deux, laisse **2 IDE**, mais reste déclarée admissible. Elle est même choisie dans le plan prioritaire et reçoit `APPROVED_IN_DEMO`.

**Source :** `resources.py:27–48` contrôle chaque option séparément ; `candidates.py` combine les options sans vérification cumulative de la capacité de la même unité sur chaque créneau. Les invariants de `reference_forecaster.py` ne rétablissent pas ce contrôle.

**Correction attendue :** calculer les engagements cumulés du plan par unité prêteuse, compétence et fenêtre temporelle, en incluant les engagements déjà réservés. Les deux options peuvent rester disponibles séparément ; leur combinaison doit être rejetée si elle franchit le minimum. Ajouter un cas où les prêts sont décalés et restent légitimes.

### F03 — Un plan refusé laisse des réservations actives

**Priorité : bloquant pour le workflow. Test A04.**

Avant l’approbation, R1 est réservé par une autre demande. La revue commence par réserver le transport, échoue sur R1, puis réserve encore R2. Le résultat final est `REFUSED`, mais le registre conserve les deux nouvelles réservations : transport et R2. Le plan refusé peut donc bloquer les suivants.

**Source :** `planner.py:684–698`. Les réservations sont écrites au fil de la boucle ; aucun retour arrière n’est prévu lorsqu’une réservation échoue.

**Correction attendue :** transaction « tout ou rien », ou phase de vérification puis engagement atomique. Après un refus, les réservations préexistantes doivent être intactes et aucune réservation nouvelle de ce plan ne doit subsister. Ajouter un cas concurrent et un cas de relance de la même demande.

### F04 — Une même clé peut rejouer une approbation pour une autre décision

**Priorité : importante. Test A05.**

Appeler `review(..., decision='approve', idempotency_key='shared-key')`, puis `review(..., decision='reject', idempotency_key='shared-key')`, renvoie la première approbation : `decision='approve'`, `outcome='APPROVED_IN_DEMO'`.

**Source :** `planner.py:651–652`, cache consulté avant toute comparaison du contenu de la requête. Le frontend actuel inclut la décision dans sa clé (`decision.ts:171`), ce qui réduit l’exposition de ce cas par les boutons habituels ; le contrat du moteur reste néanmoins incorrect face à une réutilisation incohérente.

**Correction attendue :** associer la clé à l’empreinte canonique de la recommandation et de la décision. Même contenu : résultat idempotent. Contenu différent : conflit explicite, jamais une réussite empruntée à une autre demande. Distinguer également reçu historique et validité actuelle après une nouvelle information.

### F05 — Une heure manuelle à la minute est arrondie silencieusement à l’heure précédente

**Priorité : bloquant pour la fidélité des scénarios. Test A06.**

Une sortie verrouillée à **10 h 30, heure de Paris**, est acceptée. L’action conserve 10 h 30, mais le journal simulé la place à **10 h 00**. Le scénario reste approuvable sans avertissement.

**Source :** `resources.py:19–20`, conversion par `math.floor` ; les contrats des verrous ne refusent pas cette précision non prise en charge. La contrainte d’heure entière ne porte que sur `PublicSnapshot.as_of`.

**Correction attendue :** soit gérer les événements à cette précision, soit refuser explicitement les horaires non pris en charge dès le contrat et dans l’interface. Pour une clôture étroite, le refus des heures non entières est suffisant. Ne jamais avancer silencieusement un événement verrouillé.

### F06 — Une durée de nettoyage inconnue est remplacée silencieusement par une heure

**Priorité : importante pour les hypothèses. Test A07.**

Retirer `cleaning_hours` du lit occupé L01 n’ajoute aucune anomalie au snapshot. Le moteur recommande toujours la sortie ; après le départ, il utilise une durée de nettoyage de **1 h**, sans signaler l’absence de donnée ni identifier cette valeur comme une hypothèse de remplacement.

**Source :** `reference_forecaster.py:282`, `beds[bed_id].cleaning or Distribution.point(1)`. Le contrôle de `snapshot.py` ne couvre cette absence que pour les lits déjà sales ou en nettoyage, pas ceux qui vont être libérés.

**Correction attendue :** abstention ciblée, ou distribution de remplacement explicitement configurée et versionnée, avec provenance et avertissement dans la recommandation. Une valeur par défaut peut être un choix de démonstration, mais pas une donnée connue implicitement inventée.

### F07 — Une compétence avec demande connue mais planning inconnu est assimilée à zéro présent

**Priorité : importante pour l’abstention. Test A08.**

Ajout d’un besoin AS sur S01, sans aucune déclaration de couverture du planning AS. Le moteur continue avec `RECOMMENDATION_READY`, `approvable=true` et aucun diagnostic. Le manque d’information sur le planning AS n’est pas distingué d’un effectif réellement nul.

**Source :** `_data_gaps()` dans `planner.py` contrôle la couverture du planning IDE uniquement, alors que `reference_forecaster.py` calcule IDE et AS.

**Correction attendue :** vérifier les données de présence pour chaque compétence effectivement requise, ou refuser explicitement les compétences hors périmètre. Un scénario conditionnel « supposons zéro AS » doit rester une hypothèse nommée, non une conversion silencieuse de l’inconnu.

### F08 — Les identifiants de documents ne changent pas lorsque la formule change

**Priorité : importante pour la traçabilité. Test A09.**

Sur le même snapshot, changer uniquement le diviseur de charge dans les coefficients du score change la trajectoire calculée. Le test obtient par exemple **9 puis 4** pour le premier point, mais la recommandation et le bundle gardent exactement les mêmes identifiants. L’empreinte de formule dans `bundle.score` change bien : le contrôle n’est simplement pas inclus dans les identités des documents.

**Source :** `planner.py:173–181` et `230–234`. La construction des IDs ne contient pas l’empreinte complète du score/configuration. `State.keep` du serveur remplace un document de même ID ; les pointeurs de provenance ne suffisent donc pas à garantir une version immuable si ces paramètres évoluent.

**Correction attendue :** empreintes de configurations complètes, backend/code, horizon et seeds pertinents dans l’identité des résultats, ou un stockage immuable adressé par contenu. Un même identifiant ne doit jamais désigner deux sorties différentes. Le test volontairement modifie les paramètres sans modifier la version textuelle : ce cas doit être détecté, pas masqué par un numéro de version inchangé.

## 4. Ce qui fonctionne et corrige les réserves antérieures

### Besoin IDE distinct des options de renfort

Le contrôle positif **A10 réussit** : supprimer toutes les options de renfort ne change pas la trajectoire de besoin IDE pour la même pratique habituelle. La fonction `coverage()` calcule le besoin à partir de la demande et de la simultanéité, avant le choix des offres. Dans cette fixture, le pic reste **5 IDE**, avec **2 au-dessus du planning**. Cette indépendance précise est confirmée ; elle ne valide pas l’estimation des besoins en clinique.

### Décomposition des gains déjà disponible

L’audit des résultats régénérés donne :

| Plan sur la fixture nominale | Minutes non couvertes | Attente, patients·h | Heures de renfort |
|---|---:|---:|---:|
| Pratique habituelle | 1 040 | 21,5 | 0 |
| Coordination S01 à 10 h seule | 905 | 14,5 | 0 |
| R1 + R2 seuls | 640 | 21,5 | 10 |
| Coordination S01 à 10 h + R1 + R2 | 435 | 14,5 | 10 |
| Coordination S01 à 10 h + R2, sans R1 | 795 | 14,5 | 4 |

Ces valeurs sont bien présentes dans les branches calculées ; il n’est pas nécessaire de créer une nouvelle campagne pour obtenir cette décomposition. Elles ne sont pas des effets mesurés dans un hôpital. Le caractère conditionnel de R1 est explicite dans les résultats et dans la capture livrée.

### Informations privées

Les tests livrés T03/T04 passent, l’interface de prévision accepte un snapshot public, et le backend privé est refusé par le chemin produit testé. Aucune fuite vers une réalisation privée n’a été identifiée dans cette revue ciblée. Ce constat ne remplace pas une preuve exhaustive sur tous les futurs modules.

### Admissions et métrique de charge

La correction du travail d’admission restant dû existe réellement, et T14 passe. L’audit n’établit pas une nouvelle erreur chiffrée sur ce point. La formule reste néanmoins une convention du démonstrateur : les minutes de soins d’un patient en attente sont comptées comme non couvertes, et le travail d’admission restant est ajouté en fin d’horizon. Ne pas confondre cette convention avec une mesure validée des soins réellement non délivrés.

Le correctif souhaitable est un test de comptabilité/localisation/double comptage, pas l’imposition générale selon laquelle toute admission améliorerait tous les scores.

### Test T19

Le test T19 vérifie un changement de demande et de minutes non couvertes quand t varie. La simple assertion `len(set(totals.values())) > 1` n’établit pas le franchissement d’un seuil d’effectif. L’export garde le même pic de 5 IDE pour t=0 à 7. Cela ne prouve pas que les besoins horaires sont toujours identiques ; cela signifie que la preuve spécifique d’un seuil contrôlé reste à ajouter. Ne pas modifier la fixture uniquement pour obtenir un chiffre attendu : documenter l’oracle de calcul du seuil.

## 5. Traçabilité de la livraison et du budget

Le registre chaîné effectivement livré est intact, mais contient **32 entrées, dont 30 commandes, pour 37,016 s**. Le fichier `BUDGET_FINAL.json` annonce **43,001 s**, et le texte de livraison environ **43,6 s**. Les dernières lignes permettant de relier ces valeurs ne sont pas présentes dans le registre restauré. Son dernier enregistrement est le premier essai T30 échoué ; le reçu de restauration final est détaché et réussi.

Cela ne remet pas en cause T30 : **cet audit l’a rejoué avec succès**. En revanche, la reprise annoncée ne restitue pas à elle seule le compteur final. Le commit supplémentaire `282ee85`, décrit comme purement probatoire, n’est pas livré dans l’arbre ni dans les patches.

Autre limite : `restore.sh` vérifie le manifeste principal, mais pas `SHA256SUMS.post` avant de rejouer. **Les deux manifestes sont conformes dans l’archive fournie**, vérifiés par cet audit ; le script de restauration devrait contrôler aussi les reçus détachés et la continuité du registre final.

Enfin, le chaînage détecte la modification d’une entrée conservée, mais `read_ledger()` retourne un registre vide si le fichier manque et n’ancre pas extérieurement sa longueur finale. La promesse « impossible de remettre à zéro » est donc trop forte. Une copie complète et une empreinte finale vérifiée sont nécessaires pour détecter une perte/troncature accidentelle à la reprise.

## 6. P4 reste partiel

La page livrée respecte visuellement la priorité automatique et place le scénario manuel en complément. Elle utilise les styles du cockpit mais reste sous `web/decision`, hors écran React. Les 66 tests Vitest annoncés du cockpit n’ont pas été exécutés dans cette livraison et ne l’ont pas été dans cet audit.

Les tests navigateur n’ont pas pu être revalidés dans l’environnement d’audit, en raison du blocage administratif de la navigation locale ; ne pas enregistrer cet obstacle comme un échec fonctionnel du produit, ni déclarer ces 19 contrôles indépendamment réussis.

L’intégration frontend vient après les corrections de contraintes. Elle ne doit ni déclencher une réécriture du moteur ni ouvrir P5/P6. Une installation réseau éventuelle exige toujours son autorisation distincte.

## 7. Ordre de reprise recommandé

1. Reproduire A01–A09 et garder les journaux ; confirmer A10 et les 44 + 86 tests préexistants.
2. Corriger F01/F02/F03/F05 : préconditions des verrous, engagements cumulés, atomicité des réservations, précision des horaires.
3. Corriger F04/F06/F07/F08 : clés idempotentes liées au contenu, inconnues explicites et identités de résultats.
4. Compléter les tests de seuil IDE et de comptabilité des admissions, sans modifier l’objectif pour rendre les seuls exemples favorables.
5. Relivrer les preuves finales et le registre complet ; vérifier le compteur à la restauration et les deux manifestes.
6. Intégrer au cockpit React et relancer ses tests lorsque l’installation réseau aura été explicitement autorisée ; vérifier Python 3.11.9.
7. Réexaminer la clôture technique. Maintenir `PROTOTYPE_UNVALIDATED` et `G2=NO-GO`, même si tous ces contrôles passent.

**Le paquet de correction joint est un support à transmettre à l’agent de développement. Il ne vaut pas nouvelle autorisation de dépense, de push, de campagne ou d’entraînement.**

## 8. Reproduire l’audit

Depuis l’arbre source restauré de l’archive originale, avec ses dépendances déjà présentes :

```bash
export PYTHONPATH=src:.
python -m pytest -q /chemin/vers/HospitalOS_Audit_DS_20261114/tests/test_independent_acceptance.py
python /chemin/vers/HospitalOS_Audit_DS_20261114/tests/reproduce_findings.py
```

Les tests indépendants doivent échouer sur les défauts décrits avant correction. Un code de sortie pytest égal à 1 est donc attendu sur la livraison initiale. Après correctif, conserver les mêmes invariants ; adapter uniquement les points d’intégration documentés si les contrats changent, sans supprimer la couverture des contre-exemples.

Le script de contre-exemples ne constitue pas un lanceur de production ; il opère uniquement sur la fixture synthétique nominale. Il n’entraîne aucun modèle.

### Coût de vérification effectivement enregistré

21.102 s de temps mural pour les commandes bornées de tests/rejeux, au plus 6.516 s par commande. En réservant prudemment les 43,6 s annoncées avant cet audit, le total comptable reste à 64.702 s sur 600 s. Cette durée ne comprend pas la lecture statique ni la rédaction ; elle n’est pas une estimation de durée de développement. Aucun processus applicatif de test n’a été laissé actif.
