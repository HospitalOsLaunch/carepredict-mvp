# HospitalOS : corpus synthétique v0.4.1 — correctif de fusion

**Statut : synthétique, non calibré sur un établissement. Ce n'est ni une reproduction d'hôpital ni une preuve d'efficacité.**

Ce corpus contient une année simulée (2025, pas horaire) d'un pôle de médecine en aval des urgences : 102 lits répartis en 4 unités (médecine polyvalente 28, court séjour gériatrique 24, pneumologie 26, cardiologie 24). L'unité focale, la gériatrie, est une **projection du même monde** : elle partage ses patients hébergés, ses services et ses rapatriements avec les trois autres unités.

## Correctif de fusion de la v0.4.1

La fusion traite désormais chaque mention à sa première disponibilité. Lorsqu'une version ajoute un complément, seul le texte ajouté peut actualiser une variable. Les faits recopiés conservent leur source et leur ancienneté ; « RAS » ne les réaffirme pas. Une répétition explicite ou une rectification dans le complément constitue bien une nouvelle mention.

Chaque valeur porte l'identifiant et la version de sa note source, la date de rédaction de la mention et l'extrait qui la justifie. Par exemple, pour `S001546`, le complément de l'observation médicale du 11 février ne remplace plus « vit seule », documenté dans le recueil IDE plus récent que l'observation médicale initiale.

Les états documentaires du pôle et de la gériatrie ont été recalculés depuis les notes observées, sans consulter la vérité annotée. Les notes, les extractions par version, la couche séjour, les trajectoires physiques et les contrefactuels restent identiques à ceux de la v0.4.1 initiale. Le bilan mesuré figure dans `data/rapport_fusion.json`.

Deux contrôles et sept tests supplémentaires couvrent la conservation des mentions recopiées, leur provenance, les corrections explicites, l'absence d'effet des versions futures et le rejet des historiques incomplets ou réécrits.

## Ce qui change en v0.4.1 : fiabilisation des notes et de l'estimand de renfort

Une revue externe de la v0.4 a relevé cinq défauts qui échappaient aux contrôles. Tous ont été vérifiés, puis corrigés, et chacun est maintenant couvert par un contrôle ou un test qui l'aurait détecté. Rejoués sur la v0.4, les nouveaux contrôles échouent.

