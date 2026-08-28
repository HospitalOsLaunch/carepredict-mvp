"""Architecture-agnostic interfaces for HFWM-R0 components."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, TypeAlias, runtime_checkable

from .serialization import JSONValue

TensorLike: TypeAlias = object


@dataclass(frozen=True, slots=True)
class ComponentIdentity:
    component_type: str
    implementation_id: str
    contract_version: str
    implementation_version: str
    artifact_hash: str | None = None


@dataclass(frozen=True, slots=True)
class TokenizerInput:
    events: Sequence[Mapping[str, JSONValue]]
    time_series: Mapping[str, TensorLike]
    entity_graph: Mapping[str, JSONValue]
    capacities: Mapping[str, TensorLike]
    resources: Mapping[str, TensorLike]
    context: Mapping[str, JSONValue]
    actions: Sequence[Mapping[str, JSONValue]]
    recording_process: Mapping[str, JSONValue]
    schema_versions: Mapping[str, str]
    as_of: str


@dataclass(frozen=True, slots=True)
class TokenBatch:
    values: TensorLike
    attention_mask: TensorLike
    entity_ids: Sequence[str]
    event_ids: Sequence[str]
    available_at: Sequence[str]
    provenance: Sequence[Mapping[str, JSONValue]]
    metadata: Mapping[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StateEncoderInput:
    observations: TokenBatch
    history: Sequence[TokenBatch]
    entity_graph: Mapping[str, JSONValue]
    recording_process: Mapping[str, JSONValue]
    context: Mapping[str, JSONValue]
    site_metadata: Mapping[str, JSONValue]


@dataclass(frozen=True, slots=True)
class BeliefState:
    value: TensorLike
    state_uncertainty: TensorLike
    entity_states: Mapping[str, TensorLike]
    hierarchical_states: Mapping[str, TensorLike]
    provenance: Sequence[Mapping[str, JSONValue]]
    as_of: str


@dataclass(frozen=True, slots=True)
class ActionObservation:
    action_type: str | None
    parameters: Mapping[str, JSONValue]
    dose: Mapping[str, JSONValue] | None
    timing: Mapping[str, JSONValue] | None
    scope: Mapping[str, JSONValue] | None
    execution_status: str
    deviation: Mapping[str, JSONValue] | None
    observed_at: str | None
    provenance: Sequence[Mapping[str, JSONValue]]


@dataclass(frozen=True, slots=True)
class ActionConditioningResult:
    conditioned_state: BeliefState
    observability_status: str
    in_support: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TransitionPrediction:
    next_state_distribution: TensorLike
    event_distribution: TensorLike
    uncertainty: TensorLike
    constraint_context: Mapping[str, JSONValue]
    horizon_steps: int


@dataclass(frozen=True, slots=True)
class TrajectoryRollout:
    state_trajectories: TensorLike
    event_trajectories: TensorLike
    uncertainty_by_horizon: TensorLike
    free_running: bool
    horizon_steps: int
    provenance: Sequence[Mapping[str, JSONValue]]


@dataclass(frozen=True, slots=True)
class TrajectoryScore:
    aggregate_score: float
    per_step_scores: Sequence[float]
    scoring_rule: str
    metadata: Mapping[str, JSONValue]


@dataclass(frozen=True, slots=True)
class ObservationPrediction:
    observation_distribution: TensorLike
    delay_distribution: TensorLike
    missingness_distribution: TensorLike
    silent_source_probability: TensorLike
    correction_distribution: TensorLike


@dataclass(frozen=True, slots=True)
class ConstraintViolation:
    constraint_id: str
    severity: str
    magnitude: float
    step: int | None
    entities: tuple[str, ...]
    evidence: Mapping[str, JSONValue]


@dataclass(frozen=True, slots=True)
class ConstraintReport:
    hard_violations: Sequence[ConstraintViolation]
    soft_violations: Sequence[ConstraintViolation]
    approximate_rule_findings: Sequence[ConstraintViolation]
    evaluated_constraint_versions: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class TaskPrediction:
    task_id: str
    distribution: TensorLike
    uncertainty: TensorLike
    horizons: tuple[int, ...]
    metadata: Mapping[str, JSONValue]


@dataclass(frozen=True, slots=True)
class JointPrediction:
    joint_distribution: TensorLike
    marginals: Mapping[str, TensorLike]
    dependency_metadata: Mapping[str, JSONValue]
    uncertainty: TensorLike


@dataclass(frozen=True, slots=True)
class SiteAdaptationRequest:
    site_id: str
    htl_mapping_version: str
    recording_process_version: str
    calibration_dataset_ref: str
    adaptation_dataset_ref: str
    local_data_budget: int
    compute_budget: Mapping[str, JSONValue]
    freeze_backbone: bool = True


@dataclass(frozen=True, slots=True)
class SiteAdaptationResult:
    adapter_artifact_ref: str
    adapter_hash: str
    calibration_ref: str
    backbone_hash: str
    local_data_used: int
    compute_used: Mapping[str, JSONValue]
    from_scratch_control_ref: str
    metadata: Mapping[str, JSONValue]


@runtime_checkable
class HospitalTokenizer(Protocol):
    identity: ComponentIdentity

    def encode(self, batch: TokenizerInput) -> TokenBatch: ...


@runtime_checkable
class StateEncoder(Protocol):
    identity: ComponentIdentity

    def infer_state(self, inputs: StateEncoderInput) -> BeliefState: ...

    def update_state(
        self, state: BeliefState, observations: TokenBatch, context: Mapping[str, JSONValue]
    ) -> BeliefState: ...


@runtime_checkable
class DynamicsCore(Protocol):
    identity: ComponentIdentity

    def infer_state(self, inputs: StateEncoderInput) -> BeliefState: ...

    def update_state(
        self, state: BeliefState, observations: TokenBatch, context: Mapping[str, JSONValue]
    ) -> BeliefState: ...

    def predict_next(
        self,
        state: BeliefState,
        actions: Sequence[ActionObservation],
        context: Mapping[str, JSONValue],
    ) -> TransitionPrediction: ...

    def rollout(
        self,
        state: BeliefState,
        actions: Sequence[ActionObservation],
        context: Mapping[str, JSONValue],
        horizon_steps: int,
    ) -> TrajectoryRollout: ...

    def sample_futures(
        self,
        state: BeliefState,
        actions: Sequence[ActionObservation],
        context: Mapping[str, JSONValue],
        horizon_steps: int,
        sample_count: int,
        seed: int,
    ) -> TrajectoryRollout: ...

    def score_observed_trajectory(
        self, rollout: TrajectoryRollout, observed: Sequence[Mapping[str, JSONValue]]
    ) -> TrajectoryScore: ...


@runtime_checkable
class ObservationModel(Protocol):
    identity: ComponentIdentity

    def predict_observations(
        self,
        state: BeliefState,
        recording_process: Mapping[str, JSONValue],
        site_metadata: Mapping[str, JSONValue],
    ) -> ObservationPrediction: ...

    def score_observations(
        self, prediction: ObservationPrediction, observed: TokenBatch
    ) -> TrajectoryScore: ...


@runtime_checkable
class ConstraintEngine(Protocol):
    identity: ComponentIdentity

    def evaluate(self, rollout: TrajectoryRollout) -> ConstraintReport: ...


@runtime_checkable
class ActionConditioner(Protocol):
    identity: ComponentIdentity

    def condition(
        self, state: BeliefState, actions: Sequence[ActionObservation]
    ) -> ActionConditioningResult: ...


@runtime_checkable
class TaskHead(Protocol):
    identity: ComponentIdentity

    def predict(self, state: BeliefState, horizons: tuple[int, ...]) -> TaskPrediction: ...


@runtime_checkable
class JointDecoder(Protocol):
    identity: ComponentIdentity

    def decode(self, rollout: TrajectoryRollout, task_ids: tuple[str, ...]) -> JointPrediction: ...


@runtime_checkable
class SiteAdapter(Protocol):
    identity: ComponentIdentity

    def adapt(self, request: SiteAdaptationRequest) -> SiteAdaptationResult: ...

    def calibrate(
        self, result: SiteAdaptationResult, calibration_dataset_ref: str
    ) -> SiteAdaptationResult: ...
