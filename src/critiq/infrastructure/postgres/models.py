from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Installation(Base):
    __tablename__ = "installations"

    id: Mapped[int] = mapped_column(primary_key=True)
    github_installation_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    account_login: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    repositories: Mapped[list[Repository]] = relationship(back_populates="installation")


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(primary_key=True)
    installation_id: Mapped[int] = mapped_column(ForeignKey("installations.id"))
    github_repo_id: Mapped[int] = mapped_column(BigInteger)
    full_name: Mapped[str] = mapped_column(Text)
    default_branch: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    installation: Mapped[Installation] = relationship(back_populates="repositories")
    pull_requests: Mapped[list[PullRequest]] = relationship(back_populates="repository")
    policy: Mapped[ReviewPolicy | None] = relationship(
        back_populates="repository", uselist=False
    )
    org_setting: Mapped[OrgSetting | None] = relationship(
        back_populates="repository", uselist=False
    )


class PullRequest(Base):
    __tablename__ = "pull_requests"
    __table_args__ = (
        UniqueConstraint("repository_id", "github_pr_number", name="uq_repo_pr"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"))
    github_pr_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_login: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_branch: Mapped[str | None] = mapped_column(Text, nullable=True)
    head_branch: Mapped[str | None] = mapped_column(Text, nullable=True)
    head_sha: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    repository: Mapped[Repository] = relationship(back_populates="pull_requests")
    review_runs: Mapped[list[ReviewRun]] = relationship(back_populates="pull_request")


class ReviewRun(Base):
    __tablename__ = "review_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    pull_request_id: Mapped[int] = mapped_column(ForeignKey("pull_requests.id"))
    status: Mapped[str] = mapped_column(Text, default="pending")
    mode: Mapped[str] = mapped_column(Text, default="automatic")
    overall_score: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    pull_request: Mapped[PullRequest] = relationship(back_populates="review_runs")
    findings: Mapped[list[Finding]] = relationship(back_populates="review_run")
    patches: Mapped[list[AutoFixPatch]] = relationship(back_populates="review_run")


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(primary_key=True)
    review_run_id: Mapped[int] = mapped_column(ForeignKey("review_runs.id"))
    category: Mapped[str] = mapped_column(Enum("correctness", "security", "architecture",
                                                     "reliability", "performance", "testing",
                                                     name="finding_category"))
    file_path: Mapped[str] = mapped_column(Text)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    severity: Mapped[str] = mapped_column(
        Enum("critical", "high", "medium", "low", name="finding_severity")
    )
    confidence: Mapped[float] = mapped_column(Float)
    title: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text)
    recommendation: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, default="llm")
    posted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    review_run: Mapped[ReviewRun] = relationship(back_populates="findings")
    patches: Mapped[list[AutoFixPatch]] = relationship(back_populates="finding")


class ReviewPolicy(Base):
    __tablename__ = "review_policies"

    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id"), unique=True
    )
    severity_threshold: Mapped[str] = mapped_column(Text, default="medium")
    confidence_threshold: Mapped[float] = mapped_column(Float, default=0.85)
    categories_enabled: Mapped[dict] = mapped_column(JSONB, default=dict)
    mode: Mapped[str] = mapped_column(Text, default="automatic")
    model_routing: Mapped[dict] = mapped_column(JSONB, default=dict)
    fix: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    repository: Mapped[Repository] = relationship(back_populates="policy")


class FindingFeedback(Base):
    """A developer's reaction to a posted finding (feedback-learning loop)."""

    __tablename__ = "finding_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id"))
    signal: Mapped[str] = mapped_column(Text)  # accepted | rejected | resolved
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AutoFixPatch(Base):
    """A proposed code fix for a finding (V3 auto-fix)."""

    __tablename__ = "autofix_patches"
    __table_args__ = (
        UniqueConstraint("review_run_id", "file_path", name="uq_patch_run_file"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    review_run_id: Mapped[int] = mapped_column(ForeignKey("review_runs.id"))
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id"))
    file_path: Mapped[str] = mapped_column(Text)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    replacement_text: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    status: Mapped[str] = mapped_column(
        Enum("offered", "applied", "rejected", name="patch_status")
    )
    test_status: Mapped[str | None] = mapped_column(
        Enum("passed", "failed", "unverified", name="patch_test_status"), nullable=True
    )
    review_comment_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    review_run: Mapped[ReviewRun] = relationship(back_populates="patches")
    finding: Mapped[Finding] = relationship(back_populates="patches")


class OrgSetting(Base):
    """Per-repository auto-fix behavior (V3 auto-fix)."""

    __tablename__ = "org_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id"), unique=True
    )
    auto_push_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    repository: Mapped[Repository] = relationship(back_populates="org_setting")
