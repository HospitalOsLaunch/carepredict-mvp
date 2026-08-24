"""
CarePredict — Pipeline d'ingestion : passages aux urgences (DREES) → schéma canonique.

Source : "Séries longues corrigées du nombre de passages aux urgences 2017-2023"
         DREES / Ministère des Solidarités et de la Santé — Licence Ouverte 2.0
         https://www.data.gouv.fr/datasets/series-longues-corrigees-du-nombre-de-passages-aux-urgences-2017-a-2023-en-france

Schéma source (4 champs) :
    date         dd/mm/yyyy
    dep          code département (texte)
    libelle_dep  libellé département
    nb_passages  passages quotidiens corrigés (décimal — résulte d'un calage Denton-Cholette)

Produit :
    - DataFrame canonique (site, ts, load_proxy, surge_flag, covariables calendaires)
    - surge_flag par département (régime de forte charge, déf. percentile saisonnier)
    - découpe train / calib / test TEMPORELLE (pas de fuite), pour conformal split + Mondrian

Usage :
    python carepredict_ingest.py                 # télécharge la vraie source DREES
    python carepredict_ingest.py --synthetic     # fallback hors-ligne (SIIPS-like)
    python carepredict_ingest.py --dep 75 33 59  # restreindre à des départements
"""

from __future__ import annotations

import argparse
import io
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

# URL stable de la ressource CSV (API data.gouv.fr — redirige vers le fichier DREES)
DREES_CSV_URL = "https://www.data.gouv.fr/api/1/datasets/r/b0005488-e2a9-455a-ae33-b3263d06d119"

# Départements à couverture partielle (à écarter ou traiter à part — cf. doc DREES)
PARTIAL_COVERAGE_DEPS = {"972", "974", "976", "2A", "2B", "90", "973", "48"}


# --------------------------------------------------------------------------- #
# 1. CHARGEMENT
# --------------------------------------------------------------------------- #
def load_drees(url: str = DREES_CSV_URL) -> pd.DataFrame:
    """Charge le CSV DREES depuis data.gouv.fr. Réseau requis."""
    import urllib.request

    print("[load] téléchargement DREES …", file=sys.stderr)
    with urllib.request.urlopen(url, timeout=120) as resp:
        raw = resp.read()
    # Le fichier est en UTF-8, séparateur ';' (standard data.gouv.fr FR). On tente les deux.
    for sep in (";", ","):
        try:
            df = pd.read_csv(io.BytesIO(raw), sep=sep, dtype={"dep": str})
            if {"date", "dep", "nb_passages"}.issubset(df.columns):
                print(f"[load] OK — séparateur '{sep}', {len(df):,} lignes", file=sys.stderr)
                return df
        except Exception:
            continue
    raise RuntimeError("Schéma DREES inattendu — vérifier la source.")


