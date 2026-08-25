"""Lightning module for TS-JEPA pretraining."""

from __future__ import annotations

import copy
import math
from typing import Any

import lightning as L
import torch
import torch.nn.functional as F
from torch import Tensor
from torch.optim.adamw import AdamW
from torch.optim.lr_scheduler import LambdaLR

from hospitalos.encoders.ts_jepa.config import JEPAConfig
from hospitalos.encoders.ts_jepa.encoder import TransformerEncoder
from hospitalos.encoders.ts_jepa.masking import block_mask
from hospitalos.encoders.ts_jepa.patcher import Patchifier
from hospitalos.encoders.ts_jepa.predictor import Predictor
from hospitalos.encoders.ts_jepa.probes import embedding_std, mean_offdiag_corr


class JEPALightningModule(L.LightningModule):
    """Train a time-series JEPA encoder with an EMA target encoder."""

    def __init__(self, cfg: JEPAConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self.patcher = Patchifier(cfg.in_channels, cfg.patch_len, cfg.emb_dim)
        self.context_encoder = TransformerEncoder(
            emb_dim=cfg.emb_dim,
            depth=cfg.ctx_layers,
            n_heads=cfg.n_heads,
            mlp_ratio=cfg.mlp_ratio,
        )
        self.target_encoder = copy.deepcopy(self.context_encoder)
        self.target_encoder.requires_grad_(False)
        self.target_encoder.eval()
        self.predictor = Predictor(
            emb_dim=cfg.emb_dim,
            pred_dim=cfg.pred_dim,
            depth=cfg.pred_layers,
            n_heads=cfg.n_heads,
            mlp_ratio=cfg.mlp_ratio,
        )

    def training_step(self, batch: dict[str, Tensor] | Tensor, batch_idx: int) -> Tensor:
        """Run one JEPA reconstruction step over masked target patch embeddings."""
        del batch_idx
        series = self._extract_series(batch)
        tokens = self.patcher(series.float())
        batch_size, n_patches, _emb = tokens.shape
        del batch_size

        generator = torch.Generator(device="cpu")
        generator.manual_seed(int(self.global_step))
        ctx_idx_cpu, tgt_idx_cpu = block_mask(
            n_patches=n_patches,
            mask_ratio=self.cfg.mask_ratio,
            n_target_blocks=self.cfg.n_target_blocks,
            generator=generator,
        )
        ctx_idx = ctx_idx_cpu.to(device=tokens.device, dtype=torch.long)
        tgt_idx = tgt_idx_cpu.to(device=tokens.device, dtype=torch.long)
        all_idx = torch.arange(n_patches, device=tokens.device, dtype=torch.long)

        ctx = self.context_encoder(tokens[:, ctx_idx], ctx_idx)
        with torch.no_grad():
            full_tgt = self.target_encoder(tokens, all_idx)
            tgt = full_tgt[:, tgt_idx]
        pred = self.predictor(ctx, ctx_idx, tgt_idx)
        loss = F.smooth_l1_loss(pred, tgt)
        self.log("jepa/loss", loss, prog_bar=True, on_step=True, on_epoch=True)

        if (
            self.cfg.probe_every_n_steps > 0
            and int(self.global_step) % self.cfg.probe_every_n_steps == 0
        ):
            self.log("probe/emb_std", embedding_std(tgt.detach()), on_step=True, on_epoch=False)
            self.log(
                "probe/offdiag_corr",
                mean_offdiag_corr(tgt.detach()),
                on_step=True,
                on_epoch=False,
            )
        return loss

    def validation_step(self, batch: dict[str, Tensor] | Tensor, batch_idx: int) -> Tensor:
        """Run one JEPA validation reconstruction step without updating EMA state."""
        series = self._extract_series(batch)
        tokens = self.patcher(series.float())
        _batch_size, n_patches, _emb = tokens.shape

        generator = torch.Generator(device="cpu")
        generator.manual_seed(int(self.global_step) + int(batch_idx))
        ctx_idx_cpu, tgt_idx_cpu = block_mask(
            n_patches=n_patches,
            mask_ratio=self.cfg.mask_ratio,
            n_target_blocks=self.cfg.n_target_blocks,
            generator=generator,
        )
        ctx_idx = ctx_idx_cpu.to(device=tokens.device, dtype=torch.long)
        tgt_idx = tgt_idx_cpu.to(device=tokens.device, dtype=torch.long)
        all_idx = torch.arange(n_patches, device=tokens.device, dtype=torch.long)

        ctx = self.context_encoder(tokens[:, ctx_idx], ctx_idx)
        with torch.no_grad():
            full_tgt = self.target_encoder(tokens, all_idx)
            tgt = full_tgt[:, tgt_idx]
        pred = self.predictor(ctx, ctx_idx, tgt_idx)
        loss = F.smooth_l1_loss(pred, tgt)
        self.log("jepa/val_loss", loss, prog_bar=True, on_step=False, on_epoch=True)
        return loss

    def on_train_batch_end(self, outputs: Any, batch: Any, batch_idx: int) -> None:
        """Update the target encoder with a cosine-scheduled EMA."""
        del outputs, batch, batch_idx
        self.update_target_encoder()

    def ema_momentum(self) -> float:
        """Return the current EMA momentum."""
        step = min(int(self.global_step), self.cfg.max_steps)
        cosine = (math.cos(math.pi * step / self.cfg.max_steps) + 1.0) / 2.0
        return self.cfg.ema_end - (self.cfg.ema_end - self.cfg.ema_start) * cosine

    @torch.no_grad()
    def update_target_encoder(self) -> None:
        """Apply one EMA update from context encoder to target encoder."""
        momentum = self.ema_momentum()
        for target_param, context_param in zip(
            self.target_encoder.parameters(),
            self.context_encoder.parameters(),
            strict=True,
        ):
            target_param.mul_(momentum).add_(context_param.detach(), alpha=1.0 - momentum)

    def configure_optimizers(self) -> Any:
        """Configure AdamW and warmup-cosine learning-rate scheduling."""
        params = list(self.patcher.parameters())
        params += list(self.context_encoder.parameters())
        params += list(self.predictor.parameters())
        optimizer = AdamW(params, lr=self.cfg.lr, weight_decay=self.cfg.wd)
        warmup_steps = max(int(self.cfg.warmup_frac * self.cfg.max_steps), 1)

        def lr_lambda(step: int) -> float:
            if step < warmup_steps:
                return float(step + 1) / float(warmup_steps)
            progress = min(
                max((step - warmup_steps) / max(self.cfg.max_steps - warmup_steps, 1), 0.0),
                1.0,
            )
            return 0.5 * (1.0 + math.cos(math.pi * progress))

        scheduler = LambdaLR(optimizer, lr_lambda=lr_lambda)
        return {
            "optimizer": optimizer,
            "lr_scheduler": {
                "scheduler": scheduler,
                "interval": "step",
            },
        }

    @staticmethod
    def _extract_series(batch: dict[str, Tensor] | Tensor) -> Tensor:
        """Extract a ``series`` tensor from a Lightning batch."""
        if isinstance(batch, Tensor):
            return batch
        if "series" not in batch:
            raise KeyError("batch must contain a 'series' tensor")
        return batch["series"]
