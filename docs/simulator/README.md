# Simulateur hospitalier — référence v0.3 et intégration

Date : 25 octobre 2026. **Statut : spécification et première boucle dynamique
réunies ; implémentation complète et qualification v0.3 à établir.**

## Branche commune

`codex/integrated-demo` réunit les sources suivantes en conservant leur historique :

| Élément | Révision source | Chemin dans la branche commune |
| --- | --- | --- |
| Backend hybride, PR #22 | `8dea341536e2c0d9a1f1e0864f5df824946942da` | `src/hospitalos/hybrid`, `services/api/hybrid_app.py` |
| Cockpit | `a5e737eec2cfdf0f52a68f41b523f928181c03e6` | `web` |
| Boucle dynamique, PR #24 | `33c764b02561df9ba1a0aaeaf710c926f88b954a` | `src/hospitalos/simulator`, `services/api/simulator_app.py` |
| Spécification, PR #23 | `844008eaf4d7ad8332840c2f24200009b7a8e64c` | `docs/simulator/spec-v0.3.md` |

Depuis la racine : **`python3 demo.py`** (Python 3.11+, Node.js 22+ avec npm).
Le [guide de lancement](dynamic-demo.md) décrit la préparation automatique, les
ports, l'arrêt et les limites de la démo. Cette intégration ne clôture aucun
jalon M1–M4 et n'attribue aucune qualification au simulateur complet.

## Spécification et cartographie initiale

La [spécification consolidée v0.3](spec-v0.3.md) fixe le périmètre du nouveau banc
mono-unité « libérer puis attribuer », ses interfaces, ses règles métier et son
protocole scientifique. Elle comprend les jalons M1–M4 et les vingt cas T01–T20.
Le fichier Markdown reprend intégralement le texte source des livrables Word/PDF
du 25 octobre. Les liens d'entrée du dépôt conduisent à cette version diffable.

La cartographie documentaire initiale ci-dessous repose sur l'inventaire des fichiers aux
révisions ci-dessous. Ce n'est pas un audit complet du code ni une réexécution
des campagnes historiques. Aucun des vingt tests n'est déclaré réussi par
simple correspondance avec un fichier existant.

## Références et portée

