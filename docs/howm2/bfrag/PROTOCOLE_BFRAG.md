# Protocole B-FRAG — fragilités dormantes, cascades et prévention

**Version** P1, du 17 novembre 2026 (décision n° 6). Gelé dans le registre B **avant toute mesure
comparative**.

**Statuts :** `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`.

**Portée.** Benchmark **synthétique**. Aucune convention ci-dessous n'est validée cliniquement.
Aucun entraînement, aucun réseau. Les comparateurs sont des règles et des estimateurs explicites.

## 0. Différences avec B amendé (`proposition_B_amende/`)

| Élément | B amendé (non adopté) | B-FRAG (ce protocole) |
|---|---|---|
| Objet | monde v2 avec un état caché qui pèse sur les décisions, porte G_ID | anticiper des ruptures et choisir des interventions, à information publique identique |
| Monde | générateur v2 nouveau (pôle de 6 unités, dérive) | moteur HOWM-1 gelé, avec générateur **dérivé** (capacité nominale et lits tampons) et scénarios superposés ; aucune source gelée n'est modifiée |
| Horizon | 6/24 h (M_pub) et décision 24 h | 6, 24, 72 et 168 h, trajectoire continue |
| Seuils | M_pub ≥ 0,02 ; marge ≥ 15 | **abandonnés** pour B-FRAG ; ils restent historiques. Critères propres (§ 8–9) |
| Comparateurs | règle, C_param, C_pub_snap, planificateur L4 | R0, R1, R2, F, O (§ 6) |
| Populations | REF2_TUNE (60) et REF2_CONF (200 + 24 × 4) | BFRAG_TUNE (48) et BFRAG_CONF (96) ; BFRAG_DEV (8) pour le calibrage du régime de fonctionnement, sans aucune méthode |
| Convention temporelle | état vrai après le pas t0 | décision au **début** du tick t0 : état vrai et public tous deux sans aucun événement de t0 (§ 2) ; conserve l'exigence « même instant pour les deux » |

## 1. Définitions opérationnelles

Une « cellule dormante » désigne une configuration d'entités, de ressources, de délais et de
dépendances. Ce n'est ni une catégorie biologique ni une catégorie clinique.

**Fragilité.** Faible marge, à t0, face à certaines perturbations. La fragilité est
**caractérisée par le scénario** (fiches du § 3) et mesurée par l'écart de devenir entre la
variante de base et la variante détendue, apparentée (§ 5). Une forte occupation ne suffit pas
(familles témoins SC4 à SC6).

**Déclencheur.** Événement pouvant faire franchir la limite. Exemples dans ce monde :
- baisse planifiée de capacité de nettoyage ;
- régime lent d'une équipe (m2) ;
- surcroît d'arrivées ;
- arrivée d'un patient en isolement lorsque les lits d'isolement sont occupés.

**Rupture**, pour une unité u.

*Compte suivi.* À la fin de chaque tick, on compte les patients de la file d'admission de u qui
attendent un lit admissible depuis **au moins 24 h**. C'est une convention **synthétique** :
- le simulateur ne fixe aucune limite d'attente ;
- une limite de 4 h ou de 12 h est franchie chaque nuit dans ce monde, à cause des heures de
  nettoyage (06 h–22 h), et ne distingue donc pas une rupture du régime normal ;
- la limite de 24 h et le seuil de 5 patients ont été fixés sur BFRAG_DEV, avant toute méthode.

*Règles :*
- **rupture** : ce compte ≥ **5** pendant au moins **1 h** (4 ticks) ;
- **début** : premier tick de cette période ;
- **fin et récupération** : compte < 5 pendant ≥ 2 h ;
- **fusion** : deux périodes séparées par moins de 2 h ne font qu'une ;
- **gravité** : patients-minutes comptés pendant les ruptures.

**Cascade** (descriptif). Débuts de rupture dans les **deux** unités à moins de 24 h d'écart.

**Récupération.** Retour sous la limite, selon la règle ci-dessus.

**Rupture active à t0.** Monde rapporté comme tel et **exclu** des mesures d'anticipation : ce ne
serait pas une anticipation.

## 2. Temps, observabilité, vérité terrain

**Instant de décision.** Début du tick t0 = jour 2, 07 h 00 (tick 220, heure 55). La phase de mise
en régime va de l'heure 0 à t0 : 55 h d'historique public.

