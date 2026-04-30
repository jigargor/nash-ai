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
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    login: Mapped[str] = mapped_column(Text, nullable=False)
    token_enc: Mapped[bytes | None] = mapped_column(
        LargeBinary
    )  # Fernet-encrypted OAuth token (reserved)
    accepted_terms_version: Mapped[str | None] = mapped_column(Text)
    accepted_terms_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class UserProviderKey(Base):
    __tablename__ = "user_provider_keys"
    __table_args__ = (UniqueConstraint("user_id", "provider"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)  # "anthropic" | "openai" | "gemini"
    key_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)  # Fernet-encrypted
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class UserKeyAuditLog(Base):
    __tablename__ = "user_key_audit_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)  # "created" | "updated" | "deleted"
    performed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


class Installation(Base):
    __tablename__ = "installations"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    installation_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    account_login: Mapped[str] = mapped_column(Text, nullable=False)
    account_type: Mapped[str] = mapped_column(Text, nullable=False)
    installed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    suspended_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class InstallationUser(Base):
    __tablename__ = "installation_users"
    __table_args__ = (
        UniqueConstraint("installation_id", "user_id"),
        Index("installation_users_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    installation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("installations.installation_id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'member'"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


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
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("installation_id", "pr_number", "pr_head_sha"),
        Index("reviews_repo_pr", "repo_full_name", "pr_number"),
    )

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
    github_review_node_id: Mapped[str | None] = mapped_column(Text)
    tokens_used: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6))
    triggered_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


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
    stage_duration_ms: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


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
    detected_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    signals: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class LLMModelCatalogSnapshot(Base):
    __tablename__ = "llm_model_catalog_snapshots"
    __table_args__ = (
        Index("llm_model_catalog_snapshots_version_hash", "version_hash", unique=True),
        Index("llm_model_catalog_snapshots_promoted_at", "promoted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    version_hash: Mapped[str] = mapped_column(Text, nullable=False)
    catalog_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_hashes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    generated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
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
    circuit_open: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    failure_class: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    last_success_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"
    __table_args__ = (Index("benchmark_runs_started_at", "started_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    model_config_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    dataset_path: Mapped[str] = mapped_column(Text, nullable=False)
    triggered_by: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'running'"))
    totals_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ReviewContextSnapshot(Base):
    """Gzip-compressed JSON snapshot of everything fed to the LLM for a review.

    One row per review; captured fire-and-forget so failure never aborts a live review.
    Use evals/export_snapshot.py to export a row as an eval dataset directory.
    """

    __tablename__ = "review_context_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    review_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("reviews.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    installation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("installations.installation_id", ondelete="CASCADE"),
        nullable=False,
    )
    captured_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    r2_object_key: Mapped[str | None] = mapped_column(Text)
    schema_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"))
    snapshot_gz: Mapped[bytes | None] = mapped_column(LargeBinary)


class BenchmarkResult(Base):
    __tablename__ = "benchmark_results"
    __table_args__ = (Index("benchmark_results_run_id", "run_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("benchmark_runs.id"), nullable=False)
    case_id: Mapped[str] = mapped_column(Text, nullable=False)
    review_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("reviews.id"), nullable=True
    )
    expected_findings: Mapped[int] = mapped_column(Integer, nullable=False)
    predicted_findings: Mapped[int] = mapped_column(Integer, nullable=False)
    true_positives: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    false_positives: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    false_negatives: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6))
    cost_per_tp_usd: Mapped[float | None] = mapped_column(Numeric(10, 6))
    stage_timings_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


class ApiUsageEvent(Base):
    __tablename__ = "api_usage_events"
    __table_args__ = (
        Index("api_usage_events_installation_service_time", "installation_id", "service", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    installation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("installations.installation_id", ondelete="CASCADE"),
        nullable=False,
    )
    service: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


class FastPathThresholdConfig(Base):
    __tablename__ = "fast_path_threshold_configs"

    installation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("installations.installation_id", ondelete="CASCADE"),
        primary_key=True,
    )
    current_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("90")
    )
    minimum_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("60")
    )
    step_down: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("2"))
    target_disagreement_low: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("5")
    )
    target_disagreement_high: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("15")
    )
    max_false_accept_rate: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("5")
    )
    max_dismiss_rate: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("25")
    )
    min_samples: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


class FastPathThresholdHistory(Base):
    __tablename__ = "fast_path_threshold_history"
    __table_args__ = (
        Index("fast_path_threshold_history_installation_time", "installation_id", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    installation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("installations.installation_id", ondelete="CASCADE"),
        nullable=False,
    )
    previous_threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    new_threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    disagreement_rate: Mapped[float] = mapped_column(
        Numeric(10, 6), nullable=False, server_default=text("0")
    )
    dismiss_rate: Mapped[float] = mapped_column(
        Numeric(10, 6), nullable=False, server_default=text("0")
    )
    false_accept_rate: Mapped[float] = mapped_column(
        Numeric(10, 6), nullable=False, server_default=text("0")
    )
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    action: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'hold'"))
    recorded_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


class ProviderMetricConfig(Base):
    __tablename__ = "provider_metric_configs"

    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    redact_user_fields: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    allowed_dimensions: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


class ExternalEvaluation(Base):
    __tablename__ = "external_evaluations"
    __table_args__ = (
        Index("external_evaluations_installation_created", "installation_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    installation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("installations.installation_id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_by_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    repo_url: Mapped[str] = mapped_column(Text, nullable=False)
    owner: Mapped[str] = mapped_column(Text, nullable=False)
    repo: Mapped[str] = mapped_column(Text, nullable=False)
    target_ref: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    estimated_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    estimated_cost_usd: Mapped[float] = mapped_column(
        Numeric(10, 6), nullable=False, server_default=text("0")
    )
    token_budget_cap: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cost_budget_cap_usd: Mapped[float] = mapped_column(
        Numeric(10, 6), nullable=False, server_default=text("0")
    )
    ack_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    ack_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    summary: Mapped[str | None] = mapped_column(Text)
    findings_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False, server_default=text("0"))
    prepass_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


class ExternalEvaluationShard(Base):
    __tablename__ = "external_evaluation_shards"
    __table_args__ = (
        Index("external_evaluation_shards_eval_status", "external_evaluation_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    external_evaluation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("external_evaluations.id", ondelete="CASCADE"),
        nullable=False,
    )
    installation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shard_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    model_tier: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'economy'"))
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    findings_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False, server_default=text("0"))
    meta_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


class ExternalEvaluationFinding(Base):
    __tablename__ = "external_evaluation_findings"
    __table_args__ = (
        Index("external_evaluation_findings_eval_severity", "external_evaluation_id", "severity"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    external_evaluation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("external_evaluations.id", ondelete="CASCADE"),
        nullable=False,
    )
    installation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str | None] = mapped_column(Text)
    line_start: Mapped[int | None] = mapped_column(Integer)
    line_end: Mapped[int | None] = mapped_column(Integer)
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
