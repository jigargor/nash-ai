from datetime import datetime
from typing import Any

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    Boolean,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    login: Mapped[str] = mapped_column(Text, nullable=False)
    token_enc: Mapped[bytes | None] = mapped_column(LargeBinary)  # Fernet-encrypted OAuth token
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class Installation(Base):
    __tablename__ = "installations"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    installation_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    account_login: Mapped[str] = mapped_column(Text, nullable=False)
    account_type: Mapped[str] = mapped_column(Text, nullable=False)
    installed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    suspended_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class RepoConfig(Base):
    __tablename__ = "repo_configs"
    __table_args__ = (UniqueConstraint("installation_id", "repo_full_name"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    installation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("installations.installation_id"),
        nullable=False,
    )
    repo_full_name: Mapped[str] = mapped_column(Text, nullable=False)
    config_yaml: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ai_generated_yaml: Mapped[str | None] = mapped_column(Text)
    ai_generated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (Index("reviews_repo_pr", "repo_full_name", "pr_number"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    installation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("installations.installation_id"),
        nullable=False,
    )
    repo_full_name: Mapped[str] = mapped_column(Text, nullable=False)
    pr_number: Mapped[int] = mapped_column(Integer, nullable=False)
    pr_head_sha: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default="queued")
    model_provider: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        insert_default="anthropic",
    )
    model: Mapped[str] = mapped_column(Text, nullable=False)
    findings: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    debug_artifacts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    tokens_used: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6))
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class ReviewModelAudit(Base):
    __tablename__ = "review_model_audits"
    __table_args__ = (
        Index("review_model_audits_review_stage", "review_id", "stage"),
        Index("review_model_audits_provider_model", "provider", "model"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    review_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("reviews.id"), nullable=False)
    installation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    findings_count: Mapped[int | None] = mapped_column(Integer)
    accepted_findings_count: Mapped[int | None] = mapped_column(Integer)
    conflict_score: Mapped[int | None] = mapped_column(Integer)
    decision: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class FindingOutcome(Base):
    __tablename__ = "finding_outcomes"
    __table_args__ = (
        UniqueConstraint("review_id", "finding_index"),
        Index("finding_outcomes_review", "review_id"),
        Index("finding_outcomes_outcome", "outcome"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    review_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("reviews.id"), nullable=False)
    finding_index: Mapped[int] = mapped_column(Integer, nullable=False)
    github_comment_id: Mapped[int | None] = mapped_column(BigInteger)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    outcome_confidence: Mapped[str] = mapped_column(Text, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    signals: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))


class LLMModelCatalogSnapshot(Base):
    __tablename__ = "llm_model_catalog_snapshots"
    __table_args__ = (
        Index("llm_model_catalog_snapshots_version_hash", "version_hash", unique=True),
        Index("llm_model_catalog_snapshots_promoted_at", "promoted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    version_hash: Mapped[str] = mapped_column(Text, nullable=False)
    catalog_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_hashes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    generated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    promoted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class LLMModelHealth(Base):
    __tablename__ = "llm_model_health"
    __table_args__ = (
        UniqueConstraint("provider", "model"),
        Index("llm_model_health_provider_status", "provider", "provider_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    provider_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    circuit_open: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    failure_class: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    last_success_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
