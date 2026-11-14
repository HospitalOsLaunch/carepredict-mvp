# P5a — Évaluation réservée du planificateur public v6 (14 novembre 2026)

**Autorisation :** (ii), « P5a uniquement », adoptée explicitement par l'utilisateur (réponse
« Oui, j'adopte (ii) P5a ») ; texte conservé (`evidence/decision_support/p5/ACCORD_ii_P5a_TEXT_ADOPTED.txt`),
relevé `docs/decision_support/P5_DECISIONS_v4_P5a.json`, registre n° 36. Protocole :
P5-PROTO-3 + 3.1 (D13). **Rien d'autre n'est lancé** : P5b, D16, P6, installation, nouvelle
exécution A5, push restent fermés. Arrêt après cette livraison.

**Verdict R1 (principal) : `exploratory`.** Ce verdict est imposé par la règle de précision
pré-enregistrée, et non par un résultat défavorable : la demi-largeur projetée sur le
développement valait 33,9 minutes-soignant, au-dessus de la limite de 7,5 (δ/2). La lecture a
donc été **déclarée exploratoire avant le gel F_a**. Elle n'a pas été requalifiée après lecture,
bien que l'intervalle observé du gain soit très au-dessus de δ.

Toutes les données sont **synthétiques**. Aucun bénéfice hospitalier réel, aucune calibration réelle
ni aucune validation clinique ne sont établis. Statuts inchangés : `PARTIAL_WITH_CHECKPOINT`,
`PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`.

## 1. Déroulé et preuves

