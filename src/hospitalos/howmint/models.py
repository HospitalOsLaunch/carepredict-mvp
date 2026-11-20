"""HOWM-INT-1 learned models (torch, CPU).

W (GraphWM): one family, two sizes (S: d = 128, M: d = 320), parameters SHARED across units and across resources.
  encoders   unit MLP(54 -> d -> d), resource MLP(10 -> d -> d), global MLP(8 -> d) added to every node
  state      explicit per-unit operational state s_t (9 variables) fed back at every step + latent h_t (GRU)
  messages   unit <- resources it uses (cleaning, transport, external downstream), resource <- mean of its units,
             unit <- units linked by observed transfers (row-normalised adjacency, both directions)
  transition GRUCell per node type driven ONLY by the exogenous schedule (interventions, calendar, clock)
  outputs    bed-state fractions (softmax over occupied/free/dirty: conserves beds), queue >= q12 >= q24 >= 0 by
             construction, other backlogs >= 0 (softplus), per-unit step wait cost (softplus), rupture logit
  no observation and no true future state enter a rollout (open loop)
Uncertainty: W predicts an expectation (conditional mean) of states/costs and a rupture probability per unit and
step; no calibrated distribution is claimed (3 seeds = stability diagnostic only).

DSet (direct reference of comparable capacity): DeepSets over units with the same inputs; predicts the cumulative
cost of a sequence directly (base + paired effect heads); no dynamics.
"""

from __future__ import annotations

import torch
from torch import nn

N_STATE = 9
COUNT_IDX = (3, 4, 5, 6, 7, 8)  # queue, q12, q24, ready_wait_tr, transfer_wait, aval_blocked
UNIT_IN, RES_IN, GLOB_IN = 54, 10, 8
U_SCHED, R_SCHED, CLOCK = 3, 3, 3


def mlp(i: int, h: int, o: int) -> nn.Sequential:
    return nn.Sequential(nn.Linear(i, h), nn.SiLU(), nn.Linear(h, o))


