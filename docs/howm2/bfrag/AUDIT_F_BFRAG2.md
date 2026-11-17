# Audit de spécification de F — B-FRAG 2

**Date** 17 novembre 2026, décision n° 7. Audit **de lecture** (code et plans), fait avant toute mesure
comparative. Aucune revendication de postérieur bayésien exact.

## 1. Version de F conservée

`core2.f_pairs` reproduit la chaîne historique `bfrag.core.f_samples` de B-FRAG 1, ligne à ligne :

1. `Ladder(REF, static, nominal)` ;
2. ingestion publique ;
3. `lad.context(…, 15·t0 − 1)` ;
4. `revealed_arrivals(…, 15·t0)` ;
5. `sample_world` (θ, mécanisme, ancre de régime) ;
6. `BFNowcastProvider` (convention stricte de publication) ;
7. `nowcast_engine` ;
8. simulateur `bf_provider` avec θ tiré.

Trois différences seulement, toutes de clé ou d'origine, aucune de modèle :

| B-FRAG 1 | B-FRAG 2 |
|---|---|
| origine fixe `T0` | toute origine `t0` |
| clé publique `public_key(inst)` | `public_key2(pub)` : statique, nombre d'observations, 20 premières et 5 dernières observations publiques |
| aucune répétition | paramètre `rep`, utilisé uniquement par l'étude de stabilité |

Le code de B-FRAG 1 n'est pas modifié (test T2-9).

## 2. Écarts entre le modèle de F et le monde

| Aspect | Monde B-FRAG 2 | Modèle de F | Conséquence attendue |
|---|---|---|---|
| **Prior de θ** | REF, puis plages **restreintes par famille** (D2) : SF1 `cl_min` 60–75 et `arr_mult` 1,00–1,15 ; SF2 `tr_min` 70–90 et `conf_tr_min` 80–120 ; SF3 `cl_min` 55–75 ; SC4 `arr_mult` 1,05–1,15 | prior **uniforme** sur les plages REF (`tr_min` 30–90, `cl_min` 30–75, `arr_mult` 0,85–1,15, …) ; la famille est inconnue | support correct (les plages D2 sont incluses dans REF) ; le prior est plus large et décentré, surtout pour SF1 et SF2, en bord haut. F sous-estime la lenteur tant que l'historique public est court (origines précoces) |
| **Mécanisme** | drapeaux de mécanisme tirés par REF à la structure | mélange postérieur sur les types REF (`m2`, `κ`, `simple`) | bien spécifié en forme ; le poids dépend de l'historique |
| **Régime** | régime caché vrai, en continu | ancre de régime tirée au dernier pas observé | l'état de régime est inféré, sans connaissance du vrai |
| **Capacité nominale et tampon** | arrivées pilotées par la capacité nominale ; lits physiques = nominal + tampon | `n_beds = nominal` (public) ; lits physiques dans `static` | spécification correcte (marge publique) |
| **Calendrier** | baisse planifiée publique (SF3, SC5) appliquée à la trajectoire de référence (correction `CORRECTION_CALENDAR.json`) et à tous les déroulés | `WithCalendar(drop)` dans les déroulés de F | cohérent |
| **Disponibilité de l'information** | observations publiées strictement avant `15·t0` | idem (`public_state`), nowcast des arrivées non publiées selon le délai postérieur | cohérent ; tests T2-1 et T2-2 |
| **Politique de fond** | opérateur gelé, sans plan de fond | idem dans les déroulés | cohérent |
| **Structure du simulateur** | générateur HOWM-1 dérivé | **même structure** (moteur gelé + `BFTruthProvider`) | avantage structurel de F : la classe de modèle est exacte, seuls les paramètres et l'état sont inférés. C'est la limite principale de toute comparaison avec des références apprises qui ne connaissent pas la classe du modèle |

## 3. Ce que F n'est pas

- Ce n'est **pas** un postérieur exact. Le postérieur L4 est factorisé (transport et nettoyage séparés), sur
  grille, et calculé sous l'hypothèse de la population REF. Le nowcast L4-N est une approximation par
  rejet, avec repli compté.
- Ce n'est **pas** un oracle. O garde l'avantage du θ vrai, du régime vrai et de l'état vrai.
- Aucune propriété de calibration n'est revendiquée. Le Brier est publié à titre descriptif.

## 4. Stabilité numérique (DEV)

Voir `MC_STABILITY_DEV.json` et `MC_CHOICE.json`.

- **Écart absolu moyen** entre répétitions : 0,02 à M = 32. La tolérance (≤ 0,10) est atteinte.
- **Rang** (Spearman ≥ 0,80) : tolérance atteinte seulement à M = 128.
- **Choix retenu** : M = 32, plafond budgétaire préenregistré.
- **Effet attendu** : le bruit Monte-Carlo, indépendant des étiquettes, atténue les AUC.
- **Décision** : accord des choix et regret nul entre répétitions à M = 32, mais sur 2 décisions DEV seulement.