**État vrai.** Moteur cloné par le générateur dérivé **avant** tout événement du tick t0.

**Public.** Observations dont la date de publication est **strictement** antérieure à 15·t0
minutes. Aucun événement du tick t0 n'y figure, même à retard nul : ni plan habituel, ni demande
de transport. Ni l'état vrai ni l'état public ne contiennent d'événement de t0.

**Action.** Appliquée à t0 sur l'état de départ propre à chaque système. Le premier pas traite
ensuite t0.

**Après t0.** Aucun plan de fond : les opérations habituelles intégrées à l'opérateur gelé,
communes et fixées, s'appliquent seules (placements FIFO, transports aux heures habituelles,
nettoyage FIFO de 06 h à 22 h). **Aucune boucle fermée.** Ce n'est **pas** une replanification
adaptative sur 7 jours, qui reste une étape ultérieure distincte.

**Horizons** : 6, 24, 72 et 168 h, issus d'une **même** trajectoire continue de 168 h, avec les
mêmes identités, les mêmes encours et la même horloge : il n'y a jamais de réinitialisation
journalière.

**Observation terminale à 168 h**, par unité :
- file d'attente et attente maximale ;
- lits sales ou en nettoyage ;
- séjours prêts mais non partis.

Les patients encore en attente comptent pour l'attente qu'ils ont déjà accumulée, sans
extrapolation. Un report au-delà de 168 h n'est **jamais** qualifié de « rupture évitée » : la
charge terminale est toujours rapportée.

**Vérité terrain.** Les labels et le diagnostic O utilisent l'état vrai.

**Entrées publiques** (R0, R1, R2 et F) :
- observations publiques ;
- description statique publique (unités, lits, rosters, c_tr, c_cl) ;
- capacité nominale planifiée ;
- calendrier public de baisse de capacité.

**Clés de simulation des méthodes publiques.** Elles sont **dérivées de l'information publique**,
par une empreinte de l'historique public. Jamais : graine du monde, identifiant de scénario,
famille, θ vrai, régime vrai ou marqueur de rupture (tests T-B2 et T-B2b).

## 3. Scénarios : fiches et mélange

**Générateur dérivé.** Loi HOWM-1 gelée, sauf sur un point : les arrivées sont pilotées par la
**capacité nominale** planifiée. Les **lits tampons** (physiques, publics) s'y ajoutent comme
marge. C'est une hypothèse synthétique ; elle a été motivée par le constat, sur DEV, que le monde
natif est saturé de façon chronique.

**Paramètres.** θ reste dans le support a priori REF, pour que les postérieures L4 restent
valides. Le mélange compte 6 familles, à parts égales, fixées par l'indice : i mod 6.