| Étape | Registre | Détail |
|---|---|---|
| Accord (ii) consigné | n° 36 | ouverture des lots P5.3 et P5.5 au compteur |
| Code P5a : exécuteur, analyse, script ; descripteurs PS-EXP-1 ajoutés à l'adaptateur | — | `p5a.py`, `p5a_analysis.py`, `scripts/p5_p5a.py`, `eval_adapter.py` |
| Tests avant E4 | n° 38–39 | un vrai défaut trouvé et corrigé (intervalle d'une colonne sans valeur), puis 68 réussis + 1 refus d'intégrité attendu |
| **E4** | n° 41–42 | graines inchangées, moteur v6 identique à `856a57c` |
| Tests sous E4 | n° 43 | **69/69** (`pytest_p5_1_E4.xml`) |
| Contrôle : réservé refusé sans F_a | n° 44 | code 4, rien de généré |
| Développement P5a_dev 10 × 10 | n° 45–46 | 100 parents ; 3 exclusions sur 103 candidats (2,9 %) ; 0 abstention ; aucun arrêt |
| Projection de précision | n° 47 | écart-type des moyennes par structure 94,8 ; demi-largeur projetée **33,9 > 7,5** ⇒ lecture **exploratoire** |
| **F_a** | n° 48–49 | `F_a.json` (`055a4d26…a6bc`) : 17 fichiers figés, δ, seuils, graine de bootstrap engagée en E0, précision et lecture déclarées |
| Réservé P5a_eval 30 × 10 | n° 50–52 | 3 segments d'environ 8 s, code 0 ; 300 parents ; 0 exclusion sur 300 candidats ; aucun arrêt |
| Analyse finale | n° 53 | bootstrap à deux étages, 2000 rééchantillonnages, graine engagée en E0 et vérifiée |

Le réservé a été lu **une fois**, après F_a. Aucun seuil, aucune population, aucune graine ni
aucun réglage n'a été modifié après lecture.

## 2. Résultats R1 (principal), par épisode, pondérés par structure, IC 95 %

| Quantité | Valeur | IC 95 % |
|---|---:|---|
| U pratique habituelle (minutes-soignant non couvertes / 24 h) | 1011,2 | 862,8 – 1164,4 |
| U plan v6 | 794,1 | 666,6 – 928,5 |
| U\* (minimum exact sur l'univers public) | 786,6 | 658,5 – 921,6 |
| **Gain P5a-1 = U_hab − U_plan** | **217,1** | **187,3 – 248,0** |
| Marge U_hab − U\* | 224,6 | 194,3 – 255,7 |
| **Part capturée (P5a-2, descriptive)** | **96,6 %** | 94,6 – 98,1 % (aucun écrêtage ; 0 rééchantillonnage sous δ) |
| Regret du plan (U_plan − U\*) | 7,5 | 4,2 – 12,2 |
| O_lex (diagnostic) : U_lex − U\* | 1,0 | 0,6 – 1,5 |
| U_fix (diagnostic, biaisé vers le bas avec K = 3) | 787,9 | — |

**Garde-fous :**
- 0 violation (aucun arrêt) ;
- plan choisi toujours dans l'univers public ;
- univers identique entre réalisations et régimes ;
- exclusions : 0 % ;
- **dégradation : 0 structure dégradée sur 30** (0 parent), borne de Clopper–Pearson unilatérale
  9,50 % ≤ 10 %. Événement observé : un parent est dégradé si la moyenne, sur les 3 réalisations,
  de (U_plan − U_hab) dépasse 15. C'est un **risque de dégradation limité** sous cet événement
  synthétique, pas une garantie clinique.

Recommandations : 281 `RECOMMENDATION_READY` et 19 `NO_ACTION_PREFERRED` (le plan habituel est
choisi, ce n'est pas une abstention) ; **0 abstention**. Plans choisis : 127 coordination seule,
45 renforts seuls, 109 combinaisons, 19 pratique habituelle. Univers : 7,9 plans en moyenne.

## 3. Décomposition coordination / renforts (descriptive, R1)

| Composante | Valeur | IC 95 % |
|---|---:|---|
| Mêmes renforts seuls : U_hab − U(r\*) | 100,4 | 73,9 – 128,3 |
| **Coordination à renforts égaux : U(r\*) − U(a\*)** | **116,7** | 101,2 – 132,0 |
| Coordination seule : U_hab − U(c\*) | 117,7 | 102,3 – 133,4 |
| Renforts après coordination : U(c\*) − U(a\*) | 99,4 | 74,0 – 126,3 |
| Interaction I = U(c\*) + U(r\*) − U(a\*) − U_hab | −1,0 | −4,0 – 1,8 |

- Environ **117 minutes-soignant par épisode** viennent du choix des séjours à coordonner, à
  renforts égaux.
- Environ **100** viennent des **moyens supplémentaires** : la pratique habituelle n'emploie aucun
  renfort.
- Seule la première part peut être présentée comme valeur du choix des patients. L'interaction est
  proche de 0.

Coûts : heures de renfort prévues 3,4 par épisode, réalisées 2,6 (renforts absents sous R1), dont
0,8 h prêtées par une autre unité. Interventions : 1,8. Descriptifs secondaires, plan contre
pratique habituelle :
- attente de lit : 9,4 contre 11,5 patients·h ;
- lits remis : 1,7 contre 1,6 ;
- pic PS-EXP-1 : 8,2 contre 8,9 ;
- heures au-dessus du seuil : 5,2 contre 6,8.

Minimum moyen par classe : coordination seule 890,2 ; renforts seuls 800,7 ; combinaison 740,9.

## 4. R2 (robustesse, ne relève pas un verdict R1)

Gain 213,5 [184,1 ; 244,2] ; part capturée 96,2 % [94,1 ; 97,8] ; regret du plan 8,3 ; 0 structure
dégradée sur 30 ; décomposition proche de R1 :
- renforts seuls 94,5 ;
- coordination à renforts égaux 119,0 ;
- interaction −1,3.

Heures réalisées : 2,4. Sous R2, les renforts demandés sont présents avec une probabilité de 0,5
et une corrélation par pool. Lecture : `exploratory` (robustesse seulement).

## 5. Limites (à lire avec les chiffres)

1. **Population construite et bornée** (A8) :
   - instant de décision unique, IDE seulement, 4 gabarits d'offres ;
   - le nombre d'offres est couplé au nombre de coordinations ;
   - pertes de soins habituelles élevées, environ 1000 minutes-soignant par épisode ;
   - les gains absolus en dépendent directement.
2. **Peu d'incertitude privée dans ce générateur** : U_fix ≈ U\* ≈ U_plan. Le planificateur v6,
   qui énumère tout l'univers avec 4 graines publiques, atteint presque le minimum exact. Le
   problème est facile ici ; cela ne prédit rien d'un environnement plus incertain.
3. **Pratique habituelle simulée** (HABITUAL-1), non validée sur le terrain, sans renfort : près
   de la moitié du gain vient des moyens ajoutés (§ 3).
4. **Précision** : la règle « demi-largeur ≤ 7,5 » ne pouvait pas être atteinte avec 30 structures
   et cette hétérogénéité entre structures (écart-type ≈ 95). Elle plafonne le verdict à
   « exploratoire ». Changer cette règle exigerait un nouvel amendement, **avant** toute nouvelle
   lecture réservée.
5. Moteur v6 inchangé. Les portes produit Python 3.11.9 exact et rejeu React indépendant restent
   ouvertes. Exécutions de l'auteur ; aucun rejeu indépendant n'est revendiqué.

## 6. Registre

| Lot | Utilisé | Plafond |
|---|---:|---:|
| P5.0 | 3,541 s | 30 s |
| P5.1 | 26,592 s | 130 s |
| P5.2 | 24,009 s | 40 s |
| P5.I | 8,557 s | 60 s |
| **P5.3** | **33,218 s** | 330 s |
| **P5.5** | 2,272 s (avant vérification de livraison) | 90 s |
| **Total** | **98,189 s** avant les notes et la vérification de livraison | 1200 s |

P0–P4 est inchangé, sans transfert. Terminal final : voir l'ancre livrée.

## 7. Suite (aucune décision prise)

(iii) P5b reste fermé. Avant tout accord, il faudra décider :
- du devis L2 ;
- du plafond P5.4 de 470 s ;
- du cas d'un ajustement M_ent de plus de 30 s à l'univers maximal ;
- de la règle de précision, qui a les mêmes conséquences pour P5b : 30 structures réservées
  avec une hétérogénéité comparable.

D16 et P6 restent fermés.