| Défaut en v0.4 | Ampleur | Correction en v0.4.1 | Ce qui le détecte désormais |
|---|---|---|---|
| « Pas d'oxygénothérapie » lu comme `oxygene=True` | 2 644 versions, 2 046 notes | La négation n'était pas reconnue après une apostrophe (« pas d' »). Apostrophes typographiques normalisées. Une formulation négative niée (« personne ne vit avec lui ») est lue comme une affirmation. | 21 cas unitaires écrits à la main (négations, apostrophes, abréviations) |
| Vérité incomplète, et évaluation par simple détection | 1 460 versions avec une mention d'oxygène non annotée | Les examens ne parlent plus de SpO2 hors annotation. Les récits ne contiennent plus d'information sociale implicite (« découverte par l'IDE à domicile »). L'évaluation porte sur le triplet variable-valeur-statut. | Contrôle de complétude : toute phrase qui contient un marqueur explicite d'une variable doit être annotée ; contrôle de conformité : un fait « vrai » égale la situation vraie, un fait « faux » ou « périmé » en diffère |
| Contradictions d'assemblage | Dans une même note : 74 cas « veuf, vit seul » avec un conjoint aidant (78 à mon décompte). Sur toutes les notes d'un séjour : 562 séjours, plus 233 « alité » avec une marche, et 90 « marche sans aide » avec une aide technique | Une situation patient unique (statut marital, cohabitant, aidant, aides, logement, aide technique), dont toutes les notes du séjour sont rédigées. Formulations d'autonomie compatibles avec l'aide technique. | Contrôle de cohérence entre les faits « vrais » d'un séjour, toutes notes confondues ; les erreurs volontaires (« faux », « périmé ») restent étiquetées à part |
| Estimand « exécution » mal nommé | 193 scénarios « renfort imposé » sur 1 460 sans aucun renfort | Familles A et B renommées : elles mesurent l'effet d'engager le levier, échec compris. Nouveau scénario `renfort_soignant_pourvu`, où le renfort est réellement présent. | Contrôle : un renfort pourvu est toujours présent |
| La jointure proposée effaçait des faits connus | 2 370 versions où une autonomie connue devenait vide | État documentaire par variable (`etat_notes_asof.csv.gz`) : une absence de mention n'efface rien. Chaque variable porte sa source, sa date, le nombre de notes qui la mentionnent et un drapeau de conflit. | Contrôle : aucune variable connue ne redevient vide, aucune source postérieure à l'instant |

Le monde simulé est inchangé. Les fichiers des états, des séjours, des livraisons, des variables, de la couche séjour et des décisions sont identiques à l'octet à ceux de la v0.4. Changent les notes, leur vérité, l'extraction et les contrefactuels, qui gagnent un scénario.

## Ce qui avait changé en v0.4 : les notes cliniques

La v0.4 ajoute au monde v0.3, **inchangé à l'octet**, des notes cliniques en texte libre :
- observation des urgences ;
- observation d'entrée dans le service ;
- recueil infirmier d'accueil.

Il y a 14 058 notes et 18 257 versions. Chaque note est versionnée, horodatée et accompagnée de sa vérité annotée. Un extracteur de référence les lit (section 4).

Les formulations ont été rédigées à la main dans une banque, en trois voix (interne des urgences, senior de service, IDE d'accueil). Un assembleur reproductible les combine. **Leur réalisme n'est pas validé** : un médecin du CHU doit relire un échantillon.

## Ce qui avait changé en v0.3 par rapport à la v0.2

| Correction | Ce qui était faux en v0.2 | v0.3 |
|---|---|---|
| 1. Deux estimands d'exécution déclarés | Un seul scénario : « levier seul, puis rien » | Famille A « levier seul, puis rien » et famille B « action imposée, puis politique en vigueur », avec un scénario `factuel` qui reproduit exactement la trajectoire observée, combinaisons de leviers comprises |
| 2. Découpage des contrefactuels | Aucune colonne de découpage ; 60 fenêtres franchissaient chaque frontière | Colonne `split` dans `decisions` et `contrefactuels`, même règle et même embargo que les vues d'apprentissage ; aucune fenêtre ne franchit une frontière |
| 3. Séjours figés au 31/12 | Des séjours censurés portaient une admission ou une sortie médicale de 2026 | Les séjours censurés sont reconstruits depuis l'état exact du 31/12 à 24 h ; aucune date postérieure (contrôlé) |
| 4. Recommander n'est pas exécuter | Un levier décidé était toujours exécuté | Chaîne recommandation HospitalOS → exposition → validation ou initiative du cadre → exécution ou échec, et famille C « recommandation imposée » : effet en intention de traiter |
| 5. Contrôles | 30 contrôles, 6 tests de mutation | 44 contrôles, 31 tests dont 13 de mutation, au moins un par correction (v0.4.1 initiale : 55 contrôles, 47 tests dont 22 de mutation) |
| 6. Couche séjour | Agrégats d'unité seulement | Trajectoire opérationnelle de chaque séjour, telle que connue à chaque heure : 789 693 lignes, avec cibles par séjour |

Le moteur gagne trois mécanismes, pour que les nouveaux champs agissent sur la dynamique au lieu d'être décoratifs :
- **avis spécialisés**, une file partagée qui bloque la sortie médicale comme l'imagerie ;
- **aide à domicile**, à organiser pour une partie des retours à domicile et qui retarde la sortie ;
- **mobilité**, qui impose un transport, même vers le domicile, aux patients brancardés.

Le dictionnaire des champs est dans [SCHEMA.md](SCHEMA.md).

---

## 1. Contenu

| Dossier | Volume |
|---|---|
| `verite/` : séjours, états horaires (unités + pôle), effectifs, tâches, événements, politique du cadre | 5 322 séjours, 43 800 états horaires, 11 332 tâches, 166 915 événements |
| `observe/livraisons.jsonl.gz` | 160 065 livraisons, dont 823 corrections et 1 263 doublons |
| `apprentissage/` : variables d'unité, cibles d'unité | 43 800 lignes de variables, 217 380 cibles (5 horizons × 9 grandeurs) |
| `apprentissage/` : couche séjour | 789 693 lignes séjour-heure (environ 90 séjours présents par heure), autant de lignes de cibles |
| `unite_CSG/` | Projection exacte de la gériatrie, dont 190 401 lignes séjour-heure |
| `causal/` : décisions, contrefactuels, estimands | 1 460 décisions, 26 280 rejeux de 72 h en trois familles |
| `observe/notes.jsonl.gz` | 14 058 notes, 18 257 versions, avec horloges de création, de modification et de disponibilité |
| `verite/notes_annotations.jsonl.gz`, `verite/sejours_cliniques.csv.gz` | Faits affirmés par chaque version (statut, exactitude, position) ; situation clinique et sociale vraie de chaque séjour |
| `apprentissage/extraction_notes.csv.gz` | Une ligne par version de note : variables extraites par l'extracteur de référence, heure à partir de laquelle elles sont utilisables |
| `apprentissage/etat_notes_asof.csv.gz` | État documentaire par séjour et par variable après chaque version : valeur, statut, source, date de la source, nombre de notes, conflit |
| `rapport_extraction.json` | Rappel, précision, exactitude de la valeur et du statut, par variable et par période |
| `config/`, `structure.json`, rapports, `manifest.json` | Paramètres, lits, contrôles, empreintes SHA-256 |

Découpage commun à toutes les vues : entraînement de janvier à août, validation en septembre-octobre, test en novembre-décembre, et embargo de 168 h avant chaque frontière.

## 2. Démarrage

```python
import pandas as pd
x = pd.read_csv("data/apprentissage/variables_asof.csv.gz")
y = pd.read_csv("data/apprentissage/cibles.csv.gz")
train_24h = x[x.split == "train"].merge(y[(y.split == "train") & (y.horizon_h == 24)], on=["sample_id", "split"])

# couche séjour : une ligne par séjour présent et par heure, telle que connue
s = pd.read_csv("data/apprentissage/sejours_asof.csv.gz", low_memory=False)
c = pd.read_csv("data/apprentissage/cibles_sejours.csv.gz", low_memory=False)
midi = s[(s.h % 24 == 12) & (s.split == "train")].merge(c, on=["sample_id", "split"])
# relier un séjour à son unité : unite_actuelle + h  <->  entite + h dans variables_asof
```

Les colonnes booléennes de la couche séjour peuvent être vides (information pas encore connue) : lire avec `low_memory=False`.

## 3. La couche séjour

Chaque ligne décrit un séjour **tel que l'hôpital le connaît à l'heure h**. Toutes les valeurs proviennent de livraisons déjà disponibles, dédupliquées, et retenues à la version la plus récente au sens de l'horloge du fait.

| Bloc | Champs |
|---|---|
| Parcours | unité actuelle et d'appartenance, hébergé, mode d'entrée, durée écoulée, mouvements internes |
| Besoins qui contraignent le lit | isolement, oxygène |
| Charge en soins | dépendance, mobilité et minutes de soins de la dernière évaluation (bruitées, parfois erronées), âge de l'évaluation |
| Préparation de la sortie | date de sortie prévisionnelle (en jours restants), nombre de révisions, statut sortant saisi, destination demandée et ses révisions |
| Blocages | imagerie, avis, transport, demande d'aval en attente et son ancienneté, place d'aval confirmée, aide à domicile requise ou organisée |
| Traçabilité | âge de la dernière information, dernière disponibilité utilisée, identifiant de l'événement qui porte la date prévisionnelle |

L'âge exact ne sort pas de la vérité : seule la tranche (moins de 65, 65-74, 75-84, 85 et plus) est livrée.

Un séjour apparaît dès qu'un mouvement ou une évaluation est disponible. Il disparaît quand sa sortie est disponible, quand un autre patient est enregistré dans son lit, ou après 96 h sans information. **1,1 % des lignes sont des fantômes** : le patient est déjà parti, mais sa sortie n'est pas encore connue. La cible `cible_present_vrai` permet de l'apprendre.

**La date de sortie prévisionnelle** est le point le plus sensible, car c'est elle qui fera gagner, ou non, la version « agrégats + séjours ». Elle est produite au staff des jours ouvrés, avec un générateur aléatoire séparé : elle n'agit jamais sur la physique (c'est testé).

L'équipe estime le reste à faire à partir de trois éléments :
- le cours clinique prévu, bruité, avec un bruit qui diminue au fil du séjour et une tendance à l'optimisme ;
- les blocages visibles ;
- l'attente d'aval habituelle pour la destination *déclarée*, qui est fausse dans 20 % des cas au premier staff.

Elle ne voit jamais la sortie réalisée, ni les files futures.

Résultat, mesuré à midi :

| Indicateur | Valeur |
|---|---|
| Heures-séjour sans date prévisionnelle | 46 % (30 % des séjours n'en ont jamais, les autres pas encore ou pas saisie) |
| Jour exact | 25 % |
| À un jour près | 50 % |
| Erreur absolue moyenne | 2,8 jours |

Ces paramètres sont des **hypothèses**, réglables (`INFO` dans `hospsim.py`, dont `dsp_informativite`), à caler sur le CHU. Sur données synthétiques, le gain d'une couche séjour reflète d'abord ces hypothèses.

Cibles par séjour : présence vraie, sortie dans les 24, 48 et 72 h, durée restante, passage au statut sortant médical dans les 24 h. Les valeurs inconnues à cause de la censure au 31/12 sont vides.

## 4. Les notes cliniques

### Ce qu'elles contiennent

| Note | Pour qui | Quand | Versions |
|---|---|---|---|
| Observation des urgences | Patients venus des urgences | Commencée 0,3 à 2,5 h avant la décision d'hospitaliser | Complément après appel de la famille (55 %), relecture le lendemain (10 %) |
| Observation d'entrée | Tout patient admis | 1 à 14 h après l'admission ; le matin si l'admission est nocturne | Complément (30 %) |
| Recueil infirmier | 80 % des admis | 0,3 à 5 h après l'admission | Une seule |

Les notes mêlent, selon des probabilités propres à chaque type, des informations de sept natures :
- motif et conclusion, certaine ou en hypothèse ;
- antécédents et traitements ;
- mode de vie : vit seul, aidant, aides en place ;
- troubles cognitifs et perte d'autonomie récente ;
- autonomie et mobilité ;
- oxygène et isolement ;
- examens et avis prévus, besoin d'évaluation sociale, orientation envisagée.

**Ce qu'elles ne contiennent jamais** : une date de sortie, une durée de séjour, une destination réalisée. C'est contrôlé, de même que l'absence de toute date postérieure à la rédaction.

### Les difficultés volontairement présentes

- **Négations** (18 % des faits) : « Pas de troubles cognitifs connus », « Aucune aide en place ».
- **Hypothèses** (5 %) : « Possible syndrome démentiel débutant ? », « AEG : cause néoplasique ? dépressive ? ».
- **Copier-coller périmés** (12 % des observations d'entrée) : un fait social inversé, parfois suivi de sa source, « (cf. CRH 2023) ».
- **Erreurs** (5 % des observations des urgences).
- **Pièges cliniques** : une désorientation aiguë dans une confusion n'est pas un trouble cognitif chronique.
- **Bruit de rédaction** : abréviations, fautes de frappe, rubriques absentes.
- **Disponibilité décalée** : 16 à 46 % des versions, selon le type, ne sont lisibles que plus de 2 h après le début de leur rédaction (signature tardive).
- **Ajouts séparés** : une version n'efface jamais la précédente ; elle ajoute un complément daté.

### Comment éviter la fuite

Chaque variable extraite n'est utilisable qu'à partir de `h_utilisable`, l'heure entière qui suit la disponibilité de la version.

Pour la joindre à la couche séjour, utiliser **l'état documentaire**, pas l'extraction brute. Joindre la dernière note efface ce qu'une note précédente avait établi, quand la nouvelle n'en parle pas.

```python
e = pd.read_csv("data/apprentissage/etat_notes_asof.csv.gz", low_memory=False).sort_values("h_utilisable")
s = pd.read_csv("data/apprentissage/sejours_asof.csv.gz", low_memory=False).sort_values("h")
s = pd.merge_asof(s, e.drop(columns=["split"]), left_on="h", right_on="h_utilisable", by="sejour_id",
                  direction="backward")
s["autonomie_anciennete_h"] = s.h - s.autonomie_h_source   # âge de l'information, variable par variable
```

Règles de l'état documentaire :
- la nouvelle mention dont la disponibilité est la plus récente donne la valeur courante ; recopier une mention dans une version ultérieure ne change pas sa priorité ;
- une absence de mention n'efface rien ;
- `<variable>_conflit` signale que des notes disponibles se contredisent, par exemple un copier-coller périmé face à une observation récente ;
- `<variable>_source` et `<variable>_h_source` donnent le type de note et la disponibilité de la version qui a introduit la mention ;
- `<variable>_note_id_source`, `_version_source`, `_ts_redaction_source` et `_extrait_source` permettent de retrouver cette mention. La date de rédaction ne prétend pas dater l'événement clinique sous-jacent.

Le journal observé est requis pour distinguer un fait recopié d'une nouvelle affirmation : `etat_documentaire(lignes_extraites, notes_observees)`. Le CSV d'extraction reste une lecture de chaque version complète. Les versions doivent être consécutives et fonctionner par ajout ; un historique incomplet ou une réécriture est rejeté, car il exige une autre méthode de suivi des mentions.

### La vérité annotée et l'extracteur de référence

Chaque version porte la liste des faits qu'elle affirme, avec :
- la variable et la valeur ;
- le statut : documenté, négation ou hypothèse ;
- l'exactitude : vrai, faux, périmé ou prévision ;
- l'extrait et sa position exacte dans le texte.

C'est la référence pour évaluer un extracteur, ce qui demanderait une annotation manuelle sur données réelles.

L'extracteur fourni (`extraction.py`) est à règles explicites, avec détection de la négation et de l'hypothèse. Il donne un point de comparaison, pas un objectif. Son lexique ne couvre que les tournures de la banque principale. La période de test mêle une banque de tournures inédites, pour mesurer la robustesse.

La mesure retenue est le **triplet exact** : variable, valeur et statut tous justes. Une valeur inversée compte comme une erreur, pas comme une détection réussie.

| Variable | Triplet exact avant le test : rappel / précision | Pendant le test : rappel / précision |
|---|---|---|
| Vit seul | 97 % / 100 % | 60 % / 100 % |
| Aides en place | 99 % / 100 % | 68 % / 100 % |
| Troubles cognitifs | 98 % / 100 % | 53 % / 100 % |
| Perte d'autonomie récente | 99 % / 100 % | 51 % / 100 % |
| Niveau d'autonomie | 97 % / 100 % | 55 % / 100 % |
| Motif, oxygène, isolement, examens et avis prévus | 98-100 % / 100 % | 98-100 % / 100 % |

Valeurs inversées : 13 sur environ 112 000 mentions avant le test (motif et incertitude, sur des fautes de frappe), et 2 pendant le test.

Deux lectures :
- **Les scores avant le test sont élevés par construction**, puisque le même auteur a écrit les gabarits et les règles. Ils vérifient la chaîne, pas la difficulté réelle du texte clinique.
- **Les deux erreurs qui comptent restent visibles.** L'extracteur rate environ une tournure sur deux qu'il n'a jamais vue. Il reprend aussi pour vrais les faits périmés : 666 cas, dont 38 % seulement sont signalés, et uniquement quand la note cite sa source. L'état documentaire les fait apparaître comme conflits quand une autre note dit le contraire.

Un extracteur par modèle de langage devra faire mieux sur ces deux points, mesuré contre la même vérité.

### Ce que ces notes permettent, et ce qu'elles ne permettent pas

Les situations cliniques et sociales sont tirées en cohérence avec ce que le moteur simule déjà : âge, dépendance, unité, oxygène, isolement, destination, aide à domicile, durée. Les notes portent donc un signal sur l'aval. Par exemple, quand l'extracteur trouve une perte d'autonomie récente, 41 % des patients sortent vers un SMR ou un EHPAD, contre 16 % sinon.

Mais ce signal, nous l'avons programmé. Ces notes servent à tester la chaîne : disponibilité, versions, extraction, négations, fuites. **Elles ne mesurent pas ce que les vraies notes apporteraient à HospitalOS.** Pour cela, il faut des notes réelles avec l'historique de leurs versions, reliées aux trajectoires de séjour.

## 5. Chaîne de décision et identification

Chaque jour à 9 h, pour chaque unité :

1. **Recommandation HospitalOS.** Chaque levier est recommandé avec une probabilité `q_reco_*`, journalisée et fonction des seules colonnes de `decisions.csv.gz`. Elle reste entre 0,05 et 0,95 quand le levier est applicable : c'est un tirage d'exploration, qui garantit la positivité.
2. **Exposition.** Le cadre consulte l'écran 85 % des jours.
3. **Validation ou initiative.** Une recommandation vue est validée avec une probabilité propre au levier. Sans recommandation vue, le cadre suit son habitude. Dans les deux cas, il dispose d'une information cachée : l'afflux attendu aux urgences dans les 24 h. Cette information pèse aussi sur l'attente à venir. Ses probabilités ne sont pas dans `causal/`, comme dans un vrai service ; elles sont dans `verite/politique_cadre.csv.gz`, pour l'audit.
4. **Exécution.** Un levier engagé peut échouer : renfort non pourvu, aucun patient éligible. `x_*` vaut 1 seulement si le levier a réellement agi.

| Levier | Recommandé | Validé si vu | Initiative sans recommandation vue | Exécuté |
|---|---|---|---|---|
| Anticipation des sorties | 32 % | 67 % | 14 % | 26 % |
| Lits supplémentaires | 8 % | 56 % | 2 % | 6 % |
| Renfort soignant | 34 % | 66 % | 16 % | 26 % |
| Accélération de l'aval | 58 % | 74 % | 22 % | 35 % |

**Ce que cela permet de tester :**
- **L'effet de recommander est identifiable sur données observées**, puisque la recommandation est tirée avec des probabilités connues.
- **L'effet d'exécuter ne l'est pas** par simple ajustement sur les colonnes journalisées, à cause de l'information cachée du cadre. La recommandation peut servir d'instrument ; l'exclusion est vraie par construction.
- La vérité des trois familles permet de mesurer l'erreur de chaque estimateur.

La comparaison naïve des jours avec et sans action montre l'ampleur du piège :

| Levier | Écart naïf, attente aux urgences sur 72 h (patient-heures) | Effet vrai (famille B) |
|---|---|---|
| Lits supplémentaires | +15,2 | −3,2 |
| Anticipation des sorties | +15,9 | +0,3 |
| Renfort soignant | +6,8 | +0,1 |
| Accélération de l'aval | +6,1 | −0,1 |

Les jours d'action sont des jours de tension. Un modèle qui apprend sur ces corrélations conclurait que les lits supplémentaires aggravent l'attente.

## 6. Vérité causale : trois familles de contrefactuels

Pour chaque jour et chaque unité, 18 rejeux de 72 h depuis l'état exact, avec les mêmes aléas :

| Famille | Scénarios | Estimand |
|---|---|---|
| A, levier seul puis rien | `aucun` + 4 leviers + `renfort_soignant_pourvu` | Effet d'**engager** le levier (échec d'exécution compris), sans aucune décision ensuite ; effet d'un renfort réellement présent |
| B, action imposée puis politique | `factuel`, `aucun` + 4 leviers + `renfort_soignant_pourvu` | Effet d'**engager** le levier ce jour-là (échec compris), la politique en vigueur (recommandeur + cadre) s'appliquant ensuite partout ; effet d'un renfort réellement présent |
| C, recommandation imposée puis politique | `aucune` + 4 leviers | Effet de recommander, non-adoption et échecs compris |

Effet moyen sur 72 h (différence avec `aucun` ou `aucune` de mêmes jour et unité ; familles A et B les jours où le levier s'applique, famille C tous les jours) :

| Levier | Attente aux urgences, unité / pôle (patient-heures) : A | B | C | Minutes de soins non couvertes, unité : A | B | C |
|---|---|---|---|---|---|---|
| Lits supplémentaires | −4,0 / −10,2 | −3,2 / −9,1 | −1,4 / −4,0 | +278 | +221 | +89 |
| Accélération de l'aval | −0,2 / −0,4 | −0,1 / −0,3 | −0,03 / −0,08 | −2 | −2 | −1 |
| Anticipation des sorties | +0,5 / +0,1 | +0,3 / −0,2 | +0,1 / −0,1 | −10 | −11 | −6 |
| Renfort soignant, engagé (échec de pourvoi compris) | +0,1 / +0,1 | +0,1 / 0,0 | 0,0 / 0,0 | −207 | −176 | −54 |
| Renfort soignant, réellement présent | +0,1 / +0,1 | +0,1 / 0,0 | | −280 | −242 | |

Lecture :
- **B est plus faible que A.** La politique en vigueur compense en partie : sans lits supplémentaires imposés, le cadre en ouvre parfois le lendemain.
- **C est plus faible que B.** Une recommandation de lits supplémentaires n'est validée que 46 % des jours, et exécutée 41 %. C'est l'ordre de grandeur que mesurerait un essai qui randomise les recommandations.
- **Les compromis de la v0.2 demeurent.** Les lits supplémentaires réduisent l'attente mais dégradent la charge ; le renfort agit sur la charge, pas sur les flux.
- **L'interaction de pôle aussi.** Anticiper les sorties d'une unité libère des lits que prennent d'abord les patients des autres unités.

Les jours où plusieurs leviers sont engagés (32 % des décisions) sont couverts par le scénario `factuel`. Les interactions entre leviers ne sont pas décomposées.

## 7. Réalisme mesuré

| Indicateur | Médecine | Gériatrie | Pneumologie | Cardiologie | Repère public |
|---|---|---|---|---|---|
| Durée moyenne de séjour (j) | 6,6 | 11,3 | 6,2 | 4,6 | 5,5 j en MCO, toutes disciplines (DREES, 2023) |
| Occupation des lits ouverts | 0,87 | 0,87 | 0,88 | 0,87 | 77,8 % en MCO, tous services (DREES, 2024) ; plus en médecine d'aval |
| Attente décision → lit, médiane / 90e centile | 2 h / 11 h | 2 h / 6 h | 3 h / 14 h | 2 h / 6 h | Hospitalisés : environ 5 h 20 aux urgences au total (DREES, 2023) |
| Attente > 4 h / > 12 h | 14 % / 10 % | 12 % / 7 % | 17 % / 11 % | 11 % / 8 % | |
| Patients hébergés (dont rapatriés) | 16 % (78 %) | 16 % (93 %) | 17 % (67 %) | 10 % (76 %) | |
| Sorties le vendredi / le week-end | 20 % / 13 % | 19 % / 9 % | 21 % / 12 % | 20 % / 15 % | Pic du vendredi, creux du week-end |
| Ratio charge/capacité ; heures au-delà de 1,15 | 0,87 ; 16 % | 0,93 ; 21 % | 0,93 ; 22 % | 0,83 ; 15 % | |
| Avis spécialisé / aide à domicile requis | 19 % / 15 % | 17 % / 16 % | 23 % / 15 % | 21 % / 16 % | |

Les sorties du week-end baissent en gériatrie (11 % en v0.2, 9 % ici) : l'aide à domicile ne s'organise que les jours ouvrés.

## 8. Vérifications

- **57 contrôles de cohérence** (`controles.py`), tous réussis. Ils reprennent les 30 contrôles de la v0.2 et en ajoutent :
  - 2 pour le correctif de fusion : mentions recopiées sans rafraîchissement, provenance vérifiable dans les ajouts observés ;
  - 6 en v0.4 pour les notes : horloges et versions en ajout seul, aucune date postérieure à la rédaction, aucune mention de sortie future, annotations conformes au texte, notes dans la période, extraction alignée ;
  - 5 en v0.4.1 : annotations complètes sur les marqueurs explicites, faits conformes à la vérité, absence de contradiction hors erreurs volontaires, renfort pourvu toujours présent, état documentaire sans effacement ni source future ;
  - 14 en v0.3, qui portent sur :
  - séjours figés au 31/12 ;
  - chaîne recommandation-exécution cohérente ;
  - absence des probabilités du cadre dans `causal/` ;
  - découpage des décisions et des contrefactuels, sans franchissement ;
  - trois familles complètes ;
  - nombres aléatoires communs dans chaque famille : un levier sans effet, ou une recommandation non vue, ne change rien ;
  - scénario factuel identique à l'action imposée correspondante et à la vérité ;
  - couche séjour : liste fermée de colonnes, disponibilité avant l'instant, jamais avant l'admission vraie, lignage de la date prévisionnelle, découpage, cibles conformes.
- **54 tests** (`tests.py`), tous réussis, dont 24 tests de mutation et 21 cas unitaires de l'extracteur. Les tests de mutation corrompent volontairement les données et vérifient que les contrôles échouent :
  - correctif de fusion : date d'un fait recopié artificiellement rafraîchie, identifiant de source inventé ;
  - v0.4.1 : annotation d'oxygène supprimée, erreur volontaire étiquetée « vrai », contradiction d'assemblage ajoutée, valeur effacée dans l'état documentaire, renfort « pourvu » absent ;
  - v0.4 : sortie future ajoutée dans une note, note réécrite au lieu d'être complétée, note disponible avant sa rédaction, annotation d'une variable interdite ;
  - date future sur un séjour censuré ;
  - fenêtre franchissant une frontière marquée « train » ;
  - exécution sans validation ;
  - factuel altéré ;
  - colonne privilégiée ajoutée à la couche séjour ;
  - date prévisionnelle remplacée par la vraie ;
  - information séjour postérieure à l'instant ;
  - et les 6 mutations de la v0.2.
- **Tests de moteur**, dont les nouveaux :
  - les informations du staff ne changent pas la physique ;
  - imposer les actions factuelles reproduit le factuel ;
  - une recommandation non vue est sans effet ;
  - les livraisons futures et les doublons ne changent pas la couche séjour ;
  - les notes sont reproductibles, et couper le journal à une heure T ne change aucune note disponible avant T.
- **Reproductibilité à l'octet** : deux générations avec la même graine produisent les 19 fichiers de données identiques. Les 19 fichiers de la v0.3 sont identiques à l'octet en v0.4 : seules les notes s'ajoutent.

Ces vérifications portent sur la cohérence interne. Elles ne valident aucun réalisme empirique.

## 9. Comparer agrégats et séjours : comment lire le résultat

Le protocole proposé compare trois versions sur les mêmes périodes : agrégats seuls ; agrégats + séjours ; puis, sur données réelles, variables cliniques ciblées. Sur ce corpus, la comparaison des deux premières **vérifie la tuyauterie et l'absence de fuite. Elle ne mesure pas la valeur réelle de la couche séjour.** Celle-ci dépend surtout de la qualité de la date prévisionnelle et des blocages, que nous avons programmée. Pour la mesurer, il faut des données réelles, une période réservée et des seuils fixés d'avance.

La version clinique n'est pas simulée : sans mécanisme clinique honnête, elle n'apprendrait que du bruit. Sur données réelles, le premier candidat serait le passage d'un traitement intraveineux à un traitement oral. Les codes PMSI (GHM, CIM-10) sont exclus en entrée : ils sont codés après la sortie.

## 10. Limites

- **Pas de calibration locale.** Les paramètres sont des ordres de grandeur nationaux ou des hypothèses. « Ultra réaliste » ne sera acquis qu'après comparaison avec un établissement, sur une période réservée et avec des tolérances fixées d'avance.
- **Pré-entraînement.** Un modèle pré-entraîné sur ce corpus apprend les hypothèses du simulateur. Critère proposé : le pré-entraînement n'est gardé que s'il améliore une validation sur données réelles, avec un intervalle de confiance qui exclut zéro.
- **Une seule réalisation.** Cent graines du même simulateur ne valent pas cent hôpitaux. Pour la suite, il faut faire varier les mécanismes et leurs paramètres, et réserver des configurations entières au test.
- **Modélisation.** La charge est un indicateur construit, pas un score SIIPS. Les effectifs sont des nombres par rôle. Les urgences ne sont modélisées qu'à partir de la décision d'hospitalisation. Les réadmissions ne sont pas réinjectées. Le changement d'heure n'est pas modélisé. Les chambres sont individuelles. L'aval est une attente par patient, pas un réseau de SMR. Surveillance continue et compétences spécifiques ne contraignent pas encore les lits.
- **Couche séjour.** L'isolement et l'oxygène sont fixés à l'admission. La destination demandée et la date prévisionnelle sont des signaux bruités des mécanismes du moteur ; leurs lois d'erreur sont inventées.
- **Couche causale.** Le recommandeur simulé lit l'état vrai à travers les colonnes journalisées ; un recommandeur réel lirait l'état connu. L'information cachée du cadre est une construction unique (l'afflux attendu) ; d'autres confusions existent en réalité. Les interactions entre leviers ne sont pas décomposées.
- **Variabilité.** L'occupation varie plus qu'en réalité : de 0,69 à 0,97 en moyenne mensuelle, et jusqu'à 0,47 sur une semaine d'octobre en gériatrie, quand le tirage n'amène que 3 puis 6 demandes hebdomadaires au lieu d'environ 12. Les lits libres ne sont comblés que par le pôle, pas par le reste de l'hôpital.
- **Notes.** Les formulations sont d'un seul auteur et en nombre fini ; aucune note réelle n'a servi de modèle. Les situations sociales sont tirées en cohérence avec l'issue du séjour, ce qui fixe arbitrairement leur valeur prédictive. Pas de traitements en cours détaillés, pas de résultats biologiques chiffrés exploitables, pas de passage de l'intraveineux à l'oral. Pas de noms : le texte réel, lui, en contient, et sa pseudonymisation est un chantier à part entière.
- **Scénarios inventés.** La grippe, les canicules, la panne du système d'information d'octobre et les pannes d'imagerie ne reconstituent aucun événement réel.

## 11. Reproduire

Python 3.10+, `numpy`, `pandas` (`matplotlib` pour les figures).

```bash
cd generateur
python run.py --sortie ../data          # environ 3 min sur 2 cœurs : calibrage, simulation, contrefactuels, vues
python controles.py ../data             # 57 contrôles, écrit rapport_controles.json et manifest.json
python realisme.py ../data --figures    # réalisme, couche séjour, notes, effets par famille, biais naïf
python tests.py                         # 54 tests
```

Pour appliquer uniquement le correctif documentaire à une v0.4.1 existante, lancer `python refusion_notes.py ../data`, puis `python controles.py ../data`. Cette opération ne relance pas le monde simulé.

Options de `run.py` : `--seed`, `--annee`, `--unite-focale` (MED_POLY, CSG, PNEUMO, CARDIO), `--echelle unite`, `--sans-contrefactuels`, `--processus`.

| Fichier | Rôle |
|---|---|
| `hospsim.py` | Moteur : aléas exogènes, lits, services, flux, charges, chaîne de décision, informations du staff |
| `observation.py` | Livraisons du système d'information et vues d'unité |
| `parcours.py` | Couche séjour telle que connue, cibles par séjour |
| `textes_notes.py` | Banque de formulations (principale et hors vocabulaire) |
| `notes.py` | Situations cliniques et sociales, rédaction des notes versionnées, vérité annotée |
| `extraction.py` | Extracteur de référence, fusion par mention et évaluation contre la vérité |
| `refusion_notes.py` | Recalcul des seuls états documentaires depuis les notes observées |
| `run.py` | Calibrage, simulation, contrefactuels, écriture |
| `controles.py`, `tests.py`, `realisme.py` | Vérifications |

## Sources des repères

- DREES, *Les établissements de santé*, édition 2025, fiche 10 (durée moyenne de séjour 2023) ; édition 2026 (occupation MCO 2024).
- DREES, *Études et résultats* n° 1334, mars 2025 (enquête Urgences 2023).
- Roussel M. et al., *Overnight Stay in the Emergency Department and Mortality in Older Patients*, JAMA Intern Med 2023;183(12):1378-1385.
- Wei J. et al., *Predicting individual patient and hospital-level discharge using machine learning*, Communications Medicine 2024;4:236.
