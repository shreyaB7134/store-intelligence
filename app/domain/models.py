from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    String, Boolean, Float, Integer, DateTime, Text, Index,
    ForeignKey, UniqueConstraint, func
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class EventRecord(Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    store_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    camera_id: Mapped[str] = mapped_column(String(64), nullable=False)
    visitor_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    zone_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    dwell_ms: Mapped[int] = mapped_column(Integer, default=0)
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    queue_depth: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sku_zone: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    session_seq: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_events_store_timestamp", "store_id", "timestamp"),
        Index("ix_events_store_type", "store_id", "event_type"),
        Index("ix_events_visitor_store", "visitor_id", "store_id"),
    )


class POSTransaction(Base):
    __tablename__ = "pos_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    order_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    store_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(String(64), nullable=False)
    brand_name: Mapped[str] = mapped_column(String(128), nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_pos_store_datetime", "store_id", "order_datetime"),
    )


class VisitorSession(Base):
    __tablename__ = "visitor_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    visitor_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    store_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entry_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False)
    converted: Mapped[bool] = mapped_column(Boolean, default=False)
    total_dwell_ms: Mapped[int] = mapped_column(Integer, default=0)
    visited_billing: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("visitor_id", "store_id", name="uq_visitor_store"),
        Index("ix_sessions_store_entry", "store_id", "entry_time"),
    )
