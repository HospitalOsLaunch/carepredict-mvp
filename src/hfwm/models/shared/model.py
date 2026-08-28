"""Shared linear belief dynamics with a frozen-backbone bounded site adapter."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from hfwm.contracts.interfaces import ComponentIdentity
from hfwm.models.local.model import FloatArray, JointDynamicsConfig, LocalJointDynamicsModel


@dataclass(frozen=True, slots=True)
class SiteAdaptationSummary:
    """In-memory proof that adaptation stayed within its local data budget."""

    site_id: str
    local_examples_used: int
    local_data_budget: int
    backbone_hash_before: str
    backbone_hash_after: str
    adapter_hash: str


class SharedHFWMModel(LocalJointDynamicsModel):
    """Multi-site shared backbone with no site identity feature.

    The core uses exactly the representation and parameterization of the local
    from-scratch control. Pretraining pools sufficient rows across sites; adaptation
    updates only a bounded per-target bias and never mutates the backbone arrays.
    """

    MAX_LOCAL_DATA_BUDGET = 256

    def __init__(self, config: JointDynamicsConfig) -> None:
        super().__init__(config)
        self.identity = ComponentIdentity(
            component_type="DynamicsCore",
            implementation_id="shared_hfwm_multitask",
            contract_version="hfwm.dynamics-core.v1",
            implementation_version="hfwm-r0.1",
        )
        self._pretraining_site_count = 0
        self._adaptation: SiteAdaptationSummary | None = None

    @property
    def pretraining_site_count(self) -> int:
        """Number of separately supplied sites, not a model feature."""
        return self._pretraining_site_count

    @property
    def adaptation_summary(self) -> SiteAdaptationSummary | None:
        """Return the most recent bounded adaptation proof."""
        return self._adaptation

    def pretrain(
        self,
        *,
        trajectories_by_site: Mapping[str, FloatArray],
        observed_masks_by_site: Mapping[str, FloatArray] | None = None,
        recording_process_by_site: Mapping[str, FloatArray] | None = None,
    ) -> SharedHFWMModel:
        """Fit one shared backbone from in-memory point-in-time site arrays."""
        if len(trajectories_by_site) < 2 or any(not site for site in trajectories_by_site):
            raise ValueError("shared pretraining requires at least two named sites")
        if observed_masks_by_site is not None and not set(observed_masks_by_site) <= set(
            trajectories_by_site
        ):
            raise ValueError("observed mask contains an unknown site")
        if recording_process_by_site is not None and not set(recording_process_by_site) <= set(
            trajectories_by_site
        ):
            raise ValueError("recording process contains an unknown site")
        designs: list[FloatArray] = []
        targets: list[FloatArray] = []
        masks: list[FloatArray] = []
        for site_id in sorted(trajectories_by_site):
            design, target, target_mask = self._training_rows(
                trajectories_by_site[site_id],
                observed_mask=(
                    observed_masks_by_site.get(site_id)
                    if observed_masks_by_site is not None
                    else None
                ),
                recording_process=(
                    recording_process_by_site.get(site_id)
                    if recording_process_by_site is not None
                    else None
                ),
            )
            designs.append(design)
            targets.append(target)
            masks.append(target_mask)
        design = np.concatenate(designs)
        target = np.concatenate(targets)
        target_mask = np.concatenate(masks)
        design, target, target_mask = self._content_sorted_rows(design, target, target_mask)
        self._fit_rows(design, target, target_mask)
        self._local_bias.fill(0.0)
        self._site_id = None
        self._pretraining_site_count = len(trajectories_by_site)
        self._adaptation = None
        self.identity = ComponentIdentity(
            component_type="DynamicsCore",
            implementation_id="shared_hfwm_multitask",
            contract_version="hfwm.dynamics-core.v1",
            implementation_version="hfwm-r0.1",
            artifact_hash=self.backbone_hash(),
        )
        return self

    def adapt_site(
        self,
        *,
        site_id: str,
        trajectories: FloatArray,
        observed_mask: FloatArray | None = None,
        recording_process: FloatArray | None = None,
        local_data_budget: int,
    ) -> SiteAdaptationSummary:
        """Fit only a local residual bias from at most 256 transition examples."""
        if not site_id:
            raise ValueError("site_id must not be empty")
        if not 1 <= local_data_budget <= self.MAX_LOCAL_DATA_BUDGET:
            raise ValueError("local_data_budget must be in [1, 256]")
        coefficient, _variance = self._fitted_arrays()
        design, target, target_mask = self._training_rows(
            trajectories,
            observed_mask=observed_mask,
            recording_process=recording_process,
        )
        used = min(local_data_budget, design.shape[0])
        design = design[:used]
        target = target[:used]
        target_mask = target_mask[:used]
        before = self.backbone_hash()
        residual = target - design @ coefficient
        adapter = np.zeros(self.config.observation_dim, dtype=np.float64)
        for feature in range(self.config.observation_dim):
            selected = target_mask[:, feature] > 0.0
            if np.any(selected):
                adapter[feature] = float(np.sum(residual[selected, feature])) / (
                    int(np.sum(selected)) + self.config.ridge_alpha
                )
        self._local_bias = adapter
        self._site_id = site_id
        after = self.backbone_hash()
        if before != after:
            raise RuntimeError("backbone mutated during site adaptation")
        summary = SiteAdaptationSummary(
            site_id=site_id,
            local_examples_used=used,
            local_data_budget=local_data_budget,
            backbone_hash_before=before,
            backbone_hash_after=after,
            adapter_hash=self.adapter_hash(),
        )
        self._adaptation = summary
        return summary

    def adapter_hash(self) -> str:
        """Hash the in-memory local adapter independently from the backbone."""
        digest = hashlib.sha256()
        digest.update(str(self._local_bias.shape).encode("ascii"))
        digest.update(self._local_bias.astype("<f8", copy=False).tobytes(order="C"))
        return digest.hexdigest()

    @staticmethod
    def _content_sorted_rows(
        design: FloatArray, target: FloatArray, target_mask: FloatArray
    ) -> tuple[FloatArray, FloatArray, FloatArray]:
        """Make pretraining invariant to site labels and mapping insertion order."""
        combined = np.concatenate((design, target, target_mask), axis=1)
        keys = tuple(combined[:, index] for index in reversed(range(combined.shape[1])))
        order = np.lexsort(keys)
        return design[order], target[order], target_mask[order]
