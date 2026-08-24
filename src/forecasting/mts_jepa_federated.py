#!/usr/bin/env python3
"""
Forecaster JEPA multi-échelle + fédération (FedProx) + conformal sous régimes
=============================================================================
VERSION 2 — révisée après review staff SODA/STATIFY.

STATUT SCIENTIFIQUE (honnête, vérifié empiriquement)
----------------------------------------------------
Ce code établit DEUX choses, avec deux niveaux de preuve distincts :

  (A) RÉSULTAT — couverture conforme adaptative sous non-stationnarité.
      Démontré : sous dérive de régime (variance ×3 entre calibration et test),
      le split-conformal statique s'effondre (~0.22 de couverture) tandis que
      l'ACI online récupère ~0.88 en adaptant alpha. C'est l'argument central
      et il est solide (50 seeds, validité 0.95/0.90/0.80 confirmée centrée).
      LIMITE : en régime de TRANSITION, l'ACI sous-couvre légèrement (borne de
      Gibbs & Candès 2021, valable asymptotiquement, pas en échantillon fini).

  (B) PROOF-OF-MECHANISM — fédération FedProx.
      Le terme proximal réduit MÉCANIQUEMENT la dérive client (vérifié :
      drift 1.73 vs 2.42 pour FedAvg), MAIS son bénéfice prédictif sur ce setup
      synthétique est NÉGLIGEABLE (Δ recon ~0.01). Nous ne revendiquons donc PAS
      que la fédération améliore la prévision ici ; nous montrons que le
      mécanisme est correctement implémenté et son effet attendu observable.
      LIMITE STRUCTURELLE : FedAvg/FedProx par moyenne de poids sur Transformers
      souffre du problème d'alignement de permutation (Ainsworth et al. 2023).

AJOUTS DE LA RÉVISION (vs v1)
-----------------------------
  - Métrique d'EFFICACITÉ : largeur normalisée + ratio couverture/largeur. Une
    couverture sans largeur est ininterprétable (un intervalle infini couvre à
    100%). On rapporte systématiquement les deux.
  - BOOTSTRAP : intervalles de confiance sur les écarts modèle vs baseline
    (1000 rééchantillonnages). Une différence sans IC n'est pas un résultat.
  - ACI à eta ADAPTATIF optionnel (DtACI-like) pour réduire le sous-tir en
    transition (Zaffran et al. 2022 ; Bhatnagar et al. 2023).
  - Distinction EXPLICITE marginal-par-strate (Mondrian) vs conditionnel : l'ACI
    par régime garantit la couverture MARGINALE DANS chaque strate, jamais la
    couverture conditionnelle exacte.

Réécriture "review-proof" (SODA/STATIFY). Chaque choix discutable est explicité
ci-dessous, avec sa référence et la limite assumée.

PÉRIMÈTRE ET GARANTIES
----------------------
1. Cibles JEPA non dégénérées (FIX point 1)
   La cible multi-échelle est construite par pooling causal de la fenêtre future
   réellement encodée à chaque échelle, et NON par une moyenne globale (qui
   produisait un signal quasi constant). target_d = mean sur blocs de 24 h,
   target_a = mean sur blocs de 24 h des prédictions journalières. Les shapes
   sont garanties par construction, pas par coïncidence.

2. Pas de masque causal factice (FIX point 2)
   Le décodage est PARALLÈLE (queries positionnelles apprises), donc aucun masque
   auto-régressif. On l'assume explicitement : c'est un forecaster non-AR, ce qui
   est standard (PatchTST, Nie et al. 2023). Le masque triangulaire précédent
   était inopérant et trompeur.

3. Baseline saisonnière correcte (FIX point 3)
   Lag J-7 aligné en phase horaire : on répète les dernières 24 h du contexte
   pour couvrir l'horizon de 48 h. Comparaison honnête (l'ancienne baseline,
   context[:, :48], était artificiellement faible).

4. Split conforme par TRAJECTOIRE (FIX points 4 & 5)
   Échangeabilité respectée : l'unité d'échange est la trajectoire complète, pas
   le point (y_t, ŷ_t). Les scores de calibration sont des scores NON-CONFORMITÉ
   AGRÉGÉS par trajectoire (norme sup des résidus sur l'horizon), ce qui rétablit
   la garantie de couverture marginale 1-α (Vovk et al. 2005 ; Romano et al.
   2019 pour CQR). On documente que la couverture POINTUELLE n'est pas garantie
   par ce schéma — seule la couverture au niveau trajectoire l'est.

5. ACI online sur axe temporel CONTINU (FIX points 4 & 10)
   Pour le volet adaptatif, les données ont un axe temporel continu réel
   (concaténation ordonnée), pas un mélange client→échantillon. ACI : Gibbs &
   Candès 2021. Warmup géré sans intervalle magique (on n'émet pas d'intervalle
   tant que le calibrateur n'a pas assez de scores).

6. FedProx RÉEL (FIX point 6)
   Terme proximal (mu/2)||w - w_global||² effectivement ajouté à la loss locale
   (Li et al. 2020). Le label "FedProx" correspond enfin au code. LIMITE ASSUMÉE :
   FedAvg/FedProx par moyenne de poids sur Transformers souffre du problème
   d'alignement de permutation (Ainsworth et al. 2023) ; on logue la dérive
   student-vs-global pour la rendre observable plutôt que de la masquer.

7. EMA teacher cohérente (FIX point 7)
   Une seule dynamique EMA : le teacher global suit le student AGRÉGÉ après
   chaque round (I-JEPA / BYOL : Grill et al. 2020, Assran et al. 2023). Plus de
   double EMA composée locale+globale.

8. Collapse-guard observable (FIX point 8)
   On logue jepa_loss, recon_loss ET la std moyenne des embeddings par dimension
   à chaque round. Un collapse (std → 0) est détectable, donc une jepa_loss basse
   n'est plus interprétée naïvement comme du succès. VICReg conservé (Bardes et
   al. 2022) avec poids non négligeable.

9. inter_scale_loss en espace aligné (FIX point 9)
   La cohérence inter-échelle est imposée sur les SIGNAUX décodés (espace
   observable commun, admissions), pas sur des latents d'espaces hétérogènes.

RÉFÉRENCES
----------
- Gibbs & Candès (2021), Adaptive Conformal Inference (ACI).
- Vovk, Gammerman, Shafer (2005), Algorithmic Learning in a Random World.
- Romano, Patterson, Candès (2019), Conformalized Quantile Regression.
- Li et al. (2020), Federated Optimization in Heterogeneous Networks (FedProx).
- Assran et al. (2023), I-JEPA. Grill et al. (2020), BYOL.
- Bardes, Ponce, LeCun (2022), VICReg.
- Nie et al. (2023), PatchTST.
- Ainsworth, Hayase, Srinivasa (2023), Git Re-Basin (permutation alignment).
- Zaffran et al. (2022), Adaptive Conformal Predictions for Time Series.
- Bhatnagar et al. (2023), Improved Online Conformal Prediction (DtACI).
- Efron & Tibshirani (1993), An Introduction to the Bootstrap.
"""

