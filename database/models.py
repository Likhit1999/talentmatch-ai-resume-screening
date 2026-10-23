"""SQLAlchemy 2.0 ORM models for TalentMatch AI.

Defines schemas and relationships for Job Descriptions, Candidates,
Screening Runs, Matches, Shortlists, Reviews, Audit Logs, and Settings.
"""

from datetime import datetime
import json
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy 2.0 ORM models."""
    pass


class JobDescription(Base):
    """Job Description model representing job postings and requisitions."""

    __tablename__ = "job_descriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    department: Mapped[Optional[str]] = mapped_column(String(150), nullable=True, index=True)
    description_text: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    experience_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    experience_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    employment_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # Full-time, Contract, etc.
    qualifications: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    responsibilities: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    certifications: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recruiter_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), default="Open", nullable=False, index=True
    )  # Open, In Progress, On Hold, Closed, Draft (also legacy Active, Inactive)
    analysis_status: Mapped[str] = mapped_column(
        String(50), default="not_analyzed", nullable=False, index=True
    )  # not_analyzed, analyzed, needs_reanalysis
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Relationships
    versions: Mapped[List["JDVersion"]] = relationship(
        "JDVersion", back_populates="job_description", cascade="all, delete-orphan"
    )
    requirements: Mapped[List["JDRequirement"]] = relationship(
        "JDRequirement", back_populates="job_description", cascade="all, delete-orphan"
    )
    screening_runs: Mapped[List["ScreeningRun"]] = relationship(
        "ScreeningRun", back_populates="job_description"
    )
    candidate_matches: Mapped[List["CandidateMatch"]] = relationship(
        "CandidateMatch", back_populates="job_description"
    )
    shortlists: Mapped[List["Shortlist"]] = relationship(
        "Shortlist", back_populates="job_description"
    )

    def __repr__(self) -> str:
        return f"<JobDescription(id={self.id}, title='{self.title}', status='{self.status}')>"


class JDVersion(Base):
    """Historical version snapshot of a Job Description."""

    __tablename__ = "jd_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jd_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("job_descriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_data: Mapped[str] = mapped_column(Text, nullable=False)  # JSON representation
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    job_description: Mapped["JobDescription"] = relationship(
        "JobDescription", back_populates="versions"
    )
    screening_runs: Mapped[List["ScreeningRun"]] = relationship(
        "ScreeningRun", back_populates="jd_version"
    )

    __table_args__ = (
        UniqueConstraint("jd_id", "version_number", name="uq_jd_version"),
    )

    def get_snapshot(self) -> Dict[str, Any]:
        """Parse snapshot JSON data."""
        try:
            return json.loads(self.snapshot_data)
        except Exception:
            return {}

    def __repr__(self) -> str:
        return f"<JDVersion(id={self.id}, jd_id={self.jd_id}, v={self.version_number})>"


class JDRequirement(Base):
    """Atomic requirement extracted from a Job Description."""

    __tablename__ = "jd_requirements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jd_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("job_descriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requirement_name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # mandatory_skill, preferred_skill, experience, education, certification, domain, tool, responsibility, other
    importance: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # mandatory, preferred, informational
    original_evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    normalized_value: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    recruiter_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    job_description: Mapped["JobDescription"] = relationship(
        "JobDescription", back_populates="requirements"
    )
    match_evidences: Mapped[List["MatchEvidence"]] = relationship(
        "MatchEvidence", back_populates="requirement"
    )

    def __repr__(self) -> str:
        return f"<JDRequirement(id={self.id}, name='{self.requirement_name}', category='{self.category}')>"


class Candidate(Base):
    """Candidate profile parsed from uploaded resumes."""

    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    resume_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    skills_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    experience_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    education_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    certifications_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parsing_status: Mapped[str] = mapped_column(
        String(50), default="pending", nullable=False, index=True
    )  # pending, parsed, failed, warning
    parsing_warnings: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    job_category: Mapped[Optional[str]] = mapped_column(String(150), nullable=True, index=True)
    upload_batch_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    resumes: Mapped[List["ResumeDocument"]] = relationship(
        "ResumeDocument", back_populates="candidate", cascade="all, delete-orphan"
    )
    screening_runs: Mapped[List["ScreeningRun"]] = relationship(
        "ScreeningRun", back_populates="candidate"
    )
    matches: Mapped[List["CandidateMatch"]] = relationship(
        "CandidateMatch", back_populates="candidate"
    )
    shortlist_entries: Mapped[List["ShortlistCandidate"]] = relationship(
        "ShortlistCandidate", back_populates="candidate"
    )

    def get_skills(self) -> List[Any]:
        """Return parsed list of skills."""
        if not self.skills_json:
            return []
        try:
            return json.loads(self.skills_json)
        except Exception:
            return []

    def __repr__(self) -> str:
        return f"<Candidate(id={self.id}, name='{self.name}', email='{self.email}')>"


class ResumeDocument(Base):
    """Raw resume document storage and deduplication metadata."""

    __tablename__ = "resume_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # SHA-256
    file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    resume_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    file_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # pdf, docx, txt
    upload_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    # Relationships
    candidate: Mapped["Candidate"] = relationship("Candidate", back_populates="resumes")

    def __repr__(self) -> str:
        return f"<ResumeDocument(id={self.id}, filename='{self.original_filename}', hash='{self.file_hash[:8]}')>"


class ScreeningBatch(Base):
    """Batch screening orchestrator job container."""

    __tablename__ = "screening_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    jd_ids_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # List of JD IDs
    candidate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="pending", nullable=False, index=True
    )  # pending, processing, completed, failed
    matching_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    scoring_config_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Relationships
    runs: Mapped[List["ScreeningRun"]] = relationship(
        "ScreeningRun", back_populates="batch", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ScreeningBatch(id={self.id}, name='{self.name}', status='{self.status}')>"


class ScreeningRun(Base):
    """Execution instance evaluating a candidate against a JD."""

    __tablename__ = "screening_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("screening_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    jd_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("job_descriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    jd_version_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jd_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    candidate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(50), default="pending", nullable=False, index=True
    )  # pending, running, completed, failed
    matching_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    model_identifier: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    scoring_config_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    batch: Mapped["ScreeningBatch"] = relationship("ScreeningBatch", back_populates="runs")
    job_description: Mapped["JobDescription"] = relationship(
        "JobDescription", back_populates="screening_runs"
    )
    jd_version: Mapped[Optional["JDVersion"]] = relationship(
        "JDVersion", back_populates="screening_runs"
    )
    candidate: Mapped["Candidate"] = relationship("Candidate", back_populates="screening_runs")
    candidate_matches: Mapped[List["CandidateMatch"]] = relationship(
        "CandidateMatch", back_populates="screening_run"
    )

    def __repr__(self) -> str:
        return f"<ScreeningRun(id={self.id}, jd_id={self.jd_id}, candidate_id={self.candidate_id}, status='{self.status}')>"


class CandidateMatch(Base):
    """Evaluated match score, breakdown, and category for a candidate against a job."""

    __tablename__ = "candidate_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    screening_run_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("screening_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    candidate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    jd_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("job_descriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    match_score: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    match_category: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # strong_match, potential_match, needs_review, insufficient_evidence
    mandatory_met: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mandatory_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mandatory_missing_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    preferred_met: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    preferred_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    experience_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    qualification_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    domain_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    strengths_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    gaps_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    parsing_warnings: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    human_review_status: Mapped[str] = mapped_column(
        String(50), default="pending", nullable=False, index=True
    )  # pending, reviewed, shortlisted, on_hold, not_selected
    reviewer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewer_decision_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_screened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    screening_run: Mapped[Optional["ScreeningRun"]] = relationship(
        "ScreeningRun", back_populates="candidate_matches"
    )
    candidate: Mapped["Candidate"] = relationship("Candidate", back_populates="matches")
    job_description: Mapped["JobDescription"] = relationship(
        "JobDescription", back_populates="candidate_matches"
    )
    match_evidences: Mapped[List["MatchEvidence"]] = relationship(
        "MatchEvidence", back_populates="candidate_match", cascade="all, delete-orphan"
    )
    recruiter_reviews: Mapped[List["RecruiterReview"]] = relationship(
        "RecruiterReview", back_populates="candidate_match", cascade="all, delete-orphan"
    )
    shortlist_candidates: Mapped[List["ShortlistCandidate"]] = relationship(
        "ShortlistCandidate", back_populates="candidate_match"
    )

    __table_args__ = (
        Index("ix_matches_jd_score", "jd_id", "match_score"),
        Index("ix_matches_candidate_jd", "candidate_id", "jd_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<CandidateMatch(id={self.id}, candidate_id={self.candidate_id}, "
            f"jd_id={self.jd_id}, score={self.match_score}, category='{self.match_category}')>"
        )


class MatchEvidence(Base):
    """Specific evidence item supporting a match for a single JD requirement."""

    __tablename__ = "match_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_match_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidate_matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requirement_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jd_requirements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    match_status: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # matched, partial, not_found, uncertain
    evidence_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    needs_human_review: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )

    # Relationships
    candidate_match: Mapped["CandidateMatch"] = relationship(
        "CandidateMatch", back_populates="match_evidences"
    )
    requirement: Mapped["JDRequirement"] = relationship(
        "JDRequirement", back_populates="match_evidences"
    )

    def __repr__(self) -> str:
        return (
            f"<MatchEvidence(id={self.id}, match_id={self.candidate_match_id}, "
            f"req_id={self.requirement_id}, status='{self.match_status}')>"
        )


class Shortlist(Base):
    """Shortlist collection grouping candidate matches for a job requisition."""

    __tablename__ = "shortlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    jd_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("job_descriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), default="active", nullable=False, index=True
    )  # active, archived
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Relationships
    job_description: Mapped["JobDescription"] = relationship(
        "JobDescription", back_populates="shortlists"
    )
    candidates: Mapped[List["ShortlistCandidate"]] = relationship(
        "ShortlistCandidate", back_populates="shortlist", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Shortlist(id={self.id}, name='{self.name}', status='{self.status}')>"


class ShortlistCandidate(Base):
    """Association between candidate, shortlist, and match decision."""

    __tablename__ = "shortlist_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shortlist_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("shortlists.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_match_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("candidate_matches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(50), default="shortlisted", nullable=False, index=True
    )  # shortlisted, on_hold, not_selected, interview_scheduled
    recruiter_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    shortlist: Mapped["Shortlist"] = relationship("Shortlist", back_populates="candidates")
    candidate: Mapped["Candidate"] = relationship("Candidate", back_populates="shortlist_entries")
    candidate_match: Mapped[Optional["CandidateMatch"]] = relationship(
        "CandidateMatch", back_populates="shortlist_candidates"
    )

    __table_args__ = (
        UniqueConstraint("shortlist_id", "candidate_id", name="uq_shortlist_candidate"),
    )

    def __repr__(self) -> str:
        return (
            f"<ShortlistCandidate(shortlist_id={self.shortlist_id}, candidate_id={self.candidate_id}, "
            f"status='{self.status}')>"
        )


class RecruiterReview(Base):
    """Audit record of recruiter reviews and decision overrides."""

    __tablename__ = "recruiter_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_match_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidate_matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reviewer: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)  # approve, reject, comment, status_change
    previous_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    new_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    # Relationships
    candidate_match: Mapped["CandidateMatch"] = relationship(
        "CandidateMatch", back_populates="recruiter_reviews"
    )

    def __repr__(self) -> str:
        return f"<RecruiterReview(id={self.id}, reviewer='{self.reviewer}', action='{self.action}')>"


class AuditLog(Base):
    """System-wide audit trail for critical security and data operations."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    details_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    performed_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    performed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, entity='{self.entity_type}', action='{self.action}')>"


class ApplicationSetting(Base):
    """Dynamic key-value settings stored in the database."""

    __tablename__ = "application_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<ApplicationSetting(key='{self.key}', value='{self.value}')>"