| Famille | Dépendance et marge | Déclencheurs possibles | Indices publics et date de disponibilité | Propagation hypothétique | Actions admissibles (coût, délai d'effet) | Pourquoi l'effet peut dépasser 24 h | Hypothèses non validées |
|---|---|---|---|---|---|---|---|
| SF1 fenêtre de nettoyage | 1 nettoyeur ; nettoyage lent (60–75 min) ; arrivées 1,00–1,15 ; tampon 35–50 % | régime lent nettoyage ; surcroît d'arrivées | lits sales, publiés avec retard ; arrivées ; durées de nettoyage passées | lits sales accumulés la nuit → file du matin → attentes qui se cumulent sur plusieurs jours | mode compatibilité 24 h (nul) ; renfort IDE 4 h ; coordination des transports | le stock de lits sales et la file persistent d'un jour à l'autre | durées et capacités synthétiques |
| SF2 fenêtre de transport | 1 brancardier ; transport 70–90 min ; confirmation 80–120 min ; tampon 35–50 % | séjours prêts en attente de transport, servis aux heures habituelles 11 h et 15 h | séjours prêts ; demandes ; débuts et fins de transport | sorties reportées → lits bloqués → file | coordination immédiate des transports | les sorties manquées reportent l'occupation au créneau suivant ou au lendemain | règle de transport habituelle |
| SF3 baisse planifiée | 2 nettoyeurs, −1 le jour 3 de 06 h à 22 h (calendrier public) ; nettoyage 55–75 min ; tampon 35–50 % | la baisse elle-même, 23 à 39 h après t0 | calendrier connu à t0 | stock de lits sales le jour 3 → file des jours 3 et 4 | compatibilité ; coordination ; renfort | la baisse a lieu après 24 h | la publication du calendrier |
| SC4 charge élevée absorbable | 3 nettoyeurs, 3 brancardiers ; arrivées 1,05–1,15 ; tampon 50–60 % | surcroît d'arrivées | idem | absorbée par les marges | idem | — | — |
| SC5 baisse avec marge | 3 nettoyeurs, −1 le jour 3 ; nettoyage 30–45 min ; tampon 50–60 % | baisse planifiée | calendrier | absorbée | idem | — | — |
| SC6 charge faible | 2 et 2 ; arrivées 0,85–0,95 ; LOS 2,5–3,5 j ; tampon 50–60 % | rares | idem | — | idem | — | — |

**Dépendance commune à toutes les familles** : les lits d'isolement (25 % des lits) sont
compatibles avec tous, alors que les patients en isolement n'ont accès qu'à eux. C'est une
dépendance du moteur gelé, observée sur DEV : 20 à 100 % des attentes de 12 h ou plus.

**Couverture des cas obligatoires :**
- épisodes sans rupture ;
- charge élevée absorbable (SC4) ;
- charge modérée avec dépendance critique (SF1, SF2) ;
- perturbation absorbée grâce à une marge (SC5) ;
- règle simple suffisante (SF2 : coordination) ;
- agrégats initiaux proches mais dépendances différentes : paires de base et détendue de
  SF1 à SF3, avec les mêmes clés, donc le même état initial et les mêmes arrivées (T-B5).

**Contrôles appariés (TUNE seulement).** Pour SF1 à SF3, une variante **détendue** :
- SF1 : nettoyeur +1 ;
- SF2 : brancardier +1 ;
- SF3 : pas de baisse.

Elle est évaluée sous la politique de référence avec les mêmes clés d'évaluation. L'intervalle
regroupe la paire par monde.

**Fréquence des ruptures.** C'est celle **du benchmark**, non une fréquence hospitalière.

## 4. Itérations sur TUNE, au plus 3, toutes conservées

Chaque itération est une conception `docs/howm2/bfrag/DESIGN_Dk.json`. D2 est l'itération 1. Elle
est évaluée sur BFRAG_TUNE (48 mondes) avec toutes les méthodes.

**Critères de validité technique du benchmark** (V), fixés ici :
- **V1** : les tests T-B1 à T-B10 réussissent.
- **V2** : la prévalence de rupture à 168 h sous la politique de référence (mondes × réalisations,
  environnement vrai) est comprise entre 0,20 et 0,80.
- **V3** : au plus 10 % des mondes ont une rupture active à t0.
- **V4** : au moins 10 % des mondes n'ont aucune rupture, dans aucune réalisation, et la prévalence
  de SC6 est inférieure à la moyenne de SF1 à SF3.
- **V5** (descriptif) : la variante détendue réduit l'attente ; IC par famille rapporté.

**Règle de sélection.** On retient la **première** itération qui satisfait V1 à V4. Si aucune ne
les satisfait après 3 itérations, le verdict est `VALIDITE_NON_ETABLIE`, il n'y a pas de CONF, et
le travail s'arrête là.

**Ce qui se règle sur TUNE, à la conception retenue, puis se gèle :**
- les seuils d'alerte ;
- le choix des concurrents de F.

**Ce qui ne change jamais :** les définitions des §§ 1, 2, 7 et 8, qui sont fixées ici.

## 5. Populations et clés

| Population | Clés | Taille |
|---|---|---|
| BFRAG_DEV | `key("HOWM1", partition, i)`, enregistrées à l'exécution | 8 |
| BFRAG_TUNE | idem | 48 |
| BFRAG_CONF | idem | 96, générée seulement après le gel |

- Ces clés sont disjointes de G0, de HOWM2_* et des partitions C1.
- **Unité indépendante** : le monde. Les réalisations et la variante détendue sont imbriquées dans
  leur monde.
- **Réalisations d'évaluation** : E = 8 futurs frais (r = 1 à 8), communs à tous les plans d'un
  même monde.

## 6. Comparateurs (mêmes actions, contraintes et budgets)

Actions : les 16 plans admissibles de HOWM-1 à t0 :
- coordination des transports ;
- mode de nettoyage FIFO ou compatibilité pendant 24 h ;
- renfort de 4 h : aucun, pool IDE A, pool IDE B, ou prêt IDE de B vers A.

Le plan 0 est la **politique de référence**, c'est-à-dire l'habituel.

| Comparateur | Décision | Score d'alerte |
|---|---|---|
| **R0** | règle publique renforcée de HOWM-1 : coordination + compatibilité + pool IDE vers l'unité de plus forte pression | heuristique publique : max par unité de (file + lits sales ou en nettoyage − lits libres) / lits, + 0,5 si une baisse planifiée tombe dans les 48 h |
| **R1** | — | P(rupture dans h) sous le plan 0, estimée par M = 8 déroulés depuis l'**état public**, avec le fournisseur statistique B0-local-long (L2), capacité nominale, calendrier. Au-delà de 24 h, les arrivées reprennent le taux de la même heure de la journée (déclaré) |
| **R2** | planificateur sur R1 : argmin, sur les 16 plans, de l'attente moyenne sur 168 h (M = 8, aléas communs) ; égalités → moins d'interventions, puis indice | — |
| **F** | même planificateur | P(rupture) sous le plan 0 depuis F |
| **O** (diagnostic privilégié) | même planificateur | idem depuis O |

**F.** Postérieure L4 (θ, mécanisme, régime), estimation L4-N de l'état présent (convention
stricte du § 2), puis simulateur de structure du générateur avec les paramètres tirés. Clés
dérivées de l'historique public.