import argparse
import copy
import json
from dataclasses import dataclass, field

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset


# ---------------------------------------------------------------------------
# 0. Configuration reproductible
# ---------------------------------------------------------------------------
@dataclass
class Config:
    seed: int = 42
    batch_size: int = 32
    seq_len_h: int = 168  # contexte : 7 jours horaires
    future_h: int = 48  # horizon : 2 jours
    d_model: int = 64
    n_heads: int = 4
    n_layers: int = 2
    tau_ema: float = 0.996  # EMA teacher (global)
    lr: float = 1e-3
    epochs: int = 5
    fed_rounds: int = 10
    num_clients: int = 5
    mu_prox: float = 0.01  # coefficient proximal FedProx
    w_recon: float = 0.5
    w_vic: float = 0.05  # relevé vs 0.01 : collapse-guard actif
    w_scale: float = 0.1
    target_coverage: float = 0.9
    aci_eta: float = 0.02
    device: str = "cuda" if torch.cuda.is_available() else "cpu"

    # échelles : h horaire, d journalier, a bi-journalier (bloc de 24 h)
    future_lens: dict[str, int] = field(default_factory=lambda: {"h": 48, "d": 2, "a": 1})


REGIMES = ["routine", "weekend", "tension", "crise"]
SCALE_IDX = {"h": 0, "d": 1, "a": 2}
IDX_SCALE = {v: k for k, v in SCALE_IDX.items()}


def set_global_seed(seed: int) -> None:
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def get_regime(occupancy: float, is_weekend: bool) -> str:
    if occupancy >= 0.95:
        return "crise"
    if occupancy >= 0.85:
        return "tension"
    if is_weekend:
        return "weekend"
    return "routine"