class GraphWM(nn.Module):
    def __init__(self, d: int = 128, use_messages: bool = True, use_history: bool = True):
        super().__init__()
        self.d, self.use_messages, self.use_history = d, use_messages, use_history
        self.unit_enc = mlp(UNIT_IN, d, d)
        self.res_enc = mlp(RES_IN, d, d)
        self.glob_enc = nn.Linear(GLOB_IN, d)
        self.s0 = nn.Linear(d, N_STATE)
        self.m_uu = nn.Linear(d, d)
        self.m_uu_rev = nn.Linear(d, d)
        self.m_ru = nn.Linear(d, d)
        self.m_ur = nn.Linear(d, d)
        self.cell_u = nn.GRUCell(U_SCHED + CLOCK + N_STATE + d, d)
        self.cell_r = nn.GRUCell(R_SCHED + CLOCK + d, d)
        self.head_beds = nn.Linear(d, 3)
        self.head_counts = nn.Linear(d, 3 + 3)  # queue, q12 gate, q24 gate, ready_wait_tr, transfer_wait, aval_blocked
        self.head_cost = nn.Linear(d, 1)
        self.head_rup = nn.Linear(d, 1)

    def init(self, unit: torch.Tensor, res: torch.Tensor, glob: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        if not self.use_history:
            unit = unit.clone()
            unit[..., UNIT_IN - 28:] = 0.0  # history summaries (14 deltas + 14 event counts) ablated
        g = self.glob_enc(glob)[:, None, :]
        return torch.tanh(self.unit_enc(unit) + g), torch.tanh(self.res_enc(res) + g)

    def readout(self, hu: torch.Tensor, beds: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        frac = torch.softmax(self.head_beds(hu), -1)  # occ, free, dirty fractions (sum to 1: bed conservation)
        c = self.head_counts(hu)
        queue = nn.functional.softplus(c[..., 0])
        q12 = queue * torch.sigmoid(c[..., 1])
        q24 = q12 * torch.sigmoid(c[..., 2])
        rest = nn.functional.softplus(c[..., 3:])
        state = torch.cat([frac, queue[..., None], q12[..., None], q24[..., None], rest], -1)
        cost = nn.functional.softplus(self.head_cost(hu))[..., 0]
        rup = self.head_rup(hu)[..., 0]
        return state, cost, rup

    def forward(self, unit, res, glob, ur_mask, uu, U, R, C, beds, steps: int | None = None, *, return_latents: bool = False):
        """unit [B,n,54] res [B,3,10] glob [B,8] ur_mask [B,n,3] uu [B,n,n] U [B,T,n,3] R [B,T,3,3] C [B,T,3].
        Returns states [B,T,n,9], costs [B,T,n] (scaled units), rupture logits [B,T,n]."""
        hu, hr = self.init(unit, res, glob)
        B, n, d = hu.shape
        T = U.shape[1] if steps is None else steps
        state, _c, _r = self.readout(hu, beds)
        a = uu / uu.sum(-1, keepdim=True).clamp(min=1.0)
        at = uu.transpose(1, 2) / uu.transpose(1, 2).sum(-1, keepdim=True).clamp(min=1.0)
        cnt = ur_mask.sum(1).clamp(min=1.0)  # [B,3]
        S, Cc, Rr = [], [], []
        latents = []
        for t in range(T):
            if self.use_messages:
                mu = self.m_uu(a @ hu) + self.m_uu_rev(at @ hu) + self.m_ru(ur_mask @ hr)
                mr = self.m_ur((ur_mask.transpose(1, 2) @ hu) / cnt[..., None])
            else:  # ablation: no exchange between units and resources (each node evolves on its own inputs)
                mu = torch.zeros_like(hu)
                mr = torch.zeros_like(hr)
            xu = torch.cat([U[:, t], C[:, t, None, :].expand(B, n, CLOCK), state, mu], -1)
            xr = torch.cat([R[:, t], C[:, t, None, :].expand(B, 3, CLOCK), mr], -1)
            hu = self.cell_u(xu.reshape(B * n, -1), hu.reshape(B * n, d)).reshape(B, n, d)
            hr = self.cell_r(xr.reshape(B * 3, -1), hr.reshape(B * 3, d)).reshape(B, 3, d)
            state, cost, rup = self.readout(hu, beds)
            if return_latents:
                latents.append(hu)
            S.append(state)
            Cc.append(cost)
            Rr.append(rup)
        outputs = torch.stack(S, 1), torch.stack(Cc, 1), torch.stack(Rr, 1)
        if return_latents:
            return (*outputs, torch.stack(latents, 1))
        return outputs


class DSet(nn.Module):
    """Direct sequence-cost reference (DeepSets), same inputs as W plus the flattened schedule summary."""

    def __init__(self, d: int = 160, desc_dim: int = 20):
        super().__init__()
        self.phi = mlp(UNIT_IN + U_SCHED, d, d)
        self.res = mlp(RES_IN + R_SCHED, d, d)
        self.rho_base = mlp(3 * d + GLOB_IN, d, 1)
        self.rho_eff = nn.Sequential(nn.Linear(3 * d + GLOB_IN + desc_dim, d), nn.SiLU(), nn.Linear(d, d), nn.SiLU(), nn.Linear(d, 1))

    def forward(self, unit, res, glob, U, R, desc):
        us = U.mean(1)  # [B,n,3] mean schedule coverage over the horizon
        rs = R.mean(1)  # [B,3,3]
        hu = self.phi(torch.cat([unit, us], -1))
        hr = self.res(torch.cat([res, rs], -1))
        z0 = torch.cat([hu.mean(1), hu.max(1).values, hr.mean(1), glob], -1)
        base = self.rho_base(torch.cat([self.phi(torch.cat([unit, torch.zeros_like(us)], -1)).mean(1),
                                        self.phi(torch.cat([unit, torch.zeros_like(us)], -1)).max(1).values,
                                        self.res(torch.cat([res, torch.zeros_like(rs)], -1)).mean(1), glob], -1))[..., 0]
        eff = self.rho_eff(torch.cat([z0, desc], -1))[..., 0]
        return base, eff


def n_params(m: nn.Module) -> int:
    return sum(p.numel() for p in m.parameters())