**O.** État vrai, θ et mécanisme vrais, régime vrai à t0. Ses clés de choix (101 à 108) sont
disjointes de l'évaluation (1 à 8) : O n'accède pas aux réalisations futures évaluées. Ce n'est ni
une borne ni une preuve d'optimalité.

**Choix des concurrents de F**, sur TUNE (conception retenue), puis gel :
- **décision** : celui de {R0, R2} qui a la plus petite perte moyenne ;
- **anticipation** : celui de {R0, R1} qui a la plus grande AUC à 72 h.

Les autres comparateurs sont toujours rapportés.

**Coûts.** Le temps de calcul de chaque méthode est journalisé par monde.

**Référence manquante.** Il n'existe aucun modèle régressif appris. Aucune victoire sur « toute
approche régressive » n'est revendiquée.

## 7. Mesures

### A. Anticipation

Les labels sont pris sous la **politique de référence** (plan 0), dans l'environnement vrai, pour
chaque réalisation r : y_h(w, r) = rupture débutant avant h. Une alerte est jugée contre ce devenir
de référence ; une rupture évitée par une intervention n'en fait donc pas une fausse alerte.

**Principal.** AUC à **72 h**, sur les paires (réalisation positive, réalisation négative) de mondes
différents, avec le score du monde. Mondes en rupture active à t0 exclus.

**Seuils d'alerte**, réglés sur TUNE puis gelés. Pour chaque méthode et horizon : le seuil qui
maximise J de Youden, sous la contrainte d'une proportion d'alertes ≤ 0,50.

**Secondaires**, par horizon :
- sensibilité ;
- ruptures manquées ;
- proportion de fausses alertes ;
- charge d'alerte effective ;
- avance moyenne avec les ratées comptées à 0, c'est-à-dire sans retrait du dénominateur ;
- Brier, pour les méthodes probabilistes (R1, F, O) ;
- résultats par famille (descriptifs).

Il y a une seule alerte par monde, à t0 : la fusion des alertes est triviale et la durée des
fausses alertes ne s'applique pas.

### B. Intervention

**Critère primaire** : attente cumulée pour un lit admissible, en **minutes-patient**, sur
(t0, t0 + 168 h], moyenne sur les E réalisations, pour le plan choisi par la méthode.

**Garde-fous et résultats distincts :**
- soins non couverts (minutes) ;
- fréquence, durée et gravité des ruptures ;
- cascades ;
- heures de renfort et nombre d'interventions ;
- refus de préconditions au moment du plan (contrainte) et au total ;
- charge terminale.

## 8. Analyse et verdicts (CONF)

**Gain décisionnel.** Gain = perte(concurrent gelé) − perte(F), par monde, moyenné sur les mondes.

**Intervalle.** IC 95 % par **bootstrap percentile en grappes de mondes**, B = 2 000, graine
`key("BFRAG", "bootstrap") mod 2^31`.

**Contraintes respectées** : aucun refus de précondition au moment du plan pour F.