| Référence | État observé | Rôle |
| --- | --- | --- |
| [main, bfa1fa7](https://github.com/HospitalOsLaunch/carepredict-mvp/tree/bfa1fa7e0a8bbdd8817157a162d65f507568a251) | Révision de départ de cette intégration | Socle synthétique, contrats opérationnels et résultats historiques |
| [PR #22](https://github.com/HospitalOsLaunch/carepredict-mvp/pull/22), [8dea341](https://github.com/HospitalOsLaunch/carepredict-mvp/tree/8dea341536e2c0d9a1f1e0864f5df824946942da) | Ouverte, en brouillon lors de la lecture | Prototype hybride candidat à réutilisation ; absent de main à cette révision |
| [Spécification v0.3](spec-v0.3.md) | Contrat pour implémentation | Exigences du nouveau banc et critères de qualification |

La v0.3 remplace les deux spécifications préparatoires de cette conversation
pour ce banc. Elle ne réécrit pas les résultats figés, les contrats Nantes,
OPERATIONAL_V2, HYBRID_MVP_2 ni les expériences antérieures. Une migration de
contrat nécessite sa propre modification versionnée et ses régressions.

Les numéros appartiennent à des séries différentes :

- **0.3 documentaire** : révision de la présente spécification ;
- **0.1–0.4 moteur dans la spécification** : jalons cibles M1–M4 ;
- **v0.4.1 historique** : moteur importé sous
  [synthetic/v041](../../src/hospitalos/synthetic/v041), déjà utilisé par les lots ;
- **générateur v0.2 mentionné dans la spécification** : composant à identifier
  par chemin, révision et empreinte lors de l'audit. Son équivalence avec le
  générateur du dépôt n'est pas établie.

Aucune comparaison de ces numéros ne prouve qu'un jalon est déjà livré.

## Raccordement à l'existant

Les éléments « candidats » ci-dessous doivent être vérifiés sur la révision
effectivement réutilisée. Les liens de la PR #22 sont figés sur son commit pour
ne pas présenter des fichiers non fusionnés comme disponibles dans main.

| Domaine v0.3 | Point d'appui documenté | Écart ou vérification à conduire |
| --- | --- | --- |
| Scénarios et provenance | [Socle synthétique](../synthetic/README.md), [registre de cohortes](../synthetic/lot03.md), [mécanismes réservés](../synthetic/lot07.md) | Auditer distributions, dépendances, calendrier, accès cachés et séparation des jeux ; ne réutiliser que profils/primitives, sans injecter une seconde trajectoire physique |
| État à D et corrections | [Observations telles que connues](../synthetic/lot02.md), [mouvements patient](../synthetic/lot10.md) ; [journal hybride, PR #22](https://github.com/HospitalOsLaunch/carepredict-mvp/blob/8dea341536e2c0d9a1f1e0864f5df824946942da/src/hospitalos/hybrid/journal.py) | Spécifier la correspondance avec les quatre horloges ; ne pas déduire t_true d'une date administrative ; conserver les observations historiques après correction |
| Lits, réservations et parcours | [MVP hybride, PR #22](https://github.com/HospitalOsLaunch/carepredict-mvp/blob/8dea341536e2c0d9a1f1e0864f5df824946942da/docs/operational/hybrid-mvp.md), [parcours](https://github.com/HospitalOsLaunch/carepredict-mvp/blob/8dea341536e2c0d9a1f1e0864f5df824946942da/docs/operational/release-allocate.md) | Quatre dimensions du lit, réservation puis installation, révocation clinique exogène, décès, urgences et cycle complet de séjour ; ne pas confondre projection d'un plan et moteur de vérité |
| Ressources humaines | [Changements d'effectifs](../synthetic/lot08.md) et capacité agrégée du prototype hybride | Minutes par rôle, présence, délégation, coût des tâches et déficit conservé ; éviter le double comptage avec la charge de fond |
| Canaux SI | [Qualification de source, PR #22](https://github.com/HospitalOsLaunch/carepredict-mvp/blob/8dea341536e2c0d9a1f1e0864f5df824946942da/docs/operational/source-qualification.md) | L'adaptateur JSON documenté n'est pas le faux SI PAM/FHIR/écrans requis ; construire les projections, perturbations, profils et essais I1 |
| Recommandations et exécution | [Boucle observée](../synthetic/lot06.md), [unité vivante, PR #22](https://github.com/HospitalOsLaunch/carepredict-mvp/blob/8dea341536e2c0d9a1f1e0864f5df824946942da/docs/operational/live-unit-pilot.md) | Représenter destinataires, présentation, lecture, refus, report, coût, exécution et échec ; une commande sandbox ne prouve pas une action hospitalière |
| Aléas et notateur | [Innovations, PR #22](https://github.com/HospitalOsLaunch/carepredict-mvp/blob/8dea341536e2c0d9a1f1e0864f5df824946942da/src/hospitalos/hybrid/innovations.py), [notateur](https://github.com/HospitalOsLaunch/carepredict-mvp/blob/8dea341536e2c0d9a1f1e0864f5df824946942da/src/hospitalos/hybrid/scoring.py) | Vérifier indexation par occurrence, invariance des primitives et reconstruction indépendante de W ; inclure attentes non terminées, stocks et sorties alternatives |
| Aval | [Lot 16 : SMR fini](../operational/lot16.md) | Conserver cette variante historique distincte ; la v0.3 mono-unité retient initialement un délai externe à compter de la demande complète |
| Apprentissage | [Contrat commun et premier modèle](../operational/lot15.md), [préparation apprise, PR #22](https://github.com/HospitalOsLaunch/carepredict-mvp/blob/8dea341536e2c0d9a1f1e0864f5df824946942da/docs/operational/learned-preparation.md) | Définir des données v0.3 séparées, des cibles déclarées autorisées et U1 ; les anciens apprentissages ne valent pas qualification de ce nouveau corpus |

## Décisions de raccordement

1. **Un seul moteur de vérité pour un scénario.** Les générateurs historiques
   fournissent des primitives après audit. Le moteur du planificateur peut
   projeter des scénarios pour décider, mais ne commande pas la vérité par une
   trajectoire pré-calculée. SimPy reste le choix par défaut de la spécification ;
   une réutilisation du moteur existant exige une analyse d'équivalence ou une
   décision d'architecture documentée.
2. **Une frontière explicite d'observation.** La politique métier et HospitalOS
   reçoivent uniquement leurs observations autorisées. Les contrats agrégés
   existants ne permettent pas de reconstruire des identités ou compatibilités
   individuelles absentes. Les données nécessaires doivent venir du bon canal.
3. **Des variantes séparées pour l'aval.** Le délai exogène de la v0.3 ne
   désactive pas la ressource SMR finie du lot 16. Chaque expérience déclare son
   mécanisme ; ni résultats ni paramètres ne sont transférés implicitement.
4. **Des interfaces définies avant leur raccordement.** M2 produit les
   dictionnaires PAM, profils FHIR et contrat OpenAPI de la façade HTTP, avec
   versions et règles temporelles. Une extension des contrats existants
   conserve leur compatibilité ou documente explicitement la migration.
5. **Des corpus et preuves séparés.** Les exports, manifestes et qualifications
   v0.3 ont leur identité. Aucun fichier d'évidence figé ni ensemble de test
   historique n'est réécrit pour faire correspondre un ancien résultat à la
   nouvelle spécification.

Le [plan gériatrie–aval historique](../synthetic/realism_plan.md) conserve sa
traçabilité et son ambition multi-unités. La v0.3 définit une tranche mono-unité
plus étroite ; la réutilisation de ses acquis ne vaut pas fusion des périmètres.

## Séquence d'implémentation

Les critères complets figurent aux chapitres 10, 14 et 15 de la spécification.
Les points d'entrée ci-dessous servent à préparer les prochains lots. La commande
livrée plus haut lance uniquement la boucle bornée décrite dans son guide.

| Lot | Travail concret | Preuve attendue avant clôture |
| --- | --- | --- |
| Préparation M1 | Identifier le générateur ; auditer les candidats réutilisés ; définir les schémas et correspondances d'horloge ; choisir l'emplacement du moteur de vérité | Cartographie code/exigences à révision figée, registre des hypothèses et décisions de migration |
| M1 — moteur métier | Implémenter état, tâches, ressources, politique métier, réservations/installations, événements, initialisation, CRN et notateur | C1, micro-scénarios et mutations de journal ; au moins 1 000 jours cumulés, dix graines et plusieurs régimes, conformément au chapitre 14 |
| M2 — faux SI | Construire PAM/FHIR/écrans, corrections, livraison, reprise et séparation des accès | C1 conservé, I1 et tests de fuite ; fiche de portée avant attribution de SIM_GO_INTEGRATION |
| M3 — recommandations | Relier les actions, leurs préconditions, l'adhésion et leurs coûts ; comparer A0/A1 et références | Contrôles du chapitre 11, intégrale d'attente, stocks, coûts, dégradations et causes tracées |
| M4 — calage et recherche | Intégrer les primitives auditées, figer sources/splits et réserver une variante structurelle ; préparer U1 | Conditions de SIM_GO_PRETRAIN_RESEARCH puis résultats U1 ; C2–C5 uniquement lorsque les données nécessaires existent |

L'audit du composant réutilisé précède sa première utilisation, même si
l'intégration complète du générateur est planifiée à M4.

## Suivi initial des vingt cas de référence

**Statut initial de toutes les lignes : à implémenter ou à rapprocher d'une preuve
exécutable, puis à exécuter.** Les tests historiques cités dans les documents
liés ne sont pas automatiquement équivalents. Chaque résultat devra enregistrer
la révision, le scénario, la commande, le résultat et le chemin de preuve.

| Cas | Jalon de première couverture | Objet |
| --- | --- | --- |
| T01, T02, T03 | M1 | Concurrence, consommation et expiration des réservations |
| T04 | M1 puis M2 | Vérification physique d'un lit déclaré prêt à tort |
| T05, T06, T07 | M1 | Révocation de sortie, décès, fermeture d'un lit occupé |
| T08, T09 | M1 puis M3 | Déduplication du nettoyage et non-préemption |
| T10 | M2 puis M3 | Idempotence des messages et recommandations |
| T11 | M2 | Correction PAM Z99 sans réécriture de l'observation à D |
| T12, T13 | M3 | Neutralité sans coût et refus avec coût de lecture |
| T14 | M1 puis M3 | Même primitive d'aval, départ du délai lié à la demande |
| T15 | M1 | W = 4 heures-patients, y compris attente inachevée |
| T16, T17 | M1 | Déficit soignant et sortie des urgences sans hospitalisation |
| T18 | M1 puis M2/M4 | Absence d'information privilégiée dans toutes les surfaces autorisées |
| T19 | M2 | Réconciliation après panne, désordre, annulation et correction |
| T20 | M1 puis M3 | Primitives communes et conséquences endogènes traçables |

Les statuts de qualification restent **non attribués** pour le nouveau banc :
SIM_GO_INTEGRATION, SIM_GO_PRETRAIN_RESEARCH et SIM_QUALIFIED_FOR_SCOPE exigent
chacun les preuves et limites prévues au chapitre 10. Aucun résultat positif
d'une politique, bénéfice terrain ou nouveau franchissement de porte de
validation n'est revendiqué par cette livraison documentaire.