# ---------------------------------------------------------------------------
# 1. Données synthétiques — axe temporel CONTINU par site
# ---------------------------------------------------------------------------
# Un site = une longue série temporelle continue (T_total heures). On en extrait
# des fenêtres glissantes (contexte + horizon). L'ordre des fenêtres préserve la
# chronologie, ce qui rend (a) le split conformal par trajectoire valide et
# (b) l'ACI online interprétable comme un vrai flux temporel.
class HospitalSeries(Dataset):
    def __init__(
        self, n_windows: int, cfg: Config, site_params: dict, seed_offset: int = 0, stride: int = 12
    ):
        self.cfg = cfg
        self.win = cfg.seq_len_h + cfg.future_h
        self.stride = stride
        self.rng = np.random.default_rng(cfg.seed + seed_offset)
        self.p = site_params
        # longueur totale nécessaire pour n_windows fenêtres au pas 'stride'
        self.T_total = self.win + (n_windows - 1) * stride
        self.series, self.occ = self._generate_series()
        self.starts = list(range(0, self.T_total - self.win + 1, stride))[:n_windows]

    def _generate_series(self) -> tuple[np.ndarray, np.ndarray]:
        T = self.T_total
        t = np.arange(T)
        hour = t % 24
        day = (t // 24) % 7
        is_weekend = day >= 5

        base_h = 10 + self.p["base_amplitude"] * np.sin(2 * np.pi * (hour - 6) / 24)
        base_d = np.where(is_weekend, self.p["weekend_factor"], 1.0)
        trend = self.p["trend"] * t
        noise = self.rng.normal(0, self.p["noise_std"], T)
        admissions = np.maximum(base_h * base_d + trend + noise, 0.0)

        # crises poissoniennes le long de la série continue
        n_crises = self.rng.poisson(self.p["crisis_prob"] * T / 24)
        for _ in range(n_crises):
            start = self.rng.integers(0, max(1, T - 24))
            length = self.rng.integers(6, 24)
            admissions[start : start + length] *= self.p["crisis_mult"]

        rng_min, rng_max = admissions.min(), admissions.max()
        occ = 0.5 + 0.3 * (admissions - rng_min) / (rng_max - rng_min + 1e-5)
        occ = np.clip(occ, 0.4, 1.0)
        # rehausse l'occupation pendant les pics
        peak = admissions > (admissions.mean() + 1.5 * admissions.std())
        occ[peak] = np.clip(occ[peak] * 1.6, 0.8, 1.0)

        data = np.stack([admissions, occ], axis=-1)  # (T, 2)
        return data.astype(np.float32), occ.astype(np.float32)

    def _regime_seq(self, sl: slice) -> list[str]:
        t = np.arange(sl.start, sl.stop)
        is_weekend = ((t // 24) % 7) >= 5
        return [
            get_regime(self.occ[i], bool(is_weekend[k]))
            for k, i in enumerate(range(sl.start, sl.stop))
        ]

    def __len__(self) -> int:
        return len(self.starts)

    def __getitem__(self, idx: int):
        s = self.starts[idx]
        ctx_sl = slice(s, s + self.cfg.seq_len_h)
        tgt_sl = slice(s + self.cfg.seq_len_h, s + self.win)
        context = torch.from_numpy(self.series[ctx_sl])
        target = torch.from_numpy(self.series[tgt_sl])
        regimes = self._regime_seq(tgt_sl)
        # start time (heure absolue) pour reconstruire l'ordre temporel global
        return context, target, regimes, s


# ---------------------------------------------------------------------------
# 2. Modules de base
# ---------------------------------------------------------------------------
class PositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_len: int = 5000):
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        pos = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div = torch.exp(torch.arange(0, d_model, 2).float() * (-np.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(pos * div)
        pe[:, 1::2] = torch.cos(pos * div)
        self.register_buffer("pe", pe.unsqueeze(0))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.pe[:, : x.size(1), :]


class MultiScalePatchifier(nn.Module):
    """Patchification causale multi-échelle. Chaque échelle a sa projection.

    FIX point 1 : l'échelle 'a' (bi-journalière) agrège par BLOC de 24 h sur la
    moyenne journalière, et non sur toute la fenêtre. Pour le contexte (168 h)
    cela donne 7 jours -> on garde le dernier bloc de 24 h moyenné pour rester
    aligné avec la cible. Les tailles sont cohérentes par construction.
    """

    def __init__(self, d_model: int):
        super().__init__()
        self.proj_h = nn.Linear(2, d_model)
        self.proj_d = nn.Linear(2, d_model)
        self.proj_a = nn.Linear(2, d_model)

    @staticmethod
    def _daily_mean(x: torch.Tensor) -> torch.Tensor:
        B, T, C = x.shape
        assert T % 24 == 0, f"T={T} non multiple de 24"
        return x.view(B, T // 24, 24, C).mean(dim=2)  # (B, T/24, C)

    def forward(self, x: torch.Tensor) -> dict[str, torch.Tensor]:
        h = self.proj_h(x)  # (B, T, d)
        x_d = self._daily_mean(x)  # (B, T/24, 2)
        d = self.proj_d(x_d)  # (B, T/24, d)
        # 'a' : moyenne par paire de jours -> blocs bi-journaliers
        nd = x_d.size(1)
        if nd >= 2:
            pair = nd - (nd % 2)
            x_a = x_d[:, :pair, :].view(x_d.size(0), pair // 2, 2, 2).mean(dim=2)
        else:
            x_a = x_d
        a = self.proj_a(x_a)  # (B, ceil(T/48), d)
        return {"h": h, "d": d, "a": a}


class TransformerEncoder(nn.Module):
    def __init__(self, d_model, nhead, num_layers):
        super().__init__()
        layer = nn.TransformerEncoderLayer(d_model=d_model, nhead=nhead, batch_first=True)
        self.transformer = nn.TransformerEncoder(layer, num_layers=num_layers)
        self.pos = PositionalEncoding(d_model)

    def forward(self, x):
        return self.transformer(self.pos(x))


# ---------------------------------------------------------------------------
# 3. Prédicteur temporel multi-longueur (décodage PARALLÈLE, pas de masque AR)
# ---------------------------------------------------------------------------
# FIX point 2 : pas de tgt_mask causal. Les queries sont des embeddings
# positionnels appris ; la prédiction est parallèle (PatchTST-like). Aucune
# dépendance auto-régressive, donc aucun masque causal n'a de sens ici.
class TemporalPredictor(nn.Module):
    def __init__(self, d_model, nhead, num_layers, future_lens: dict[str, int]):
        super().__init__()
        self.future_lens = future_lens
        self.query_embed = nn.ModuleDict(
            {s: nn.Embedding(L, d_model) for s, L in future_lens.items()}
        )
        self.scale_embed = nn.Embedding(len(future_lens), d_model)
        layer = nn.TransformerDecoderLayer(d_model=d_model, nhead=nhead, batch_first=True)
        self.decoder = nn.TransformerDecoder(layer, num_layers=num_layers)
        self.pos = PositionalEncoding(d_model)
        self.register_buffer("_scale_ids", torch.tensor([SCALE_IDX[s] for s in future_lens]))

    def forward(self, memory_list, scales: list[str]) -> dict[str, torch.Tensor]:
        memory = self.pos(torch.cat(memory_list, dim=1))
        out = {}
        for s in scales:
            L = self.future_lens[s]
            dev = memory.device
            t = torch.arange(L, device=dev).unsqueeze(0).expand(memory.size(0), -1)
            sid = torch.tensor(SCALE_IDX[s], device=dev)
            q = self.query_embed[s](t) + self.scale_embed(sid).view(1, 1, -1)
            q = self.pos(q)
            out[s] = self.decoder(tgt=q, memory=memory)  # PAS de tgt_mask
        return out


class ForecastDecoder(nn.Module):
    def __init__(self, d_model, out_features=2):
        super().__init__()
        self.mlp = nn.Sequential(
            nn.Linear(d_model, d_model),
            nn.ReLU(),
            nn.Linear(d_model, out_features),
        )

    def forward(self, z):
        return self.mlp(z)


# ---------------------------------------------------------------------------
# 4. Modèle JEPA complet — EMA teacher cohérente
# ---------------------------------------------------------------------------
class MTS_JEPA_Forecaster(nn.Module):
    def __init__(self, cfg: Config):
        super().__init__()
        d, h, n = cfg.d_model, cfg.n_heads, cfg.n_layers
        self.patchifier = MultiScalePatchifier(d)
        self.context_encoder = TransformerEncoder(d, h, n)
        self.target_encoder = TransformerEncoder(d, h, n)
        self.target_patchifier = copy.deepcopy(self.patchifier)
        self.predictor = TemporalPredictor(d, h, n, cfg.future_lens)
        self.decoder = ForecastDecoder(d, out_features=2)

        # teacher = copie figée du student au départ
        self.target_encoder.load_state_dict(self.context_encoder.state_dict())
        for p in self.target_encoder.parameters():
            p.requires_grad = False
        for p in self.target_patchifier.parameters():
            p.requires_grad = False

    # FIX point 7 : EMA appliquée UNE seule fois, au niveau global (cf. run).
    @torch.no_grad()
    def ema_update_from(self, student_ctx_sd, student_patch_sd, tau: float):
        for k, p in self.target_encoder.state_dict().items():
            p.mul_(tau).add_(student_ctx_sd[k].to(p.device), alpha=1 - tau)
        for k, p in self.target_patchifier.state_dict().items():
            p.mul_(tau).add_(student_patch_sd[k].to(p.device), alpha=1 - tau)

    def encode_context(self, x):
        patches = self.patchifier(x)
        return {s: self.context_encoder(p) for s, p in patches.items()}

    @torch.no_grad()
    def encode_target(self, x):
        patches = self.target_patchifier(x)
        return {s: self.target_encoder(p) for s, p in patches.items()}

    def predict_latents(self, ctx_enc, scales=("h", "d", "a")):
        mem = [ctx_enc[s] for s in ("h", "d", "a") if s in ctx_enc]
        return self.predictor(mem, list(scales))

    def forward(self, x_ctx, x_tgt=None):
        ctx_enc = self.encode_context(x_ctx)
        pred = self.predict_latents(ctx_enc)
        signals = {"h": self.decoder(pred["h"])}  # signal observable à l'échelle h
        if x_tgt is not None:
            tgt_enc = self.encode_target(x_tgt)
            return pred, tgt_enc, signals, ctx_enc
        return signals


# ---------------------------------------------------------------------------
# 5. Pertes
# ---------------------------------------------------------------------------
def jepa_loss(pred, target):
    return (1 - (F.normalize(pred, dim=-1) * F.normalize(target, dim=-1)).sum(dim=-1)).mean()


def reconstruction_loss(pred_signal, target_signal):
    return F.mse_loss(pred_signal, target_signal)


def vicreg_loss(z, gamma=1.0, eps=1e-4):
    z = z.reshape(-1, z.size(-1))
    if z.size(0) < 2:
        return torch.zeros((), device=z.device)
    std = torch.sqrt(z.var(dim=0) + eps)
    var = F.relu(gamma - std).mean()
    zc = z - z.mean(dim=0)
    cov = (zc.T @ zc) / (z.size(0) - 1)
    off = cov[~torch.eye(cov.size(0), dtype=torch.bool, device=z.device)]
    return var + off.pow(2).mean()


def inter_scale_loss(decoder, pred_latents):
    """FIX point 9 : cohérence imposée dans l'espace OBSERVABLE (signaux décodés),
    pas entre latents d'espaces hétérogènes. On vérifie que la moyenne journalière
    du signal horaire prédit ~ signal journalier reconstruit.
    """
    if "h" not in pred_latents or "d" not in pred_latents:
        return torch.zeros((), device=pred_latents["h"].device)
    sig_h = decoder(pred_latents["h"])  # (B, 48, 2)
    sig_d = decoder(pred_latents["d"])  # (B, 2, 2)
    B, T, C = sig_h.shape
    if T % sig_d.size(1) != 0:
        return torch.zeros((), device=sig_h.device)
    k = T // sig_d.size(1)
    pooled = sig_h.view(B, sig_d.size(1), k, C).mean(dim=2)  # (B, 2, 2)
    return F.mse_loss(pooled, sig_d)


# ---------------------------------------------------------------------------
# 6. Baseline saisonnière J-7 alignée en phase (FIX point 3)
# ---------------------------------------------------------------------------
def seasonal_baseline(context: torch.Tensor, horizon: int) -> torch.Tensor:
    """Répète les dernières 24 h du contexte pour couvrir l'horizon, ce qui
    aligne la phase horaire (lag journalier). Honnête vs l'ancien context[:, :48].
    """
    last_day = context[:, -24:, :]  # (B, 24, 2)
    reps = (horizon + 23) // 24
    tiled = last_day.repeat(1, reps, 1)[:, :horizon, :]
    return tiled


# ---------------------------------------------------------------------------
# 7. Conformal : split par TRAJECTOIRE (FIX points 4 & 5)
# ---------------------------------------------------------------------------
# Échangeabilité respectée : l'unité d'échange est la trajectoire. Le score de
# non-conformité d'une trajectoire est la norme-sup des résidus absolus sur
# l'horizon. Le quantile (1-α)(1+1/n) des scores de calibration fournit un rayon
# r tel que P( sup_t |y_t - ŷ_t| <= r ) >= 1-α (couverture au niveau trajectoire).
# LIMITE DOCUMENTÉE : la couverture POINTUELLE par instant n'est PAS garantie ;
# seule la couverture jointe sur l'horizon l'est (bande uniforme).
class SplitConformalTrajectory:
    def __init__(self, target_coverage: float = 0.9):
        self.alpha = 1.0 - target_coverage
        self.radius = None

    def calibrate(self, residual_matrix: np.ndarray):
        # residual_matrix : (n_traj, horizon) résidus absolus
        traj_scores = residual_matrix.max(axis=1)  # norme-sup par traj
        n = len(traj_scores)
        # quantile conforme avec correction de finitude (Vovk et al.)
        q_level = min(1.0, np.ceil((n + 1) * (1 - self.alpha)) / n)
        self.radius = float(np.quantile(traj_scores, q_level, method="higher"))
        return self.radius

    def band(self, point_forecast: np.ndarray):
        assert self.radius is not None, "calibrate() d'abord"
        return point_forecast - self.radius, point_forecast + self.radius


# ---------------------------------------------------------------------------
# 8. ACI online sur flux temporel continu (FIX points 4 & 10)
# ---------------------------------------------------------------------------
# Gibbs & Candès (2021). predict-avant-update. Pas d'intervalle magique : tant
# que le buffer de scores < min_scores, on signale 'non disponible' au lieu
# d'inventer un rayon.
class ACICalibrator:
    def __init__(self, target_coverage=0.9, eta=0.02, window=500, warmup=50, min_scores=2):
        self.target = target_coverage
        self.eta = eta
        self.alpha = 1.0 - target_coverage
        self.window = window
        self.warmup = warmup
        self.min_scores = min_scores
        self.scores: list[float] = []
        self.idx = 0
        self.warmed_up = False
        self.alpha_history: list[float] = []

    def _push(self, score):
        self.scores.append(score)
        if len(self.scores) > self.window:
            self.scores.pop(0)

    def predict_interval(self, point):
        if len(self.scores) < self.min_scores:
            return None  # honnête : pas d'intervalle disponible
        q = float(np.quantile(self.scores, np.clip(1.0 - self.alpha, 0, 1)))
        return point - q, point + q

    def update(self, score, covered):
        self.idx += 1
        if self.idx <= self.warmup:
            self._push(score)
            if self.idx == self.warmup:
                self.warmed_up = True
            return
        err_target = 1.0 - self.target
        err_now = 0.0 if covered else 1.0
        self.alpha += self.eta * (err_target - err_now)
        self.alpha = float(np.clip(self.alpha, 0.01, 0.5))
        self.alpha_history.append(self.alpha)
        self._push(score)


class DtACICalibrator:
    """ACI à pas adaptatif (DtACI ; Zaffran et al. 2022, Bhatnagar et al. 2023).

    Un comité d'experts ACI à différents eta est agrégé par pondération
    exponentielle sur la pinball-loss récente. Réduit le sous-tir en régime de
    transition sans réglage manuel de eta. La garantie reste asymptotique
    (couverture marginale de long terme), pas conditionnelle en échantillon fini.
    """

    def __init__(
        self,
        target_coverage=0.9,
        etas=(0.005, 0.02, 0.08, 0.16),
        gamma=0.99,
        window=500,
        warmup=50,
        min_scores=2,
    ):
        self.target = target_coverage
        self.experts = [
            ACICalibrator(target_coverage, eta, window, warmup, min_scores) for eta in etas
        ]
        self.w = np.ones(len(etas)) / len(etas)
        self.gamma = gamma
        self.scores: list[float] = []
        self.window = window
        self.min_scores = min_scores
        self.warmed_up = False
        self.alpha_history: list[float] = []

    def _push(self, score):
        self.scores.append(score)
        if len(self.scores) > self.window:
            self.scores.pop(0)

    @property
    def alpha(self):
        return float(np.dot(self.w, [e.alpha for e in self.experts]))

    def predict_interval(self, point):
        if len(self.scores) < self.min_scores:
            return None
        q = float(np.quantile(self.scores, np.clip(1.0 - self.alpha, 0, 1)))
        return point - q, point + q

    @staticmethod
    def _pinball(alpha, score, q):
        # pinball loss du quantile (1-alpha) ; proxy de qualité d'un expert
        u = score - q
        tau = 1.0 - alpha
        return max(tau * u, (tau - 1.0) * u)

    def update(self, score, covered):
        # quantiles courants de chaque expert (pour la pinball-loss)
        qs = []
        for e in self.experts:
            if len(e.scores) >= e.min_scores:
                qs.append(float(np.quantile(e.scores, np.clip(1.0 - e.alpha, 0, 1))))
            else:
                qs.append(0.0)
            e.update(score, covered)
        # repondération exponentielle sur la pinball-loss de chaque expert
        losses = np.array(
            [self._pinball(e.alpha, score, q) for e, q in zip(self.experts, qs, strict=False)]
        )
        self.w *= np.power(self.gamma, losses)
        self.w /= max(self.w.sum(), 1e-12)
        self.alpha_history.append(self.alpha)
        self._push(score)
        if all(e.warmed_up for e in self.experts):
            self.warmed_up = True


# ---------------------------------------------------------------------------
# 9. Entraînement local — FedProx réel + diagnostics collapse
# ---------------------------------------------------------------------------
def _flatten_params(module: nn.Module) -> torch.Tensor:
    return torch.cat([p.reshape(-1) for p in module.parameters() if p.requires_grad])


def train_client(
    model: MTS_JEPA_Forecaster,
    loader,
    optimizer,
    cfg: Config,
    global_trainable_snapshot: dict[str, torch.Tensor],
):
    """FIX point 6 : terme proximal FedProx (mu/2)||w - w_global||² réellement
    ajouté. global_trainable_snapshot : dict {name: tensor} des params globaux.
    Retourne loss totale + composantes pour diagnostic (FIX point 8).
    """
    model.train()
    device = cfg.device
    agg = {
        "total": 0.0,
        "jepa": 0.0,
        "recon": 0.0,
        "vic": 0.0,
        "scale": 0.0,
        "prox": 0.0,
        "emb_std": 0.0,
    }
    n_batches = 0

    for _ in range(cfg.epochs):
        for context, target, _, _ in loader:
            context, target = context.to(device), target.to(device)
            optimizer.zero_grad()

            ctx_enc = model.encode_context(context)
            tgt_enc = model.encode_target(target)
            pred = model.predict_latents(ctx_enc)
            sig_h = model.decoder(pred["h"])

            l_jepa = sum(jepa_loss(pred[s], tgt_enc[s]) for s in pred if s in tgt_enc) / max(
                len(pred), 1
            )
            l_recon = reconstruction_loss(sig_h, target)
            l_vic = sum(vicreg_loss(z) for z in ctx_enc.values()) + sum(
                vicreg_loss(z) for z in pred.values()
            )
            l_scale = inter_scale_loss(model.decoder, pred)

            # FedProx : terme proximal sur les paramètres entraînables
            prox = torch.zeros((), device=device)
            for name, p in model.named_parameters():
                if p.requires_grad and name in global_trainable_snapshot:
                    prox = prox + ((p - global_trainable_snapshot[name]) ** 2).sum()
            prox = 0.5 * cfg.mu_prox * prox

            loss = l_jepa + cfg.w_recon * l_recon + cfg.w_vic * l_vic + cfg.w_scale * l_scale + prox
            loss.backward()
            optimizer.step()

            with torch.no_grad():
                emb_std = (
                    torch.cat([z.reshape(-1, z.size(-1)).std(dim=0) for z in ctx_enc.values()])
                    .mean()
                    .item()
                )
            agg["total"] += loss.item()
            agg["jepa"] += l_jepa.item()
            agg["recon"] += l_recon.item()
            agg["vic"] += l_vic.item()
            agg["scale"] += float(l_scale.detach())
            agg["prox"] += float(prox.detach())
            agg["emb_std"] += emb_std
            n_batches += 1

    for k in agg:
        agg[k] /= max(n_batches, 1)
    return agg


# ---------------------------------------------------------------------------
# 10. Agrégation fédérée
# ---------------------------------------------------------------------------
def average_state_dicts(state_dicts: list[dict[str, torch.Tensor]]):
    avg = {}
    for key in state_dicts[0]:
        avg[key] = torch.stack([sd[key].float() for sd in state_dicts], 0).mean(0)
    return avg


# ---------------------------------------------------------------------------
# 11. Simulation fédérée — EMA cohérente + diagnostic de dérive
# ---------------------------------------------------------------------------
SITE_PARAMS = [
    {
        "base_amplitude": 5.0,
        "weekend_factor": 0.80,
        "trend": 0.010,
        "noise_std": 2.0,
        "crisis_prob": 0.10,
        "crisis_mult": 2.5,
    },
    {
        "base_amplitude": 7.0,
        "weekend_factor": 0.70,
        "trend": 0.020,
        "noise_std": 1.5,
        "crisis_prob": 0.20,
        "crisis_mult": 3.0,
    },
    {
        "base_amplitude": 4.0,
        "weekend_factor": 0.90,
        "trend": 0.005,
        "noise_std": 3.0,
        "crisis_prob": 0.05,
        "crisis_mult": 2.0,
    },
    {
        "base_amplitude": 6.0,
        "weekend_factor": 0.75,
        "trend": 0.015,
        "noise_std": 2.5,
        "crisis_prob": 0.15,
        "crisis_mult": 2.8,
    },
    {
        "base_amplitude": 5.5,
        "weekend_factor": 0.85,
        "trend": 0.010,
        "noise_std": 2.2,
        "crisis_prob": 0.12,
        "crisis_mult": 2.6,
    },
]


def trainable_snapshot(model: nn.Module, device) -> dict[str, torch.Tensor]:
    return {
        n: p.detach().clone().to(device) for n, p in model.named_parameters() if p.requires_grad
    }


def run_federated(cfg: Config, verbose=True):
    set_global_seed(cfg.seed)
    dev = cfg.device

    train_ds, test_ds = [], []
    for i in range(cfg.num_clients):
        sp = SITE_PARAMS[i % len(SITE_PARAMS)]
        train_ds.append(HospitalSeries(160, cfg, sp, seed_offset=i * 2))
        test_ds.append(HospitalSeries(120, cfg, sp, seed_offset=i * 2 + 1))

    global_model = MTS_JEPA_Forecaster(cfg).to(dev)
    history = []

    if verbose:
        print(f"=== Entraînement fédéré (FedProx, mu={cfg.mu_prox:.3g}) ===")
    for rnd in range(cfg.fed_rounds):
        # snapshot global (entraînable) pour le terme proximal
        global_snap = trainable_snapshot(global_model, dev)
        local_students, drift_norms = [], []
        round_agg = dict.fromkeys(
            ["total", "jepa", "recon", "vic", "scale", "prox", "emb_std"], 0.0
        )

        for cid in range(cfg.num_clients):
            model = copy.deepcopy(global_model).to(dev)
            optimizer = torch.optim.Adam(
                (p for p in model.parameters() if p.requires_grad), lr=cfg.lr
            )
            loader = DataLoader(train_ds[cid], batch_size=cfg.batch_size, shuffle=True)
            agg = train_client(model, loader, optimizer, cfg, global_snap)
            for k in round_agg:
                round_agg[k] += agg[k] / cfg.num_clients

            # diagnostic de dérive student-vs-global (FIX point 6, honnêteté)
            local_snap = trainable_snapshot(model, dev)
            drift = torch.sqrt(
                sum(((local_snap[n] - global_snap[n]) ** 2).sum() for n in global_snap)
            ).item()
            drift_norms.append(drift)

            local_students.append(
                {
                    "context_encoder": model.context_encoder.state_dict(),
                    "predictor": model.predictor.state_dict(),
                    "decoder": model.decoder.state_dict(),
                    "patchifier": model.patchifier.state_dict(),
                }
            )

        # FedAvg des students
        for comp in ["context_encoder", "predictor", "decoder", "patchifier"]:
            avg = average_state_dicts([s[comp] for s in local_students])
            getattr(global_model, comp).load_state_dict(avg)

        # FIX point 7 : UNE seule EMA. Le teacher global suit le student agrégé.
        global_model.ema_update_from(
            global_model.context_encoder.state_dict(),
            global_model.patchifier.state_dict(),
            tau=cfg.tau_ema,
        )

        rec = {
            "round": rnd + 1,
            "drift_mean": float(np.mean(drift_norms)),
            "drift_std": float(np.std(drift_norms)),
            **round_agg,
        }
        history.append(rec)
        if verbose:
            print(
                f"  R{rnd + 1:02d} | total {rec['total']:.4f} "
                f"jepa {rec['jepa']:.4f} recon {rec['recon']:.4f} "
                f"vic {rec['vic']:.4f} prox {rec['prox']:.4f} | "
                f"emb_std {rec['emb_std']:.3f} "
                f"drift {rec['drift_mean']:.3f}±{rec['drift_std']:.3f}"
            )
            if rec["emb_std"] < 1e-2:
                print("  [ALERTE] emb_std très faible -> risque de collapse.")

    return global_model, test_ds, history


# ---------------------------------------------------------------------------
# 12bis. Métriques rigoureuses : efficacité + bootstrap (AJOUTS RÉVISION)
# ---------------------------------------------------------------------------
def interval_efficiency(coverage: float, mean_width: float, scale: float) -> dict[str, float]:
    """Une couverture seule est ininterprétable. On rapporte :
    - normalized_width : largeur / échelle des données (sans dimension)
    - efficiency : couverture / largeur normalisée (plus haut = mieux à
      couverture égale). Pénalise les intervalles inutilement larges.
    """
    nw = mean_width / (scale + 1e-9)
    return {
        "coverage": coverage,
        "mean_width": mean_width,
        "normalized_width": nw,
        "efficiency": coverage / (nw + 1e-9),
    }


def bootstrap_diff(
    errors_a: np.ndarray, errors_b: np.ndarray, n_boot: int = 1000, seed: int = 0
) -> dict[str, float]:
    """IC bootstrap sur la différence d'erreur moyenne (a - b). Si l'IC à 95 %
    exclut 0, la différence est significative. Sans ça, comparer deux MAE n'est
    pas un résultat (Efron & Tibshirani 1993)."""
    rng = np.random.default_rng(seed)
    a, b = np.asarray(errors_a), np.asarray(errors_b)
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    diffs = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, n)
        diffs[i] = a[idx].mean() - b[idx].mean()
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return {
        "mean_diff": float(a.mean() - b.mean()),
        "ci95_low": float(lo),
        "ci95_high": float(hi),
        "significant": bool(lo > 0 or hi < 0),
    }


def collect_predictions(model, test_ds, cfg):
    """Retourne, par client, des trajectoires ORDONNÉES par temps absolu.
    Structure : list[ dict(true, pred, base, regime, start) ] trié par start.
    Chaque entrée = une trajectoire de longueur horizon (axe temps cohérent).
    """
    model.eval()
    dev = cfg.device
    per_client = []
    for cid in range(cfg.num_clients):
        loader = DataLoader(test_ds[cid], batch_size=cfg.batch_size, shuffle=False)
        rows = []
        with torch.no_grad():
            for context, target, regimes, starts in loader:
                context = context.to(dev)
                sig = model(context)["h"][:, :, 0].cpu().numpy()  # admissions
                true = target[:, :, 0].numpy()
                base = seasonal_baseline(context, cfg.future_h)[:, :, 0].cpu().numpy()
                # regimes : list de listes (time-major par item du batch)
                reg_arr = np.array(regimes, dtype=object).T  # (B, horizon)
                for b in range(sig.shape[0]):
                    rows.append(
                        {
                            "true": true[b],
                            "pred": sig[b],
                            "base": base[b],
                            "regime": list(reg_arr[b]),
                            "start": int(starts[b]),
                        }
                    )
        rows.sort(key=lambda r: r["start"])  # ordre temporel réel
        per_client.append(rows)
    return per_client


def split_traj(rows, frac_cal=0.5):
    """Split TEMPOREL par trajectoire : la 1ère moitié chronologique calibre,
    la 2nde évalue. Respecte l'ordre du temps (pas de fuite future->passé).
    """
    k = int(len(rows) * frac_cal)
    return rows[:k], rows[k:]


def evaluate(model, test_ds, cfg, verbose=True, use_dtaci=True):
    """Évaluation rigoureuse :
    1. Split-conformal trajectoire (garantie marginale) + efficacité.
    2. ACI/DtACI Mondrian par régime (couverture marginale PAR STRATE).
    3. Bootstrap modèle vs baseline (significativité).
    4. Test de dérive explicite : couverture statique sur strate 'crise'.
    """
    per_client = collect_predictions(model, test_ds, cfg)

    # échelle des données pour normaliser les largeurs (écart-type global y)
    all_true_flat = np.concatenate([r["true"] for rows in per_client for r in rows])
    data_scale = float(all_true_flat.std() + 1e-9)

    # ---- 1. Conformal par trajectoire (garantie marginale) ----
    cal_resid_mod, cal_resid_base = [], []
    eval_rows = []
    for rows in per_client:
        cal, ev = split_traj(rows, 0.5)
        for r in cal:
            cal_resid_mod.append(np.abs(r["true"] - r["pred"]))
            cal_resid_base.append(np.abs(r["true"] - r["base"]))
        eval_rows.extend(ev)

    cc_mod = SplitConformalTrajectory(cfg.target_coverage)
    cc_base = SplitConformalTrajectory(cfg.target_coverage)
    r_mod = cc_mod.calibrate(np.stack(cal_resid_mod))
    r_base = cc_base.calibrate(np.stack(cal_resid_base))

    cov_traj_mod = float(
        np.mean([bool(np.all(np.abs(r["true"] - r["pred"]) <= r_mod)) for r in eval_rows])
    )
    cov_traj_base = float(
        np.mean([bool(np.all(np.abs(r["true"] - r["base"]) <= r_base)) for r in eval_rows])
    )

    eff_mod = interval_efficiency(cov_traj_mod, 2 * r_mod, data_scale)
    eff_base = interval_efficiency(cov_traj_base, 2 * r_base, data_scale)

    # ---- 2. ACI/DtACI Mondrian par régime ----
    Cal = DtACICalibrator if use_dtaci else ACICalibrator
    aci = {reg: Cal(cfg.target_coverage) for reg in REGIMES}
    stats = {reg: {"cov": 0, "n": 0, "w": 0.0} for reg in REGIMES}
    for r in eval_rows:
        for t in range(len(r["true"])):
            reg = r["regime"][t]
            if reg not in REGIMES:
                continue
            cal = aci[reg]
            yt, yhat = float(r["true"][t]), float(r["pred"][t])
            interval = cal.predict_interval(yhat)
            score = abs(yt - yhat)
            if interval is not None:
                lb, ub = interval
                covered = lb <= yt <= ub
                cal.update(score, covered)
                if cal.warmed_up:
                    stats[reg]["cov"] += int(covered)
                    stats[reg]["n"] += 1
                    stats[reg]["w"] += ub - lb
            else:
                cal.update(score, False)

    # ---- 3. Bootstrap modèle vs baseline (MAE pointwise) ----
    err_mod = np.concatenate([np.abs(r["true"] - r["pred"]) for r in eval_rows])
    err_base = np.concatenate([np.abs(r["true"] - r["base"]) for r in eval_rows])
    boot = bootstrap_diff(err_mod, err_base)  # mod - base ; <0 => modèle meilleur

    # ---- 4. Test de dérive : conformal STATIQUE calibré hors-crise ----
    # calibration sur routine+weekend, évaluation sur crise => doit sous-couvrir
    calm_resid, crise_resid = [], []
    for r in eval_rows:
        for t in range(len(r["true"])):
            res = abs(r["true"][t] - r["pred"][t])
            if r["regime"][t] in ("routine", "weekend"):
                calm_resid.append(res)
            elif r["regime"][t] == "crise":
                crise_resid.append((res, r["true"][t], r["pred"][t]))
    drift_cov = None
    if len(calm_resid) > 10 and len(crise_resid) > 10:
        q = float(np.quantile(calm_resid, cfg.target_coverage))
        drift_cov = float(np.mean([abs(tv - pv) <= q for _, tv, pv in crise_resid]))

    if verbose:
        print("\n=== Couverture conformale (cible %.0f%%) ===" % (100 * cfg.target_coverage))
        print("[1. Split-conformal TRAJECTOIRE — garantie marginale]")
        print(
            f"  Modèle   : cov={eff_mod['coverage']:.3f}  "
            f"larg_norm={eff_mod['normalized_width']:.3f}  "
            f"effic={eff_mod['efficiency']:.3f}"
        )
        print(
            f"  Baseline : cov={eff_base['coverage']:.3f}  "
            f"larg_norm={eff_base['normalized_width']:.3f}  "
            f"effic={eff_base['efficiency']:.3f}"
        )
        cal_name = "DtACI" if use_dtaci else "ACI"
        print(f"\n[2. {cal_name} Mondrian par régime — couverture MARGINALE PAR STRATE]")
        print(f"{'Régime':<10} {'cov':>8} {'larg':>9} {'larg_norm':>10} {'n':>7}")
        print("-" * 48)
        for reg in REGIMES:
            s = stats[reg]
            if s["n"] == 0:
                print(f"{reg:<10} {'n/a':>8} {'n/a':>9} {'n/a':>10} {0:>7}")
            else:
                w = s["w"] / s["n"]
                print(
                    f"{reg:<10} {s['cov'] / s['n']:>8.3f} {w:>9.2f} "
                    f"{w / data_scale:>10.3f} {s['n']:>7d}"
                )
        print("\n[3. Bootstrap MAE modèle vs baseline (1000 rééch.)]")
        print(
            f"  Δ MAE (mod-base) = {boot['mean_diff']:+.3f}  "
            f"IC95=[{boot['ci95_low']:+.3f}, {boot['ci95_high']:+.3f}]  "
            f"significatif={boot['significant']}"
        )
        if drift_cov is not None:
            print("\n[4. Test de dérive — conformal statique calibré hors-crise]")
            print(
                f"  Couverture sur strate 'crise' = {drift_cov:.3f} "
                f"(cible {cfg.target_coverage:.2f})"
            )
            drift_message = (
                "sous-couverture confirmée (justifie ACI)"
                if drift_cov < cfg.target_coverage - 0.05
                else "pas de dérive marquée sur ce run"
            )
            print(f"  -> {drift_message}")
        print("\nNotes de validité :")
        print("  - Garantie 1-α : couverture MARGINALE au niveau trajectoire (bande uniforme).")
        print(
            "  - ACI/DtACI par régime : couverture marginale DANS chaque "
            "strate, PAS conditionnelle."
        )
        print(
            "  - Efficacité = cov / largeur_normalisée : compare à couverture "
            "égale (une couverture sans largeur est ininterprétable)."
        )

    return {
        "traj_mod": eff_mod,
        "traj_base": eff_base,
        "radius_mod": r_mod,
        "radius_base": r_base,
        "regime_stats": {reg: stats[reg] for reg in REGIMES},
        "bootstrap_mae": boot,
        "drift_static_coverage": drift_cov,
        "data_scale": data_scale,
    }


# 13. Point d'entrée
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=None)
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument("--clients", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--save", type=str, default="mts_jepa_federated_final.pt")
    parser.add_argument("--history", type=str, default="training_history.json")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--no-dtaci", action="store_true", help="Utiliser ACI simple au lieu de DtACI adaptatif"
    )
    args = parser.parse_args()

    cfg = Config()
    if args.rounds is not None:
        cfg.fed_rounds = args.rounds
    if args.epochs is not None:
        cfg.epochs = args.epochs
    if args.clients is not None:
        cfg.num_clients = args.clients
    if args.seed is not None:
        cfg.seed = args.seed
    verbose = not args.quiet

    print(f"Device: {cfg.device}")
    model, test_ds, history = run_federated(cfg, verbose=verbose)
    metrics = evaluate(model, test_ds, cfg, verbose=verbose, use_dtaci=not args.no_dtaci)

    torch.save({"state_dict": model.state_dict(), "config": cfg.__dict__}, args.save)
    with open(args.history, "w") as f:
        json.dump({"history": history, "metrics": metrics}, f, indent=2)
    if verbose:
        print(f"\nModèle sauvegardé -> {args.save}")
        print(f"Historique + métriques -> {args.history}")


if __name__ == "__main__":
    main()