def make_synthetic(
    n_deps: int = 5, start="2017-01-01", end="2023-12-31", seed: int = 7
) -> pd.DataFrame:
    """Fallback hors-ligne avec saisonnalité et surges hivernales/caniculaires."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, end, freq="D")
    doy = dates.dayofyear.values
    frames = []
    for k in range(n_deps):
        base = 200 + 80 * k
        # saisonnalité annuelle : pic hivernal (épidémies) + bosse estivale (canicule/trauma)
        winter = 40 * np.cos(2 * np.pi * (doy - 15) / 365)  # max début janvier
        summer = 18 * np.exp(-((doy - 200) ** 2) / (2 * 12**2))  # bosse mi-juillet (canicule)
        weekly = 25 * (np.isin(dates.weekday, [0, 6])).astype(float)  # lundi/dimanche plus chargés
        noise = rng.normal(0, 12, len(dates))
        # surges épidémiques : quelques hivers avec pics marqués
        surge = np.zeros(len(dates))
        for yr in range(2017, 2024):
            peak = pd.Timestamp(f"{yr}-01-10") + pd.Timedelta(days=int(rng.integers(-20, 20)))
            if peak in dates:
                idx = dates.get_loc(peak)
                width = int(rng.integers(10, 25))
                amp = rng.uniform(50, 120)
                lo, hi = max(0, idx - width), min(len(dates), idx + width)
                xs = np.arange(lo, hi)
                surge[lo:hi] += amp * np.exp(-((xs - idx) ** 2) / (2 * (width / 2) ** 2))
        val = np.clip(base + winter + summer + weekly + surge + noise, 0, None)
        frames.append(
            pd.DataFrame(
                {
                    "date": dates.strftime("%d/%m/%Y"),
                    "dep": f"{90 + k:02d}",
                    "libelle_dep": f"SYNTH-{k}",
                    "nb_passages": val.round(1),
                }
            )
        )
    print(f"[load] SYNTHÉTIQUE — {n_deps} deps", file=sys.stderr)
    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------- #
# 2. CANONICALISATION → schéma CarePredict
# --------------------------------------------------------------------------- #
def to_canonical(
    df: pd.DataFrame, deps: list[str] | None = None, drop_partial: bool = True
) -> pd.DataFrame:
    """Mappe DREES vers le schéma CarePredict (site, ts, load_proxy, covariables)."""
    df = df.copy()
    raw_dates = df["date"].astype(str).str.strip()
    date_sample = raw_dates.dropna().head(100)
    iso_rate = date_sample.str.match(r"^\d{4}-\d{2}-\d{2}").mean()
    date_format = "%Y-%m-%d" if iso_rate > 0.50 else "%d/%m/%Y"
    df["ts"] = pd.to_datetime(raw_dates, format=date_format, errors="coerce")
    df["site_id"] = df["dep"].astype(str)
    raw_load = df["nb_passages"].astype(str).str.replace(",", ".", regex=False)
    df["load_proxy"] = pd.to_numeric(raw_load, errors="coerce")
    if df["ts"].isna().mean() > 0.50:
        sample = raw_dates.head(3).tolist()
        raise ValueError(
            "Parsing date massif échoué dans to_canonical "
            f"(format tenté={date_format}, exemples={sample})"
        )
    if df["load_proxy"].isna().mean() > 0.50:
        sample = df["nb_passages"].astype(str).head(3).tolist()
        raise ValueError(f"Parsing nb_passages massif échoué dans to_canonical (exemples={sample})")
    df = df.dropna(subset=["ts", "load_proxy"])

    if drop_partial:
        df = df[~df["site_id"].isin(PARTIAL_COVERAGE_DEPS)]
    if deps:
        df = df[df["site_id"].isin([str(d) for d in deps])]

    # covariables calendaires connues à l'avance
    df["dow"] = df["ts"].dt.dayofweek
    df["doy"] = df["ts"].dt.dayofyear
    df["week"] = df["ts"].dt.isocalendar().week.astype(int)
    df["month"] = df["ts"].dt.month
    df["is_weekend"] = df["dow"].isin([5, 6]).astype(int)
    # encodages cycliques (meilleurs que l'ordinal pour la saisonnalité)
    df["doy_sin"] = np.sin(2 * np.pi * df["doy"] / 365.25)
    df["doy_cos"] = np.cos(2 * np.pi * df["doy"] / 365.25)
    df["dow_sin"] = np.sin(2 * np.pi * df["dow"] / 7)
    df["dow_cos"] = np.cos(2 * np.pi * df["dow"] / 7)

    cols = [
        "site_id",
        "ts",
        "load_proxy",
        "dow",
        "doy",
        "week",
        "month",
        "is_weekend",
        "doy_sin",
        "doy_cos",
        "dow_sin",
        "dow_cos",
    ]
    return df[cols].sort_values(["site_id", "ts"]).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# 3. SURGE FLAG — régime de forte charge, défini par site et saison
# --------------------------------------------------------------------------- #
def add_surge_flag(df: pd.DataFrame, q: float = 0.90, by_season: bool = True) -> pd.DataFrame:
    """
    surge_flag = charge au-dessus d'un seuil haut, calculé PAR SITE.
    by_season=True : seuil relatif au mois (sinon un hiver entier serait 'surge', ce qui
    n'aide pas à distinguer un pic anormal d'une saisonnalité attendue).
    On garde aussi un surge_flag_abs (seuil annuel global) pour comparaison.
    """
    df = df.copy()
    # seuil global par site (référence absolue)
    thr_abs = df.groupby("site_id")["load_proxy"].transform(lambda s: s.quantile(q))
    df["surge_flag_abs"] = (df["load_proxy"] >= thr_abs).astype(int)

    if by_season:
        # seuil par (site, mois) : capture le pic anormal RELATIF à la saison
        thr_seas = df.groupby(["site_id", "month"])["load_proxy"].transform(lambda s: s.quantile(q))
        df["surge_flag"] = (df["load_proxy"] >= thr_seas).astype(int)
    else:
        df["surge_flag"] = df["surge_flag_abs"]

    rate = df["surge_flag"].mean()
    print(f"[surge] taux surge global = {rate:.1%} (cible ≈ {1 - q:.0%})", file=sys.stderr)
    return df


# --------------------------------------------------------------------------- #
# 4. DÉCOUPE TEMPORELLE train / calib / test (pour conformal)
# --------------------------------------------------------------------------- #
@dataclass
class Split:
    train: pd.DataFrame
    calib: pd.DataFrame
    test: pd.DataFrame

    def summary(self) -> str:
        def rng(d):
            return (
                f"{d['ts'].min().date()} → {d['ts'].max().date()}  "
                f"({len(d):,} obs, surge {d['surge_flag'].mean():.1%})"
            )

        return (
            f"  train : {rng(self.train)}\n  calib : {rng(self.calib)}\n  test  : {rng(self.test)}"
        )


def temporal_split(
    df: pd.DataFrame, train_frac=0.70, calib_frac=0.15, require_surge_in_test=True
) -> Split:
    """
    Découpe TEMPORELLE (jamais aléatoire — fuite garantie sinon sur série temporelle).
    train → fit du modèle ; calib → scores de non-conformité ; test → évaluation
    de la couverture.
    require_surge_in_test : vérifie que le test contient des épisodes de surge (sinon le test
    de couverture sous surge n'a aucun sens).
    """
    df = df.sort_values("ts")
    cuts = df["ts"].quantile([train_frac, train_frac + calib_frac]).values
    t0, t1 = pd.Timestamp(cuts[0]), pd.Timestamp(cuts[1])

    train = df[df["ts"] < t0]
    calib = df[(df["ts"] >= t0) & (df["ts"] < t1)]
    test = df[df["ts"] >= t1]

    if require_surge_in_test and test["surge_flag"].sum() == 0:
        raise ValueError("Aucun épisode de surge dans le test — ajuster la découpe ou le seuil.")
    return Split(train, calib, test)


# --------------------------------------------------------------------------- #
# 5. CONFORMAL — split classique + Mondrian (stratifié surge)
# --------------------------------------------------------------------------- #
def conformal_intervals(
    y_calib, yhat_calib, yhat_test, alpha=0.10, surge_calib=None, surge_test=None
):
    """
    Retourne des intervalles à (1-alpha) par deux méthodes :
      - 'split'   : un seul quantile de non-conformité global (l'actuel, ~0.70 en surge)
      - 'mondrian': un quantile PAR régime (normal / surge) → restaure l'échangeabilité par strate

    y*, yhat* : arrays alignés. surge_* : arrays binaires (requis pour mondrian).
    Score de non-conformité : |y - yhat| (résidu absolu).
    """
    res_cal = np.abs(np.asarray(y_calib) - np.asarray(yhat_calib))
    n = len(res_cal)

    def q_level(m):
        # quantile conforme fini-échantillon
        return min(1.0, np.ceil((m + 1) * (1 - alpha)) / m)

    out = {}
    # --- split global ---
    q_split = np.quantile(res_cal, q_level(n), method="higher")
    out["split"] = {"lo": yhat_test - q_split, "hi": yhat_test + q_split, "q": q_split}

    # --- Mondrian (stratifié) ---
    if surge_calib is not None and surge_test is not None:
        surge_calib = np.asarray(surge_calib).astype(bool)
        surge_test = np.asarray(surge_test).astype(bool)
        qmap = {}
        for regime in (False, True):
            mask = surge_calib == regime
            if mask.sum() >= 20:
                qmap[regime] = np.quantile(res_cal[mask], q_level(mask.sum()), method="higher")
            else:
                qmap[regime] = q_split  # repli si trop peu d'exemples
        q_test = np.where(surge_test, qmap[True], qmap[False])
        out["mondrian"] = {
            "lo": yhat_test - q_test,
            "hi": yhat_test + q_test,
            "q_normal": qmap[False],
            "q_surge": qmap[True],
        }
    return out


def coverage_report(y_test, intervals, surge_test):
    """Couverture marginale ET conditionnelle (par régime) — la métrique qui compte."""
    y = np.asarray(y_test)
    surge = np.asarray(surge_test).astype(bool)
    rows = []
    for method, iv in intervals.items():
        covered = (y >= iv["lo"]) & (y <= iv["hi"])
        width = np.mean(iv["hi"] - iv["lo"])
        rows.append(
            {
                "method": method,
                "cov_global": covered.mean(),
                "cov_normal": covered[~surge].mean() if (~surge).any() else np.nan,
                "cov_surge": covered[surge].mean() if surge.any() else np.nan,
                "width_mean": width,
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# 6. BASELINE saisonnière (pour Brique A — ce que le world model doit battre)
# --------------------------------------------------------------------------- #
def seasonal_baseline(train, test):
    """
    Baseline = moyenne par (site, mois, jour-de-semaine) apprise sur train.
    C'est l'adversaire de la Brique A : si le RSSM/JEPA ne bat pas ça, il n'apporte rien.
    Retourne yhat_test aligné sur test.
    """
    key = ["site_id", "month", "dow"]
    table = train.groupby(key)["load_proxy"].mean().rename("yhat")
    merged = test.merge(table, on=key, how="left")
    # repli : moyenne par site si combinaison absente
    site_mean = train.groupby("site_id")["load_proxy"].mean()
    merged["yhat"] = merged["yhat"].fillna(merged["site_id"].map(site_mean))
    return merged["yhat"].values


def skill_score(y_true, yhat_model, yhat_baseline):
    """Skill score = 1 - MAE_model / MAE_baseline. > 0 ⇔ le modèle bat la baseline."""
    mae_m = np.mean(np.abs(y_true - yhat_model))
    mae_b = np.mean(np.abs(y_true - yhat_baseline))
    return 1 - mae_m / mae_b, mae_m, mae_b


# --------------------------------------------------------------------------- #
# MAIN — démontre le pipeline de bout en bout (sur la baseline, en attendant le RSSM)
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true", help="fallback hors-ligne")
    ap.add_argument("--dep", nargs="*", default=None, help="codes départements à garder")
    ap.add_argument("--out", default="carepredict_canonical.parquet")
    args = ap.parse_args()

    raw = make_synthetic() if args.synthetic else load_drees()
    canon = to_canonical(raw, deps=args.dep)
    canon = add_surge_flag(canon, q=0.90, by_season=True)

    print(
        f"\n[canonical] {len(canon):,} obs · {canon['site_id'].nunique()} sites · "
        f"{canon['ts'].min().date()} → {canon['ts'].max().date()}"
    )

    split = temporal_split(canon)
    print("\n[split temporel]")
    print(split.summary())

    # --- Brique A : baseline contre elle-même (remplacer yhat_model par le RSSM) ---
    yhat_base_test = seasonal_baseline(split.train, split.test)
    yhat_base_cal = seasonal_baseline(split.train, split.calib)

    # Démo : un "modèle" naïf = baseline + bruit, pour illustrer le skill score.
    # >>> Ici tu branches les prédictions du RSSM / JEPA-RSSM <<<
    rng = np.random.default_rng(0)
    yhat_model_test = yhat_base_test + rng.normal(0, 5, len(yhat_base_test))

    ss, mae_m, mae_b = skill_score(split.test["load_proxy"].values, yhat_model_test, yhat_base_test)
    print(
        f"\n[Brique A] MAE modèle={mae_m:.1f} · MAE baseline={mae_b:.1f} · "
        f"skill score={ss:+.3f}  ({'BAT la baseline' if ss > 0 else 'ne bat PAS la baseline'})"
    )

    # --- Test 2 : conformal split vs Mondrian, couverture par régime ---
    iv = conformal_intervals(
        y_calib=split.calib["load_proxy"].values,
        yhat_calib=yhat_base_cal,
        yhat_test=yhat_base_test,
        alpha=0.10,
        surge_calib=split.calib["surge_flag"].values,
        surge_test=split.test["surge_flag"].values,
    )
    rep = coverage_report(split.test["load_proxy"].values, iv, split.test["surge_flag"].values)
    print("\n[Test 2 — couverture conforme (cible 0.90)]")
    print(rep.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    print(
        "\n→ Lecture : 'split' chute typiquement sous 0.90 en cov_surge ; "
        "'mondrian' restaure la couverture surge au prix d'intervalles plus larges en surge."
    )

    canon.to_parquet(args.out, index=False)
    print(f"\n[out] schéma canonique écrit → {args.out}")


if __name__ == "__main__":
    main()
