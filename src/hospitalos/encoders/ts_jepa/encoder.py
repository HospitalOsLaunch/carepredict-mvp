"""Pre-norm transformer encoder used by TS-JEPA."""

from __future__ import annotations

from typing import cast

import torch
from torch import Tensor, nn


class TransformerBlock(nn.Module):
    """One pre-norm transformer block with self-attention and MLP."""

    def __init__(self, dim: int, n_heads: int, mlp_ratio: int) -> None:
        super().__init__()
        self.norm1 = nn.LayerNorm(dim)
        self.attn = nn.MultiheadAttention(dim, n_heads, batch_first=True)
        self.norm2 = nn.LayerNorm(dim)
        hidden = dim * mlp_ratio
        self.mlp = nn.Sequential(
            nn.Linear(dim, hidden),
            nn.GELU(),
            nn.Linear(hidden, dim),
        )

    def forward(self, x: Tensor) -> Tensor:
        """Apply the transformer block."""
        attn_in = self.norm1(x)
        attn_out, _ = self.attn(attn_in, attn_in, attn_in, need_weights=False)
        x = x + attn_out
        return cast(Tensor, x + self.mlp(self.norm2(x)))


class TransformerEncoder(nn.Module):
    """Transformer encoder with learnable positional embeddings by patch index."""

    def __init__(
        self,
        emb_dim: int = 256,
        depth: int = 8,
        n_heads: int = 8,
        mlp_ratio: int = 4,
        max_patches: int = 512,
    ) -> None:
        super().__init__()
        self.emb_dim = emb_dim
        self.max_patches = max_patches
        self.pos_embed = nn.Embedding(max_patches, emb_dim)
        self.blocks = nn.ModuleList(
            [TransformerBlock(emb_dim, n_heads, mlp_ratio) for _ in range(depth)]
        )
        self.norm = nn.LayerNorm(emb_dim)

    def forward(self, tokens: Tensor, pos_idx: Tensor) -> Tensor:
        """Encode tokens with positions ``pos_idx`` and return ``(B, n, D)``."""
        if tokens.ndim != 3:
            raise ValueError("expected token shape (B, n, emb_dim)")
        if pos_idx.ndim != 1:
            raise ValueError("pos_idx must be a one-dimensional tensor")
        if tokens.shape[1] != pos_idx.numel():
            raise ValueError("token count must match positional index count")
        if int(pos_idx.max().item()) >= self.max_patches:
            raise ValueError("positional index exceeds max_patches")
        pos = self.pos_embed(pos_idx.to(device=tokens.device, dtype=torch.long))
        x = tokens + pos.unsqueeze(0)
        for block in self.blocks:
            x = block(x)
        return cast(Tensor, self.norm(x))
