"""Persistent model. Every row belongs to one group (tenant); queries are always group-scoped.

Patient data is pseudonymised by design: the product stores a referrer-side or
site-side pseudonymous reference, age band inputs and care needs, never names,
NIR or contact details.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from services.admissions_smr.db import Base, UTCDateTime


def utcnow() -> datetime:
    return datetime.now(UTC)


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    # Pre-registered baseline used by the pilot North Star and the success fee.
    baseline_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    baseline_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    baseline_frozen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    value_per_bed_day: Mapped[float] = mapped_column(Float, default=0.0)
    success_fee_rate: Mapped[float] = mapped_column(Float, default=0.0)
    scoring_weights_json: Mapped[str] = mapped_column(Text, default="{}")
    # Minutes of care per care level and per admission / discharge (hypotheses to calibrate).
    care_minutes_json: Mapped[str] = mapped_column(Text, default="{}")

    sites: Mapped[list[Site]] = relationship(back_populates="group")


class Site(Base):
    __tablename__ = "sites"
    __table_args__ = (UniqueConstraint("group_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    finess: Mapped[str | None] = mapped_column(String(9), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Comma-separated SPECIAL_NEEDS codes the site can take care of.
    capabilities: Mapped[str] = mapped_column(String(400), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    group: Mapped[Group] = relationship(back_populates="sites")
    pools: Mapped[list[BedPool]] = relationship(
        back_populates="site", cascade="all, delete-orphan", order_by="BedPool.mention"
    )


class BaselineSnapshot(Base):
    """Immutable, versioned inputs to the baseline and placebo windows. No patient identity."""

    __tablename__ = "baseline_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    start: Mapped[date] = mapped_column(Date)
    end: Mapped[date] = mapped_column(Date)
    digest: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)


class BedPool(Base):
    """Beds of one site for one SMR mention."""

    __tablename__ = "bed_pools"
    __table_args__ = (UniqueConstraint("site_id", "mention"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    mention: Mapped[str] = mapped_column(String(40))
    beds_installed: Mapped[int] = mapped_column(Integer)
    beds_open: Mapped[int] = mapped_column(Integer)
    isolation_rooms: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    site: Mapped[Site] = relationship(back_populates="pools")


class CapacityChange(Base):
    """Dated history of open beds, with the reason (staffing, works...)."""

    __tablename__ = "capacity_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    mention: Mapped[str] = mapped_column(String(40))
    effective_date: Mapped[date] = mapped_column(Date, index=True)
    beds_installed: Mapped[int] = mapped_column(Integer)
    beds_open: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(40))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(40))
    # When set, a coordination user only sees and acts on this site.
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Subject of the identity provider (Pro Santé Connect / SSO), linked on first login.
    oidc_subject: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Stay(Base):
    __tablename__ = "stays"
    __table_args__ = (UniqueConstraint("site_id", "patient_ref", "admission_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    mention: Mapped[str] = mapped_column(String(40))
    patient_ref: Mapped[str] = mapped_column(String(64))
    admission_date: Mapped[date] = mapped_column(Date, index=True)
    planned_discharge_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    discharge_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    care_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[int | None] = mapped_column(
        ForeignKey("admission_requests.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    plan_changes: Mapped[list[StayPlanChange]] = relationship(
        back_populates="stay", cascade="all, delete-orphan", order_by="StayPlanChange.recorded_at"
    )


class StayPlanChange(Base):
    """Every planned discharge date ever entered, to measure how plans slip."""

    __tablename__ = "stay_plan_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    stay_id: Mapped[int] = mapped_column(ForeignKey("stays.id"), index=True)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    recorded_on: Mapped[date] = mapped_column(Date)  # local calendar day of the entry
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="saisie")

    stay: Mapped[Stay] = relationship(back_populates="plan_changes")


class StaffPlan(Base):
    """Care hours available for a pool: a weekly pattern (weekday) or a dated override (day)."""

    __tablename__ = "staff_plans"
    __table_args__ = (UniqueConstraint("site_id", "mention", "weekday", "day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    mention: Mapped[str] = mapped_column(String(40))
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    day: Mapped[date | None] = mapped_column(Date, nullable=True)
    care_hours: Mapped[float] = mapped_column(Float)
    comment: Mapped[str | None] = mapped_column(String(300), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AdmissionRequest(Base):
    __tablename__ = "admission_requests"
    __table_args__ = (UniqueConstraint("group_id", "source", "external_ref"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    source: Mapped[str] = mapped_column(String(40))
    external_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    referrer_facility: Mapped[str] = mapped_column(String(200))
    referrer_unit: Mapped[str | None] = mapped_column(String(200), nullable=True)
    patient_ref: Mapped[str] = mapped_column(String(64))
    patient_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    patient_sex: Mapped[str | None] = mapped_column(String(1), nullable=True)
    mention_requested: Mapped[str] = mapped_column(String(40))
    clinical_category: Mapped[str | None] = mapped_column(String(200), nullable=True)
    care_level: Mapped[int] = mapped_column(Integer, default=2)
    isolation_required: Mapped[bool] = mapped_column(Boolean, default=False)
    special_needs: Mapped[str] = mapped_column(String(400), default="")
    desired_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="nouvelle", index=True)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id"), nullable=True)
    proposed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    first_response_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    refusal_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    loss_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    events: Mapped[list[RequestEvent]] = relationship(
        back_populates="request", cascade="all, delete-orphan", order_by="RequestEvent.at"
    )


class RequestEvent(Base):
    __tablename__ = "request_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("admission_requests.id"), index=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(40))
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    request: Mapped[AdmissionRequest] = relationship(back_populates="events")


class AuditEntry(Base):
    """Who did what, when. Required for any processing of health data."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    action: Mapped[str] = mapped_column(String(80))
    entity: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentState(Base):
    """Per-group settings and liveness of the computer-use agent."""

    __tablename__ = "agent_states"

    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), primary_key=True)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    policy_json: Mapped[str] = mapped_column(Text, default="{}")
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    engines_json: Mapped[str] = mapped_column(Text, default="[]")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AgentTask(Base):
    """Work for the agent: read the portal inbox, or write a reply back to the portal."""

    __tablename__ = "agent_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    request_id: Mapped[int | None] = mapped_column(
        ForeignKey("admission_requests.id"), nullable=True, index=True
    )
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    claimed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claimed_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decision_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    write_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    write_lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    available_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)
    budget_reserved_usd: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    engine_used: Mapped[str | None] = mapped_column(String(60), nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class AgentAttempt(Base):
    """One engine's try at a task, with its cost: the basis of routing and budget control."""

    __tablename__ = "agent_attempts"
    __table_args__ = (Index("uq_agent_attempt_report", "task_id", "report_key", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("agent_tasks.id"), index=True)
    report_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    engine: Mapped[str] = mapped_column(String(60))
    outcome: Mapped[str] = mapped_column(String(20))  # success | failure | refused
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    steps: Mapped[int] = mapped_column(Integer, default=0)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class AgentCalibration(Base):
    """Pointing test of a vision engine: an open model is only routed to after passing it."""

    __tablename__ = "agent_calibrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    engine: Mapped[str] = mapped_column(String(60))
    model: Mapped[str] = mapped_column(String(200))
    convention: Mapped[str | None] = mapped_column(String(40), nullable=True)
    hit_rate: Mapped[float] = mapped_column(Float)
    trials: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
