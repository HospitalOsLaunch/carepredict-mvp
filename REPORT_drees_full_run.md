# Rapport diagnostic — run DREES complet

Commande exécutée :

```bash
PYTHONPYCACHEPREFIX=/tmp/carepredict_pycache .venv/bin/python run_drees_report.py
```

## Sortie console brute — tableau de couverture

```text
      method  cov_global  cov_normal  cov_surge  width_mean  width_surge  width_normal
       split       0.920       0.934      0.749     292.541      292.541       292.541
    mondrian       0.908       0.907      0.922     267.623      555.773       243.933
  cqr_global       0.900       0.901      0.886     130.258      136.254       129.766
cqr_mondrian       0.901       0.901      0.910     131.998      159.149       129.766
```

## CP2 — Surge flag (réel)

- Taux surge global : 10.129%. Attendu ≈ 10 %. VERDICT : OK.
- Points surge calib : 4046. Points surge test : 2713.
- Comptage surge par mois :

```text
 month  sum  count  mean
     1 2056  20181 0.102
     2 1863  18321 0.102
     3 2053  20181 0.102
     4 1961  19530 0.100
     5 2053  20181 0.102
     6 1957  19530 0.100
     7 2055  20181 0.102
     8 2053  20181 0.102
     9 1959  19530 0.100
    10 2056  20181 0.102
    11 1958  19530 0.100
    12 2053  20181 0.102
```

Lecture : le taux global est proche de 10 %. La distribution mensuelle reste assez homogène car le flag est défini par seuil saisonnier site×mois ; il détecte les pics relatifs dans chaque mois plutôt qu'un hiver entier.

## CP-TROUS — Continuité temporelle

- Grille pleine théorique : 93 sites × 2556 jours = 237,708.
- Lignes canoniques : 237,708. Jours manquants calculés : 0.
- Top départements par jours manquants :

```text
site_id  missing_days first_missing last_missing
     01             0                           
     02             0                           
     03             0                           
     04             0                           
     05             0                           
     06             0                           
     07             0                           
     08             0                           
     09             0                           
     10             0                           
     11             0                           
     12             0                           
     13             0                           
     14             0                           
     15             0                           
```

VERDICT : OK pour ce run. Aucun trou n'est détecté dans la grille canonique DREES après exclusion des départements partiels. Note de vigilance : `carepredict_quantile.make_feature_frame()` construit tout de même `lag_1`, `lag_7` et `ma7` par `group.shift()` / rolling sans réindexer chaque site ; une source future incomplète pourrait donc créer un enjambement silencieux. Aucun correctif appliqué dans ce passage.

## CP3 — Brique A (skill score réel)

- yhat_model : vraie tête quantile HGBR, médiane `q_med`.
- skill_score : +0.936.
- MAE modèle : 30.878. MAE baseline saisonnière : 485.675.
- VERDICT : OK.

## CP4 — Tableau de couverture réel

```text
      method  cov_global  cov_normal  cov_surge  width_mean  width_surge  width_normal
       split       0.920       0.934      0.749     292.541      292.541       292.541
    mondrian       0.908       0.907      0.922     267.623      555.773       243.933
  cqr_global       0.900       0.901      0.886     130.258      136.254       129.766
cqr_mondrian       0.901       0.901      0.910     131.998      159.149       129.766
```

(a) `cov_surge(split)` = 0.749. Synthétique de référence = 0.706. Le split décroche bien en surge, et plus fortement que la couverture globale.
(b) `cov_global(cqr_global)` = 0.900, `cov_global(cqr_mondrian)` = 0.901. VERDICT : OK.
(c) `cov_surge(cqr_mondrian)` = 0.910. Critère principal ≥ 0.90. VERDICT : OK.
(d) `width_surge(cqr_mondrian)` = 159.149, `width_normal(cqr_mondrian)` = 129.766. VERDICT : OK.

## CP5 — Échec statistique légitime vs bug

- Points surge dans la calibration : 4046.
- qhat CQR global appliqué aux deux régimes : 0.000.
- q_normal CQR-Mondrian : 0.000.
- q_surge CQR-Mondrian : 11.447.

Diagnostic : la strate surge calib n'est pas sous-peuplée (<50) ; elle contient 4046 points. Si `cov_surge(cqr_mondrian)` est sous 0.90, ce n'est donc pas expliqué par un manque brut de points calib, mais plutôt par un décalage calib→test, la définition saisonnière du surge, ou les lags sur grille non continue.

## Bonus — Croisement quantiles HGBR

- Taux crossing calib avant réordonnancement : 0.045%.
- Taux crossing test avant réordonnancement : 0.031%.
- VERDICT : OK.

## Décisions à valider

1. Garder un contrôle de continuité avant les lags, même si le run DREES actuel n'a aucun trou. Si une future source est incomplète, réindexer chaque site sur une grille quotidienne continue puis décider une politique explicite (interpolation, forward-fill borné, ou exclusion de fenêtres).
2. Ajouter un diagnostic de stabilité calib→test par régime surge : distributions de résidus CQR calib vs test, par mois et par site. Justification : `q_surge` peut être calibré correctement sur calib mais ne pas transférer si les épisodes test sont plus extrêmes.
3. Tester une définition de surge non seulement site×mois mais aussi épidémie/hiver global pour la lecture clinique. Justification : le flag saisonnier uniformise mécaniquement le taux par mois, ce qui masque les pics hivernaux attendus dans CP2.
4. Ne pas modifier la calibration CQR avant d'avoir arbitré les points 1–3 : le tableau actuel est un mauvais chiffre honnête et exploitable pour décider.