| Verdict décisionnel | Condition |
|---|---|
| `GAIN_STATISTIQUE` | borne basse > 0 et contraintes respectées |
| `ABSENCE_DE_SUPERIORITE` | borne haute ≤ 0 |
| `INDETERMINE` | sinon |

**Anticipation.** ΔAUC72 = AUC(F) − AUC(concurrent gelé), même bootstrap. Libellés
`AVANTAGE_ANTICIPATION`, `ABSENCE_DE_SUPERIORITE` ou `INDETERMINE`, selon les mêmes règles.

**Validité technique.** Les critères V1 à V4 sont recalculés sur CONF et rapportés. Un défaut de
validité **bloque** l'interprétation.

**Campagne inachevée.** Statut `INCOMPLET`.

**Réseau appris** : **NON TESTÉ**.

**Analyses par famille et par horizon** : descriptives, sans correction préétablie.

**Portée.**
- Aucun seuil clinique ou économique n'est inventé.
- Un gain statistique n'est pas un gain produit suffisant : sa taille absolue, son coût et son
  incertitude sont rapportés.
- Aucun résultat défavorable ne démontre une impossibilité générale.

## 9. Gel avant CONF

**Contenu gelé** (`FREEZE_BFRAG.json`) :
- code de `src/hospitalos/bfrag/` et des scripts B-FRAG ;
- conception retenue ;
- seuils d'alerte et concurrents ;
- protocole et script d'analyse ;
- empreintes.

**G0-v2.** Il n'est gelé que comme **version technique identifiée**, dont le statut sépare
l'intégrité technique des résultats scientifiques. Un gel technique n'est pas un passage
scientifique.

## 10. Calcul et arrêt

Enveloppe commune de 11 400 s, CPU, dans le registre `BUDGET_LEDGER_HOWM2_B`.

| Lot | Plafond (s) |
|---|---:|
| CLOSE.C1 | 300 |
| BF.PREP | 600 |
| BF.TEST | 400 |
| BF.PILOT | 400 |
| BF.TUNE | 3 000 |
| BF.CONF | 3 000 (réservés à la confirmation) |
| BF.ANAL | 400 |
| BF.REST | 700 (réservés à la livraison) |
| Réserve non allouée | 2 600 |

**Conditions d'exécution :**
- 540 s par commande ;
- 4 processus au plus (≈ 0,3 Go chacun sur DEV ; mémoire mesurée et journalisée) ;
- un fichier par monde, écrit de façon atomique, reprenable ;
- début et fin de chaque commande journalisés.

**Paramètres** : M = 8 tirages par plan et par méthode ; E = 8 réalisations d'évaluation.

**Dimensionnement.** Si le pilote projette que CONF dépasse son lot, CONF est réduite **avant**
toute comparaison sur CONF, à 72 puis à 48 mondes en gardant le mélange. La réduction est
déclarée ; elle n'intervient jamais après avoir vu un effet.

## 11. Tests de validité (avant toute comparaison)

| Test | Objet |
|---|---|
| T-B1 | Même instant : dans un monde sans retard, S_pub(t0) = S_true(t0) champ par champ (lits, files, séjours). |
| T-B2 | Aucune observation publique publiée à ≥ 15·t0 ; aucun événement de t0 dans l'état vrai ni dans le public. |
| T-B2b | Les entrées des méthodes publiques ne contiennent ni graine ni identifiant de monde ; F et R1 ne dépendent pas de l'ekey (contrôle par permutation de l'ekey à information publique égale). |
| T-B3 | Continuité sur 168 h : les identités persistent ; arrivées = placements + croissance de la file, aucune perte. |
| T-B4 | Conservation des lits, à chaque heure : occupés + libres + sales + en nettoyage = lits physiques. |
| T-B5 | RNG stable : la variante détendue a les mêmes arrivées et le même état initial que la base. |
| T-B6 | Baisse planifiée respectée : aucun début de nettoyage au-delà de la capacité réduite. |
| T-B7 | Détecteur de rupture : séries synthétiques (fusion, durée minimale, seuil). |
| T-B8 | Générateur dérivé sans tampon = générateur gelé : observations identiques. |
| T-B9 | Fichiers gelés inchangés : G0, F1 et F-C1. |
| T-B10 | Un plan est appliqué une seule fois, à t0 ; aucun plan de fond après t0. |
