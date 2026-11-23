# Erratum — P5_P5b_REPORT.md (14 novembre 2026)

§ 5 (Budget), ligne « P5.0 / P5.1 » : **P5.1 = 57,221 s**, et non 51,735 s.

La commande n° 94 (suite P5 sous E8, 5,486 s, lot P5.1) avait été omise du tableau. Elle était
déjà incluse dans le total du registre. Aucune consommation nouvelle, aucune remise à zéro.

Valeurs exactes au terminal (134 enregistrements, 369,301 s / 1200 s, terminal `561264d5…b420`) :

| Lot | Utilisé |
|---|---:|
| P5.0 | 4,916 s |
| P5.1 | 57,221 s |
| P5.2 | 24,009 s |
| P5.I | 8,557 s |
| P5.3 | 51,324 s |
| P5.4 | 218,288 s |
| P5.5 | 4,986 s |

Le rapport et l'archive `HospitalOS_P5b_20261114.zip` (`4b13a141…3191`), vérifiés après
extraction (n° 134), ne sont pas modifiés. Le verdict et les résultats sont inchangés.

---

## Erratum 2 — portée de la borne de regret (§ 4, point 2), d'après la revue indépendante du 14 novembre 2026

Formulation du rapport : « Même un M_ent parfait n'aurait donc pas pu dépasser δ = 15 en moyenne sur
cette population. »

**Formulation corrigée.** Sur **l'échantillon réservé observé**, U_agg − U_ent ≤ U_agg − U\* :
l'écart récupérable par M_ent était donc borné par le regret moyen observé de M_agg, 12,09
minutes-soignant, sous δ = 15. Ce n'est **pas** une borne universelle pour le générateur. L'IC 95 %
de ce regret monte jusqu'à 17,19. Cette observation, faite après lecture, ne justifie ni de baisser
le seuil, ni de sélectionner des cas favorables à M_ent.

**Précisions ajoutées, issues de la revue :**
- **Précontrôle.** Il démontrait une différence d'**effets** entre jumeaux (environ 29,1
  minutes-soignant en moyenne quadratique). Le meilleur plan homologue ne change pourtant que pour
  30 des 300 parents comparables. Une information peut changer l'ampleur des conséquences sans
  changer la décision.
- **R2.** La structure dégradée correspond à deux situations : +21,67 et +30 minutes-soignant en
  moyenne contre la pratique habituelle. L'une n'emploie aucun renfort, donc ce signal ne
  s'explique pas seulement par l'absence de personnel demandé. R2 ne change pas le verdict R1, mais
  M_ent ne peut pas être présenté comme robuste dans tous les régimes testés.
- **Portée de P5b.** M_agg classe des plans déjà ciblés par le moteur explicite. P5b mesure
  l'apport des variables individuelles **supplémentaires** au modèle de classement, pas l'inutilité
  des données patients dans HospitalOS.

Le verdict R1 `insufficient`, les résultats, F_b et les archives livrées sont inchangés.
