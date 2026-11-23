# HospitalOS — Ré-audit indépendant de la v5

14 novembre 2026. Audit technique borné sur données synthétiques. Aucun entraînement, aucune
inférence AJ-H, aucune installation réseau, aucune écriture distante, aucune modification du code
produit. Le plan automatique reste central ; le mode manuel emploie le même moteur.

## Verdict

**Les quatre constats du ré-audit v4 sont corrigés sur les contre-exemples d’origine.** La suite
complète passe indépendamment : **174 réussites, 0 échec, 0 ignoré**. La restauration installe
le registre final authentifié, puis y comptabilise réellement ses tests et son export.

**Statut maintenu : PARTIAL_WITH_CHECKPOINT.** Un nouveau contre-exemple ciblé révèle une
incohérence de capacité entre deux offres du même prêteur, dans le même instantané et sur les
mêmes créneaux. Deux prêts refusés ensemble peuvent être approuvés séparément dans un ordre,
mais pas dans l’autre. Ce défaut ne remet pas en cause les corrections et les cas déjà couverts.

Statut scientifique inchangé : `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`.
Ce rapport ne prétend ni à l’absence générale de bugs ni à une efficacité sur le réel.

## 1. Entrée, intégrité, provenance

Archive : `HospitalOS_DS_P0-P4_20261114_v5.zip`, 24,248,351 octets.
SHA-256 **calculé ici**, pas comparé à une empreinte externe fournie :

```text
37cc8cde64ccc8afcd9b16ad4e9b4001f1f28680bd83b88bb0f17feed84a349d
```

Arbre déclaré et livré : `56ad3cfeda775a20396cb80dfa4554f6a8899321`.
Contrôles : CRC ZIP valide ; aucun membre ZIP/TAR hors du répertoire d’extraction et aucun lien
symbolique ; manifestes principaux **218/218**, post-scellement **6/6**, finaux **6/6**, références
**8/8** conformes. Les ensembles de manifestes se recouvrent : ne pas additionner ces nombres
comme un nombre de fichiers uniques.

Le fichier joint `CORRECTIONS_REPORT (1).md` est **identique octet pour octet** au rapport
`docs/CORRECTIONS_REPORT.md` du ZIP. Le décalage documentaire de v4 est donc levé.
Ces contrôles établissent la cohérence du paquet reçu, pas une signature cryptographique de son auteur.

## 2. Exécutions indépendantes

| Contrôle | Résultat |
|---|---|
| Original A01–A10 | Copie exacte vérifiée ; tous passent dans la suite complète |
| Original B01–B04 | Copie exacte vérifiée ; tous passent dans la suite complète |
| Test original du compteur restauré | Copie exacte ; exécuté contre une vraie restauration, passe |
| Suite DS + trois fichiers hybrides autorisés | 174/174, 0 échec, 0 ignoré |
| Restauration neuve via `restore.sh` non modifié | 88/88 tests DS ; 11 résultats identiques octet par octet |
| Registre utilisé par le runner restauré | Registre final 137 lignes / 315,676 s conservé comme préfixe exact |
| Copie altérée/incomplète, restaurateur réel | Sortie 2 au contrôle du manifeste ; cible non créée |
| TypeScript autonome | `tsc -p web/decision/tsconfig.json --noEmit` réussi |
| Nouvelle régression ciblée C01–C04 | 5 cas : 1 échec, 4 réussites |

Les 88 tests de restauration sont inclus dans les 174, pas un périmètre distinct à additionner.
Le test de compteur n’est pas ignoré ici : `AUDIT_PACKAGE` et `AUDIT_RESTORED` pointent sur le
paquet réel et le dossier effectivement restauré. Les JUnit d’auteur contiennent 174 cas dont
1 ignoré (173 réussis) ; le contrôle post-restauration de l’auteur figure aussi séparément.

