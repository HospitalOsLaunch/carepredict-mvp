"""Target-token predictor for TS-JEPA."""

from __future__ import annotations

import torch
from torch import Tensor, nn

from hospitalos.encoders.ts_jepa.encoder import TransformerBlock


class Predictor(nn.Module):
    """Predict target embeddings from encoded context tokens and target positions."""

    def __init__(
        self,
        emb_dim: int = 256,
        pred_dim: int = 192,
        depth: int = 4,
        n_heads: int = 8,
        mlp_ratio: int = 4,
        max_patches: int = 512,
    ) -> None:
        super().__init__()
        self.pred_dim = pred_dim
        self.max_patches = max_patches
        self.ctx_proj = nn.Linear(emb_dim, pred_dim)
        self.mask_token = nn.Parameter(torch.zeros(pred_dim))
        self.pos_embed = nn.Embedding(max_patches, pred_dim)
        self.blocks = nn.ModuleList(
            [TransformerBlock(pred_dim, n_heads, mlp_ratio) for _ in range(depth)]
        )
        self.norm = nn.LayerNorm(pred_dim)
        self.out_proj = nn.Linear(pred_dim, emb_dim)

    def forward(self, ctx: Tensor, ctx_idx: Tensor, tgt_idx: Tensor) -> Tensor:
        """Return predicted target embeddings with shape ``(B, n_tgt, emb_dim)``."""
        if ctx.ndim != 3:
            raise ValueError("expected context shape (B, n_ctx, emb_dim)")
        if ctx.shape[1] != ctx_idx.numel():
            raise ValueError("context token count must match ctx_idx")
        if tgt_idx.ndim != 1:
            raise ValueError("tgt_idx must be one-dimensional")
        if int(tgt_idx.max().item()) >= self.max_patches:
            raise ValueError("target index exceeds max_patches")
        batch = ctx.shape[0]
        ctx_tokens = self.ctx_proj(ctx)
        tgt_pos = self.pos_embed(tgt_idx.to(device=ctx.device, dtype=torch.long))
        queries = self.mask_token.to(device=ctx.device, dtype=ctx.dtype).view(1, 1, -1)
        queries = queries.expand(batch, tgt_idx.numel(), self.pred_dim) + tgt_pos.unsqueeze(0)
        x = torch.cat([ctx_tokens, queries], dim=1)
        for block in self.blocks:
            x = block(x)
        x = self.norm(x)
        return self.out_proj(x[:, -tgt_idx.numel() :])
