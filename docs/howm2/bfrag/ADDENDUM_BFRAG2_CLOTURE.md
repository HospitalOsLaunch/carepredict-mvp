# Addendum de clôture B-FRAG 2 — précisions d'interprétation

**Date** 17 novembre 2026, décision n° 8.

**Statuts :** `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`.

**Ce que cet addendum ne change pas.** Le rapport historique `RAPPORT_BFRAG2.md`, les mesures, les gels
(`FREEZE1_PROTOCOL.json`, `FREEZE2_BFRAG2.json`) et les verdicts restent **intacts** (empreintes inchangées,
test d'invariance du pilote). Cet addendum précise la portée des phrases du rapport ; il ne recalcule rien
sur l'ancienne CONF.

## a) Historique (question A)

- **La marge a été fixée avant CONF.** La marge d'équivalence ±0,02 figure au § 10 de `PROTOCOLE_BFRAG2.md`
  (« `EQUIVALENT` si l'IC est dans [−0,02 ; +0,02] »). Traces :
  - fichier haché au gel 1 (sha256 `2f01e6e1…7c8aa58`, registre **#71** `protocol_freeze_bfrag2`, 10:47:53 UTC) ;
  - codée dans `bfrag2_analyse.py` (`verdict_auc(…, 0.02, …)`), hachée au gel 2 (registre **#88**, 11:20:14 UTC) ;
  - les deux gels précèdent la première commande CONF (registre **#90**, 11:20:23 UTC).

  Le verdict `EQUIVALENT` n'est donc pas une qualification post hoc. L'empreinte actuelle du protocole est
  toujours `2f01e6e1…`.
- **Portée.** L'équivalence S2–S1 porte sur :
  - les **variables** S2 définies, c'est-à-dire des variations à 6 et 24 h, des comptes d'événements, des durées
    et un délai de publication ;
  - les **modèles** testés : LR et HGB bornés, configuration commune LR C = 0,01 ;
  - la **cible** (début de rupture à 72 h) et la **marge** de ±0,02 d'AUC conditionnelle.

  Elle ne prouve **pas** que toute l'information du passé est contenue dans l'état instantané. D'autres résumés
  historiques, d'autres modèles, une autre cible ou une marge plus fine pourraient montrer une différence.

## b) Garde-fous (question C)

La phrase « aucune dégradation » du rapport doit se lire : **aucune dégradation statistiquement mise en
évidence**. Les intervalles à 98,33 % laissent possibles certaines aggravations :

| Garde-fou | Borne haute de l'IC à 98,33 % |
|---|---|
| Soins non couverts | +68 min par décision |
| Minutes de rupture | +1 |
| File terminale | +0,02 |
| Part de l'attente en unité A | +0,006 (IC 95 %) |

Aucune marge de non-infériorité n'avait été préétablie : **aucune non-infériorité n'est revendiquée**.

## c) O (planificateur privilégié)

La différence O − F = +21 patients-minutes [−95 ; +161] n'est pas significative. Cela **ne démontre pas**
l'équivalence de F et O. O est un système privilégié particulier : moteur et régime vrais, M = 32 tirages,
même opérateur de choix. Il n'a **aucune garantie d'optimalité**.

## d) Choix a posteriori

La « meilleure action a posteriori » est le minimum, action par action, de l'attente moyenne sur les
**8 futurs d'évaluation eux-mêmes**. C'est un minimum empirique rétrospectif : il bénéficie de l'information
future et d'un effet de sélection, puisque le minimum de 10 moyennes bruitées est biaisé vers le bas. Ce n'est
**pas** l'optimum décisionnel accessible en espérance.

Le ratio de « 62 % de la marge restante » est **descriptif**, rapporté à ce minimum empirique. Il ne mesure pas
une fraction démontrée de la marge optimale récupérée.

## e) Causes du déficit de F en anticipation (question B)

L'écart O − F (+0,098 d'AUC conditionnelle) et le déficit de F face aux références apprises sont compatibles
avec **plusieurs causes** :

- l'information privilégiée d'O (θ, régime et état vrais) ;
- les approximations du prior (uniforme REF, non informé par famille) et du nowcast L4-N ;
- le bruit Monte-Carlo.

Un même nombre de tirages (M = 32) n'implique ni une même variance des scores ni un même effet sur les rangs.
F et O ont des distributions de probabilités différentes, et l'attaque du bruit sur les rangs dépend de la
dispersion des scores. **Aucune attribution causale exclusive n'a été démontrée.** La phrase du rapport selon
laquelle l'écart « désigne l'inférence de F » doit être lue comme une hypothèse, non comme un résultat.

## f) Monte-Carlo

L'étude de stabilité (`MC_STABILITY_DEV.json`) a été faite **avant** la correction du calendrier. Elle ne
valide pas complètement la version corrigée. Le bruit Monte-Carlo peut modifier des classements et des choix
d'actions ; son effet et sa direction doivent être **mesurés**, pas affirmés.

La vérification ciblée faite après correction, sur DEV et VAL seulement, est rapportée dans
`VERIFICATION_NUMERIQUE_BFRAG2.md` (décision n° 8, § 4). L'« atténuation des AUC » mentionnée dans le rapport
est une attente théorique (bruit indépendant des étiquettes). Elle n'a pas été mesurée.

## g) Décomposition descriptive du gain F − R1 (CONF-S enregistrée, aucune nouvelle évaluation)

Source : `evidence/howm2_bfrag2w/DECOMPOSITION_F_R1.json` (registre #122). 24 structures, 72 décisions.
Contribution d'un groupe = Σ(attente R1 − attente F) / 72.

| Groupe (exclusif) | Décisions | Structures | Gain cumulé (pm) | Gain moyen (pm) | Contribution | F meilleur / R1 meilleur | Heures-agents F / R1 |
|---|---|---|---|---|---|---|---|
| même action | 35 | 22 | 0 | 0 | 0 | 0 / 0 | 80 / 80 |
| F coordination, R1 autre | 16 | 13 | 6 943 | 434 | **96,4** | 12 / 3 | 0 / 120 |
| R1 coordination, F autre | 7 | 6 | 6 068 | 867 | **84,3** | 4 / 3 | 56 / 0 |
| même ressource, autre créneau | 11 | 8 | 5 293 | 481 | **73,5** | 8 / 2 | 88 / 88 |
| une des deux = aucune action | 1 | 1 | 0 | 0 | 0 | 0 / 0 | 0 / 8 |
| autre ressource, même créneau | 1 | 1 | −17 | −17 | −0,2 | 0 / 1 | 8 / 8 |
| autre ressource, autre créneau | 1 | 1 | 0 | 0 | 0 | 0 / 0 | 8 / 8 |
| **Total** | 72 | 24 | 18 288 | — | **253,984375** | — | — |

La somme des contributions vaut exactement le résultat enregistré (écart 0).

**Lecture descriptive.** L'écart n'est pas porté par la seule action de coordination :

- 38 % de l'écart vient des décisions où F choisit la coordination et R1 un renfort ;
- 33 % vient de celles où R1 choisit la coordination et F un renfort. Dans ce groupe, F fait mieux 4 fois sur 7
  et le gain moyen est élevé, mais il repose sur 7 décisions ;
- 29 % vient d'un meilleur choix de créneau pour la même ressource.

Le nombre de fois où une action est choisie ne permet pas de lui attribuer le bénéfice. Cette décomposition
explique l'écart observé ; **elle ne constitue pas une nouvelle preuve confirmatoire**. Elle corrige donc la
phrase du rapport selon laquelle « l'essentiel du bénéfice total vient de l'action historique ». Cette phrase
concernait le bénéfice face à l'inaction, et non l'écart F − R1.