Environnement ici : Python 3.13.5, pydantic 2.13.5, numpy 2.3.5,
pytest 9.0.2, jsonschema 4.26.0. Les dépendances sont celles
déjà disponibles ; aucune installation ni ajustement des versions. pytest 9.0.2
est au-delà de la borne `<9` des dépendances de développement : ces succès ne remplacent donc
pas un contrôle dans l’environnement cible déclaré. Les plugins pytest automatiques sont désactivés.

Les trois fichiers hybrides sont `test_mvp.py`, `test_pathway.py`, `test_future.py` (86 tests).
`test_decision_guard.py` et son `fit_benchmark()` sont exclus : aucun apprentissage autorisé ici.

## 3. Fermeture des constats v4 sur leur périmètre

**V4-R01 — Fenêtres décalées.** Une offre hors grille horaire est refusée explicitement ; le
cumul et la réservation utilisent des créneaux communs. Les prêts entiers non chevauchants
restent possibles. Les tests originaux et ceux ajoutés par l’auteur passent.

**V4-R02 — Prêteur inconnu.** Le prêt `shared_unit` sans identité du prêteur n’est plus
approuvable. Les autres catégories de ressources ne sont pas bloquées à tort.

**V4-R03 — Baisse réelle de capacité.** La réservation utilise la capacité du nouvel instantané
au lieu de conserver la capacité historique supérieure ; le cas d’origine refuse le deuxième
prêt et préserve le premier. Le registre trace aussi les conflits couverts par ses tests.

**V4-D01 — Compteur restauré.** La vraie restauration a choisi `BUDGET_LEDGER.final.jsonl`
(137 lignes / 315,676 s), et non le terminal scellé intermédiaire (133 / 310,808) ni l’arbre
source (130 lignes). Les 137 lignes sont un préfixe exact du registre de la cible. Le reçu de
restauration annonce 324,813 s après ses deux commandes de rejeu ; le contrôle était bien
exécuté dans cette cible. Les exécutions de cet audit poursuivent la même lignée.

## 4. Nouveau constat V5-R01 — Une capacité dépend de l’offre approuvée en dernier

### Entrée et reproduction

Même unité prêteuse `U-LOAN`, compétence `IDE`, même instantané public, renforts confirmés et
créneau **14 h–20 h heure de Paris, le 17 novembre 2026** (13 h–19 h UTC).

| Offre | Effectif déclaré du prêteur | Minimum conservé | Marge déclarée |
|---|---:|---:|---:|
| R1 | 4 | 3 | 1 |
| R2 | 5 | 3 | 2 |

Il s’agit de **déclarations contradictoires simultanées**, et non d’une hausse connue entre
deux instantanés. On ne peut pas en déduire l’effectif réel. La politique explicite du code
`lending_violations` résout déjà la comparaison conjointe de façon prudente (effectif minimal,
minimum à conserver maximal).

| Chemin testé | Résultat |
|---|---|
| Énumération conjointe R1+R2 | Refus `lending_unit_minimum_cumulative:...:4-2<3` |
| Approuver R1, puis R2, avec le même instantané et le même registre | **Deux `APPROVED_IN_DEMO`**, 2 engagements par heure |
| Approuver R2, puis R1, mêmes données | Premier approuvé, second refusé |

**La décision dépend de l’ordre de validation, sans nouvelle information sur la capacité.**
Le fait que le comparateur conjoint refuse les deux mais que le circuit séquentiel les accepte
est un défaut démontré de cohérence des contraintes, indépendamment de l’effectif réel inconnu.

Reproduction : `tests/probe_v5_capacity_consistency.py`, résultat complet
`evidence/capacity_consistency_probes.json`. Le test C01 dans
`tests/test_v5_capacity_consistency.py` est paramétré dans les deux ordres : l’ordre R1→R2
échoue, l’ordre inverse passe. Les décisions sont des validations de démonstration seulement.

### Cause identifiée dans les sources

- `resources.py:29–61` agrège prudemment les capacités des **offres sélectionnées ensemble**.
- `planner.py:787–815`, `_reservation_requests`, calcule chaque capacité à partir de la seule
  offre en cours : `scheduled - minimum`.
- `resources.py:218–239`, `reserve_all`, remplace la capacité par celle de chaque demande.

