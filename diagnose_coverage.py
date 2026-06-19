"""
DIAGNOSTIC — pourquoi split/mondrian s'effondrent à ~0.15 de couverture.

Un conformal split correct est GARANTI ~0.90 par construction. 0.15 ⇒ bug d'alignement
entre la prédiction utilisée pour calculer les résidus de calib et celle évaluée en test.

Ce script ne corrige rien : il LOCALISE la faute. À lancer dans le repo carepredict-mvp :
    .venv/bin/python diagnose_coverage.py --synthetic

Il rejoue le pipeline étape par étape et imprime, à chaque jonction, QUELLE prédiction
alimente QUELLE méthode, plus des sanity checks qui doivent tous passer.
"""
from __future__ import annotations

import argparse

import numpy as np

from carepredict_ingest import (
    add_surge_flag,
    conformal_intervals,
    coverage_report,
    load_drees,
    make_synthetic,
    seasonal_baseline,
    temporal_split,
    to_canonical,
)


def check(name: str, cond: bool, detail: str = "") -> None:
    flag = "OK  " if cond else "FAIL"
    print(f"  [{flag}] {name}" + (f"  — {detail}" if detail else ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true")
    args = ap.parse_args()

    raw = make_synthetic() if args.synthetic else load_drees()
    canon = add_surge_flag(to_canonical(raw), q=0.90, by_season=True)
    split = temporal_split(canon)

    y_cal = split.calib["load_proxy"].values
    y_test = split.test["load_proxy"].values

    print("\n=== 1. ALIGNEMENT DES PRÉDICTIONS (le suspect n°1) ===")
    # La baseline DOIT être calculée sur calib ET test à partir du MÊME train.
    yhat_cal = seasonal_baseline(split.train, split.calib)
    yhat_test = seasonal_baseline(split.train, split.test)

    check(
        "yhat_cal aligné sur y_cal (même longueur)",
        len(yhat_cal) == len(y_cal),
        f"{len(yhat_cal)} vs {len(y_cal)}",
    )
    check(
        "yhat_test aligné sur y_test (même longueur)",
        len(yhat_test) == len(y_test),
        f"{len(yhat_test)} vs {len(y_test)}",
    )
    check("aucune NaN dans yhat_cal", not np.isnan(yhat_cal).any())
    check("aucune NaN dans yhat_test", not np.isnan(yhat_test).any())

    # Le test décisif : l'erreur de calib et l'erreur de test doivent avoir des ÉCHELLES
    # comparables. Si l'une est 10x l'autre, les prédictions ne sont pas homogènes.
    mae_cal = np.mean(np.abs(y_cal - yhat_cal))
    mae_test = np.mean(np.abs(y_test - yhat_test))
    ratio = max(mae_cal, mae_test) / max(1e-9, min(mae_cal, mae_test))
    print(f"\n  MAE calib = {mae_cal:.1f} · MAE test = {mae_test:.1f} · ratio = {ratio:.2f}")
    check(
        "échelles d'erreur calib/test homogènes (ratio < 2)",
        ratio < 2.0,
        "si ratio élevé : prédictions calib/test pas issues du même prédicteur",
    )

    print("\n=== 2. CONFORMAL SPLIT DE RÉFÉRENCE (doit donner ~0.90) ===")
    iv = conformal_intervals(
        y_calib=y_cal,
        yhat_calib=yhat_cal,
        yhat_test=yhat_test,
        alpha=0.10,
        surge_calib=split.calib["surge_flag"].values,
        surge_test=split.test["surge_flag"].values,
    )
    rep = coverage_report(y_test, iv, split.test["surge_flag"].values)
    print(rep.to_string(index=False, float_format=lambda x: f"{x:.3f}"))

    cov_split = rep.loc[rep["method"] == "split", "cov_global"].iloc[0]
    print()
    check(
        "split RÉFÉRENCE atteint ~0.90 (0.86–0.94)",
        0.86 <= cov_split <= 0.94,
        f"obtenu {cov_split:.3f}",
    )

    if 0.86 <= cov_split <= 0.94:
        print("\n  >>> Si CE split de référence est bon (~0.90) mais que run_all.py donne 0.15,")
        print("  >>> alors le bug est DANS run_all.py : il passe à split/mondrian les quantiles")
        print("  >>> de la tête HGBR (q_med) au lieu d'une prédiction dont les résidus de calib")
        print("  >>> ont été calculés de façon cohérente. Vérifier quelle 'yhat' alimente")
        print("  >>> conformal_intervals() dans run_all.py — calib et test doivent venir du")
        print("  >>> MÊME prédicteur, et coverage_report doit évaluer CE prédicteur.")
    else:
        print("\n  >>> Le split de référence est CASSÉ ici aussi → le bug est en amont")
        print("  >>> (add_surge_flag, temporal_split, ou seasonal_baseline). Remonter la chaîne.")

    print("\n=== 3. POINT DE CONTRÔLE run_all.py ===")
    print("  Ouvre run_all.py et vérifie ces 3 lignes :")
    print("   (a) la prédiction passée comme yhat_calib à conformal_intervals")
    print("   (b) la prédiction passée comme yhat_test à conformal_intervals")
    print("   (c) la prédiction contre laquelle coverage_report évalue les intervalles")
    print("  Les trois doivent référencer le MÊME prédicteur. Pour CQR c'est q_lo/q_hi de la")
    print("  tête ; pour split/mondrian ça DOIT être un point-estimate cohérent (q_med OU")
    print("  baseline), le même en calib et en test. Un mélange = couverture 0.15.")


if __name__ == "__main__":
    main()
