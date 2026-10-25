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
    request_id: Mapped[int | None] = mapped_column(
        ForeignKey("admission_requests.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
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