L’ajustement v5 pour ne plus conserver une capacité obsolète est utile. Mais, faute d’une
capacité cohérente au niveau de l’instantané, l’offre R2 réaugmente la marge de 1 à 2 alors
qu’aucune nouvelle information n’a été reçue. Extraits avec numéros de lignes dans
`reference_extracts/SOURCE_EXCERPTS.md`.

### Correctif attendu, sans réécriture

Définir une capacité unique par **unité prêteuse × compétence × créneau × version de l’état**,
avec provenance, et la partager entre génération de candidats, revalidation et réservation.
Lorsque les déclarations simultanées se contredisent, appliquer une politique explicite :
refus diagnostiqué ou résolution prudente déclarée. Ne pas utiliser la dernière offre validée
comme source d’autorité. Une hausse réellement établie dans un nouvel instantané doit pouvoir
être prise en compte ; ne pas imposer le minimum historique pour toujours.

### Témoins qui doivent rester verts

C02 : deux offres concordantes, 5 IDE/minimum 3 → deux prêts permis.
C03 : premier état concordant à 4 puis nouvel état concordant à 5 → second prêt permis.
C04 : fenêtres disjointes, capacités différentes → pas de conflit artificiel entre horaires.
La grille de l’instantané refuse aussi correctement un `as_of` à la demi-heure (contrôle positif).

## 5. Résultats nominaux et périmètre produit

Les 11 résultats reconstruits sont identiques à ceux du paquet. La fixture nominale conserve
1040 minutes non couvertes en référence ; 905 coordination seule ; 640 renforts seuls ;
435 combinaison ; 795 combinaison sans R1 non confirmé. Ce ne sont ni des objectifs codés
en dur, ni des effets cliniques réels, ni une validation du score de pression.

La v5 améliore les garde-fous et la reprise ; elle ne fournit pas de nouvel apprentissage du
world model. Ne pas confondre réussite fonctionnelle du moteur, performance prédictive sur
d’autres cas, ni efficacité de recommandations en situation réelle.

## 6. Réserves qui demeurent

L’intégration React est dans les sources ; les tests Vitest/React/navigateur de cette version
sont des preuves d’auteur, non rejouées ici. `web/node_modules` n’est pas présent dans la
restauration ; aucune nouvelle installation réseau n’a été entreprise. Le typecheck autonome
n’est pas le typecheck React.

Python 3.11.18 dispose de journaux d’auteur dans le paquet. Pas d’exécution indépendante sous
3.11 dans cet audit, ni de contrôle de la version exacte 3.11.9. `mypy --strict` non exécuté.
Les vérifications sont synthétiques et bornées, sans conclusion sur la généralisation ou le réel.

## 7. Budget et livraison de l’audit

Départ : **137 enregistrements / 315.676 s** (registre final v5 authentifié).
Fin : **146 enregistrements / 343.115 s**. Ajout de cet audit : **27.439 s**.
Reliquat documenté : **256.885 s sur 600**, plafond de 30 s par commande respecté.
Le coût de l’enveloppe de restauration est ajouté comme note (4,618 s), sans recompter les
9,137 s des tests/export déjà enregistrés par la cible. Les temps de lecture, rédaction et
comparaison statique ne sont pas une estimation de durée des commandes de test.

Le répertoire `ledger/` contient la lignée complète et son ancre. Conserver tout historique
postérieur éventuel et réconcilier avant reprise ; ne pas remplacer une lignée plus récente.
Aucune exécution supplémentaire n’est promise après cette réponse.

## 8. Décision proposée

Conserver les acquis P0–P4 et fermer les quatre constats v4 sur les cas vérifiés. Corriger
**V5-R01** sans élargir le catalogue d’actions ni changer de modèle. Rejouer les originaux,
C01–C04, puis la restauration et les 11 résultats. Conserver `PARTIAL_WITH_CHECKPOINT` tant
que cette incohérence et les portes déclarées restent ouvertes. P5/P6, entraînement, dépenses
et push restent hors périmètre sans ordre explicite distinct.
