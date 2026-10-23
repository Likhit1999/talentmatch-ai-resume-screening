"""Repository access layer for TalentMatch AI database operations.

Encapsulates CRUD queries, filtering, search, pagination, and relational
operations using SQLAlchemy 2.0 select constructs.
"""

from datetime import datetime
import json
import logging
from typing import Any, List, Optional, Sequence, Type, TypeVar

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from database.models import (
    ApplicationSetting,
    AuditLog,
    Base,
    Candidate,
    CandidateMatch,
    JDRequirement,
    JDVersion,
    JobDescription,
    MatchEvidence,
    RecruiterReview,
    ResumeDocument,
    ScreeningBatch,
    ScreeningRun,
    Shortlist,
    ShortlistCandidate,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Base)


class BaseRepository:
    """Generic base repository providing CRUD utilities."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, model: Type[T], entity_id: Any) -> Optional[T]:
        """Fetch a single record by primary key."""
        return self.session.get(model, entity_id)

    def get_all(
        self,
        model: Type[T],
        filters: Optional[Sequence[Any]] = None,
        offset: int = 0,
        limit: Optional[int] = None,
        order_by: Optional[Any] = None,
    ) -> List[T]:
        """Retrieve records with optional filtering, ordering, and pagination."""
        stmt = select(model)
        if filters:
            for clause in filters:
                stmt = stmt.where(clause)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        if offset > 0:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt).all())

    def create(self, instance: T) -> T:
        """Add and flush a new instance."""
        self.session.add(instance)
        self.session.flush()
        return instance

    def update(self, instance: T) -> T:
        """Flush modifications on a tracked instance."""
        self.session.flush()
        return instance

    def delete(self, instance: T) -> None:
        """Delete an instance from the session."""
        self.session.delete(instance)
        self.session.flush()

    def count(self, model: Type[T], filters: Optional[Sequence[Any]] = None) -> int:
        """Count rows matching given criteria."""
        stmt = select(func.count()).select_from(model)
        if filters:
            for clause in filters:
                stmt = stmt.where(clause)
        count_val = self.session.scalar(stmt)
        return count_val or 0

    def exists(self, model: Type[T], filters: Sequence[Any]) -> bool:
        """Determine if any record satisfies the criteria."""
        return self.count(model, filters) > 0


class JDRepository(BaseRepository):
    """Repository handling Job Description domain operations."""

    def get_by_id(self, jd_id: int) -> Optional[JobDescription]:  # type: ignore[override]
        """Get JobDescription with loaded requirements."""
        stmt = (
            select(JobDescription)
            .where(JobDescription.id == jd_id)
            .options(joinedload(JobDescription.requirements))
        )
        return self.session.scalars(stmt).unique().first()

    def search(
        self,
        query: Optional[str] = None,
        department: Optional[str] = None,
        status: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> List[JobDescription]:
        """Search job descriptions with text search and field filters."""
        stmt = select(JobDescription)
        clauses = []

        if status:
            clauses.append(JobDescription.status == status)
        if department:
            clauses.append(JobDescription.department.ilike(f"%{department}%"))
        if query:
            q_pattern = f"%{query}%"
            clauses.append(
                or_(
                    JobDescription.title.ilike(q_pattern),
                    JobDescription.description_text.ilike(q_pattern),
                    JobDescription.responsibilities.ilike(q_pattern),
                    JobDescription.qualifications.ilike(q_pattern),
                )
            )

        for clause in clauses:
            stmt = stmt.where(clause)

        stmt = stmt.order_by(JobDescription.created_at.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(stmt).all())

    def get_active(self) -> List[JobDescription]:
        """Retrieve all currently active job postings."""
        return self.get_all(JobDescription, filters=[JobDescription.status == "Active"])

    def create_version_snapshot(self, jd: JobDescription) -> JDVersion:
        """Create a versioned historical snapshot for a JD."""
        current_version_count = self.count(JDVersion, [JDVersion.jd_id == jd.id])
        next_version = current_version_count + 1

        snapshot_dict = {
            "title": jd.title,
            "department": jd.department,
            "description_text": jd.description_text,
            "location": jd.location,
            "experience_min": jd.experience_min,
            "experience_max": jd.experience_max,
            "employment_type": jd.employment_type,
            "qualifications": jd.qualifications,
            "responsibilities": jd.responsibilities,
            "certifications": jd.certifications,
            "recruiter_notes": jd.recruiter_notes,
            "requirements": [
                {
                    "name": req.requirement_name,
                    "category": req.category,
                    "importance": req.importance,
                    "weight": req.weight,
                    "is_enabled": req.is_enabled,
                }
                for req in jd.requirements
            ],
        }

        version = JDVersion(
            jd_id=jd.id,
            version_number=next_version,
            snapshot_data=json.dumps(snapshot_dict),
        )
        self.create(version)
        return version

    def get_requirements(self, jd_id: int, enabled_only: bool = False) -> List[JDRequirement]:
        """Fetch requirements linked to a job description."""
        filters = [JDRequirement.jd_id == jd_id]
        if enabled_only:
            filters.append(JDRequirement.is_enabled.is_(True))
        return self.get_all(JDRequirement, filters=filters, order_by=JDRequirement.id.asc())


class CandidateRepository(BaseRepository):
    """Repository handling Candidate profile and resume document records."""

    def get_by_id(self, candidate_id: int) -> Optional[Candidate]:  # type: ignore[override]
        """Retrieve candidate with attached resume documents."""
        stmt = (
            select(Candidate)
            .where(Candidate.id == candidate_id)
            .options(joinedload(Candidate.resumes))
        )
        return self.session.scalars(stmt).unique().first()

    def get_by_email(self, email: str) -> Optional[Candidate]:
        """Find a candidate by exact email address."""
        stmt = select(Candidate).where(func.lower(Candidate.email) == email.strip().lower())
        return self.session.scalars(stmt).first()

    def get_by_file_hash(self, file_hash: str) -> Optional[ResumeDocument]:
        """Find existing resume document by SHA-256 file hash."""
        stmt = select(ResumeDocument).where(ResumeDocument.file_hash == file_hash)
        return self.session.scalars(stmt).first()

    def search(
        self,
        query: Optional[str] = None,
        skills: Optional[List[str]] = None,
        parsing_status: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> List[Candidate]:
        """Search candidate pool by text query, skills list, and parse status."""
        stmt = select(Candidate)
        clauses = []

        if parsing_status:
            clauses.append(Candidate.parsing_status == parsing_status)

        if query:
            q_pattern = f"%{query}%"
            clauses.append(
                or_(
                    Candidate.name.ilike(q_pattern),
                    Candidate.email.ilike(q_pattern),
                    Candidate.resume_summary.ilike(q_pattern),
                    Candidate.skills_json.ilike(q_pattern),
                )
            )

        if skills:
            for skill in skills:
                clauses.append(Candidate.skills_json.ilike(f"%{skill.strip()}%"))

        for clause in clauses:
            stmt = stmt.where(clause)

        stmt = stmt.order_by(Candidate.created_at.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(stmt).all())


class MatchRepository(BaseRepository):
    """Repository handling CandidateMatch and MatchEvidence records."""

    def get_matches_for_jd(
        self,
        jd_id: int,
        min_score: Optional[float] = None,
        max_score: Optional[float] = None,
        category: Optional[str] = None,
        human_review_status: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> List[CandidateMatch]:
        """Retrieve candidate matches for a job description with filters."""
        stmt = (
            select(CandidateMatch)
            .where(CandidateMatch.jd_id == jd_id)
            .options(
                joinedload(CandidateMatch.candidate),
                joinedload(CandidateMatch.match_evidences),
            )
        )

        if min_score is not None:
            stmt = stmt.where(CandidateMatch.match_score >= min_score)
        if max_score is not None:
            stmt = stmt.where(CandidateMatch.match_score <= max_score)
        if category:
            stmt = stmt.where(CandidateMatch.match_category == category)
        if human_review_status:
            stmt = stmt.where(CandidateMatch.human_review_status == human_review_status)

        stmt = stmt.order_by(CandidateMatch.match_score.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(stmt).unique().all())

    def get_candidate_match(self, candidate_id: int, jd_id: int) -> Optional[CandidateMatch]:
        """Retrieve match evaluation between specific candidate and job description."""
        stmt = (
            select(CandidateMatch)
            .where(
                CandidateMatch.candidate_id == candidate_id,
                CandidateMatch.jd_id == jd_id,
            )
            .options(
                joinedload(CandidateMatch.candidate),
                joinedload(CandidateMatch.match_evidences),
            )
        )
        return self.session.scalars(stmt).unique().first()

    def record_recruiter_review(
        self,
        candidate_match_id: int,
        reviewer: str,
        action: str,
        new_status: Optional[str] = None,
        reason: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> RecruiterReview:
        """Log a recruiter review decision and update candidate match status."""
        match_obj = self.get_by_id(CandidateMatch, candidate_match_id)
        if not match_obj:
            raise ValueError(f"CandidateMatch {candidate_match_id} not found.")

        prev_status = match_obj.human_review_status
        if new_status:
            match_obj.human_review_status = new_status
            if notes:
                match_obj.reviewer_notes = notes
            if reason:
                match_obj.reviewer_decision_reason = reason
            self.update(match_obj)

        review = RecruiterReview(
            candidate_match_id=candidate_match_id,
            reviewer=reviewer,
            action=action,
            previous_status=prev_status,
            new_status=new_status,
            reason=reason,
            notes=notes,
        )
        return self.create(review)


class ShortlistRepository(BaseRepository):
    """Repository handling Shortlists and Shortlist Candidates."""

    def get_shortlists_for_jd(
        self, jd_id: int, status: Optional[str] = None
    ) -> List[Shortlist]:
        """Retrieve shortlists created for a given JD."""
        clauses = [Shortlist.jd_id == jd_id]
        if status:
            clauses.append(Shortlist.status == status)
        stmt = (
            select(Shortlist)
            .where(*clauses)
            .options(
                joinedload(Shortlist.candidates).joinedload(ShortlistCandidate.candidate)
            )
            .order_by(Shortlist.created_at.desc())
        )
        return list(self.session.scalars(stmt).unique().all())

    def add_candidate_to_shortlist(
        self,
        shortlist_id: int,
        candidate_id: int,
        candidate_match_id: Optional[int] = None,
        status: str = "shortlisted",
        notes: Optional[str] = None,
    ) -> ShortlistCandidate:
        """Add candidate to shortlist or update entry if already present."""
        stmt = select(ShortlistCandidate).where(
            ShortlistCandidate.shortlist_id == shortlist_id,
            ShortlistCandidate.candidate_id == candidate_id,
        )
        existing = self.session.scalars(stmt).first()
        if existing:
            existing.status = status
            if notes:
                existing.recruiter_notes = notes
            if candidate_match_id:
                existing.candidate_match_id = candidate_match_id
            existing.reviewed_at = datetime.utcnow()
            self.update(existing)
            return existing

        entry = ShortlistCandidate(
            shortlist_id=shortlist_id,
            candidate_id=candidate_id,
            candidate_match_id=candidate_match_id,
            status=status,
            recruiter_notes=notes,
        )
        return self.create(entry)

    def remove_candidate_from_shortlist(self, shortlist_id: int, candidate_id: int) -> bool:
        """Remove a candidate from a shortlist."""
        stmt = select(ShortlistCandidate).where(
            ShortlistCandidate.shortlist_id == shortlist_id,
            ShortlistCandidate.candidate_id == candidate_id,
        )
        entry = self.session.scalars(stmt).first()
        if entry:
            self.delete(entry)
            return True
        return False
