"""Job Description management service for TalentMatch AI.

Provides comprehensive business logic for Job Description CRUD, versioning,
requirement lifecycle management, status toggling, and audit logging.
"""

from datetime import datetime
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from database.connection import get_session
from database.models import (
    AuditLog,
    CandidateMatch,
    JDRequirement,
    JDVersion,
    JobDescription,
    ScreeningRun,
    Shortlist,
)

logger = logging.getLogger(__name__)

# Valid workflow statuses for Job Descriptions
VALID_JD_STATUSES = ["Open", "In Progress", "On Hold", "Closed", "Draft"]


class JDService:
    """Service handling Job Description operations, versioning, and requirements."""

    def __init__(self) -> None:
        pass

    def _log_audit(
        self,
        session,
        entity_id: Optional[int],
        action: str,
        details: Optional[Dict[str, Any]] = None,
        performed_by: Optional[str] = None,
    ) -> None:
        """Helper to create an audit log entry within the active session."""
        try:
            audit = AuditLog(
                entity_type="JobDescription",
                entity_id=entity_id,
                action=action,
                details_json=json.dumps(details) if details else None,
                performed_by=performed_by or "system",
            )
            session.add(audit)
        except Exception as exc:
            logger.warning("Failed to record audit log: %s", exc)

    def create_jd(self, data: Dict[str, Any]) -> JobDescription:
        """Create a new Job Description and generate an initial version snapshot.

        Args:
            data: Dictionary containing Job Description attributes.

        Returns:
            JobDescription: The persisted Job Description model instance.

        Raises:
            ValueError: If required fields (title, description_text) are missing.
        """
        title = (data.get("title") or "").strip()
        description_text = (data.get("description_text") or "").strip()

        if not title:
            raise ValueError("Job title is required and cannot be empty.")
        if not description_text:
            raise ValueError("Job description text is required and cannot be empty.")

        exp_min = float(data["experience_min"]) if data.get("experience_min") is not None and str(data["experience_min"]).strip() != "" else None
        exp_max = float(data["experience_max"]) if data.get("experience_max") is not None and str(data["experience_max"]).strip() != "" else None

        # Auto-detect required experience range from JD text if not provided manually
        if (exp_min is None or exp_min <= 0) and description_text:
            from services.scoring_service import parse_experience_range_from_text
            detected_min, detected_max = parse_experience_range_from_text(description_text)
            if detected_min is not None:
                exp_min = detected_min
                if exp_max is None or exp_max <= 0:
                    exp_max = detected_max

        with get_session() as session:
            jd = JobDescription(
                title=title,
                department=(data.get("department") or "").strip() or None,
                description_text=description_text,
                location=(data.get("location") or "").strip() or None,
                experience_min=exp_min,
                experience_max=exp_max,
                employment_type=(data.get("employment_type") or "").strip() or None,
                qualifications=(data.get("qualifications") or "").strip() or None,
                responsibilities=(data.get("responsibilities") or "").strip() or None,
                certifications=(data.get("certifications") or "").strip() or None,
                recruiter_notes=(data.get("recruiter_notes") or "").strip() or None,
                status=data.get("status", "Active"),
                analysis_status=data.get("analysis_status", "not_analyzed"),
                created_by=data.get("created_by", "Recruiter"),
            )
            session.add(jd)
            session.flush()

            # Create initial version snapshot (v1)
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
                "status": jd.status,
                "requirements": [],
            }
            v1 = JDVersion(
                jd_id=jd.id,
                version_number=1,
                snapshot_data=json.dumps(snapshot_dict),
            )
            session.add(v1)

            self._log_audit(
                session,
                entity_id=jd.id,
                action="create",
                details={"title": jd.title, "department": jd.department},
                performed_by=jd.created_by,
            )

            session.flush()
            # Eagerly load requirements to make detached access safe
            stmt = (
                select(JobDescription)
                .where(JobDescription.id == jd.id)
                .options(selectinload(JobDescription.requirements))
            )
            created_jd = session.scalars(stmt).unique().first()
            return created_jd

    def get_jd(self, jd_id: int) -> JobDescription:
        """Retrieve a single Job Description by ID with requirements pre-loaded.

        Args:
            jd_id: Primary key ID of the Job Description.

        Returns:
            JobDescription: Found Job Description instance.

        Raises:
            ValueError: If Job Description is not found.
        """
        with get_session() as session:
            stmt = (
                select(JobDescription)
                .where(JobDescription.id == jd_id)
                .options(
                    selectinload(JobDescription.requirements),
                    selectinload(JobDescription.versions),
                )
            )
            jd = session.scalars(stmt).unique().first()
            if not jd:
                raise ValueError(f"Job Description with ID {jd_id} not found.")
            return jd

    def get_all_jds(
        self,
        filters: Optional[Dict[str, Any]] = None,
        search: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Tuple[List[JobDescription], int]:
        """Retrieve paginated Job Descriptions with optional filtering and search.

        Args:
            filters: Optional dictionary containing field filters (status, department, analysis_status).
            search: Optional text search string across title, description, qualifications, responsibilities.
            offset: Record offset for pagination.
            limit: Maximum records to return.

        Returns:
            Tuple[List[JobDescription], int]: (List of JDs, Total count matching filters).
        """
        filters = filters or {}
        clauses = []

        if filters.get("status"):
            st_val = filters["status"]
            if isinstance(st_val, (list, tuple, set)):
                clauses.append(JobDescription.status.in_(list(st_val)))
            elif st_val.lower() != "all":
                clauses.append(JobDescription.status == st_val)

        if filters.get("department"):
            clauses.append(JobDescription.department == filters["department"])

        if filters.get("analysis_status"):
            clauses.append(JobDescription.analysis_status == filters["analysis_status"])

        if search and search.strip():
            s = f"%{search.strip()}%"
            clauses.append(
                or_(
                    JobDescription.title.ilike(s),
                    JobDescription.description_text.ilike(s),
                    JobDescription.department.ilike(s),
                    JobDescription.qualifications.ilike(s),
                    JobDescription.responsibilities.ilike(s),
                    JobDescription.location.ilike(s),
                )
            )

        with get_session() as session:
            # Count query
            count_stmt = select(func.count()).select_from(JobDescription)
            if clauses:
                count_stmt = count_stmt.where(*clauses)
            total_count = session.scalar(count_stmt) or 0

            # Records query
            stmt = (
                select(JobDescription)
                .options(selectinload(JobDescription.requirements))
                .order_by(JobDescription.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            if clauses:
                stmt = stmt.where(*clauses)

            jds = list(session.scalars(stmt).unique().all())
            return jds, total_count

    def update_jd(self, jd_id: int, data: Dict[str, Any]) -> JobDescription:
        """Update an existing Job Description.

        If core requirement content (description_text, qualifications, responsibilities,
        certifications, experience range) is modified and the JD has previously been
        analyzed, analysis_status is automatically transitioned to 'needs_reanalysis'.

        Args:
            jd_id: Primary key ID of the Job Description to update.
            data: Dictionary of fields to update.

        Returns:
            JobDescription: Updated Job Description instance.

        Raises:
            ValueError: If Job Description is not found or required fields are blank.
        """
        with get_session() as session:
            stmt = (
                select(JobDescription)
                .where(JobDescription.id == jd_id)
                .options(selectinload(JobDescription.requirements))
            )
            jd = session.scalars(stmt).unique().first()
            if not jd:
                raise ValueError(f"Job Description with ID {jd_id} not found.")

            content_fields = [
                "description_text",
                "qualifications",
                "responsibilities",
                "certifications",
                "experience_min",
                "experience_max",
            ]

            content_changed = False
            for field in content_fields:
                if field in data:
                    new_val = data[field]
                    if field in ("experience_min", "experience_max"):
                        new_val = float(new_val) if new_val is not None and str(new_val).strip() != "" else None
                    else:
                        new_val = (new_val or "").strip() or None

                    old_val = getattr(jd, field)
                    if new_val != old_val:
                        content_changed = True
                        setattr(jd, field, new_val)

            # Update other non-content fields
            if "title" in data and data["title"]:
                title_val = data["title"].strip()
                if not title_val:
                    raise ValueError("Job title cannot be empty.")
                jd.title = title_val

            if "department" in data:
                jd.department = data["department"].strip() if data["department"] else None

            if "location" in data:
                jd.location = data["location"].strip() if data["location"] else None

            if "employment_type" in data:
                jd.employment_type = data["employment_type"].strip() if data["employment_type"] else None

            if "recruiter_notes" in data:
                jd.recruiter_notes = data["recruiter_notes"].strip() if data["recruiter_notes"] else None

            if "status" in data and data["status"]:
                jd.status = data["status"]

            # Analysis status flagging logic
            if "analysis_status" in data and data["analysis_status"]:
                jd.analysis_status = data["analysis_status"]
            elif content_changed and jd.analysis_status == "analyzed":
                jd.analysis_status = "needs_reanalysis"
                logger.info(
                    "JD #%d content modified: transitioning analysis_status to 'needs_reanalysis'",
                    jd_id,
                )

            jd.updated_at = datetime.utcnow()

            # Record version snapshot if content changed
            if content_changed:
                self._create_version_snapshot_internal(session, jd)

            self._log_audit(
                session,
                entity_id=jd.id,
                action="update",
                details={
                    "content_changed": content_changed,
                    "analysis_status": jd.analysis_status,
                },
            )

            session.flush()
            # Reload to return clean instance
            return self.get_jd(jd_id)

    def delete_jd(self, jd_id: int, force: bool = False) -> bool:
        """Delete a Job Description with safety checks for linked matches and shortlists.

        Args:
            jd_id: ID of the Job Description to remove.
            force: If True, bypass checks for linked screening runs/matches/shortlists.

        Returns:
            bool: True if deletion succeeded.

        Raises:
            ValueError: If active dependencies exist and force is False.
        """
        with get_session() as session:
            jd = session.get(JobDescription, jd_id)
            if not jd:
                logger.warning("Attempted to delete non-existent JD #%d", jd_id)
                return False

            if not force:
                matches_count = (
                    session.scalar(
                        select(func.count())
                        .select_from(CandidateMatch)
                        .where(CandidateMatch.jd_id == jd_id)
                    )
                    or 0
                )
                shortlists_count = (
                    session.scalar(
                        select(func.count())
                        .select_from(Shortlist)
                        .where(Shortlist.jd_id == jd_id)
                    )
                    or 0
                )
                runs_count = (
                    session.scalar(
                        select(func.count())
                        .select_from(ScreeningRun)
                        .where(ScreeningRun.jd_id == jd_id)
                    )
                    or 0
                )

                if matches_count > 0 or shortlists_count > 0 or runs_count > 0:
                    raise ValueError(
                        f"Cannot delete Job Description #{jd_id} because it is referenced by "
                        f"{matches_count} candidate match(es), {shortlists_count} shortlist(s), "
                        f"and {runs_count} screening run(s). Enable force delete to proceed."
                    )

            # Record audit before deletion
            self._log_audit(
                session,
                entity_id=jd_id,
                action="delete",
                details={"title": jd.title, "force": force},
            )

            session.delete(jd)
            logger.info("Deleted Job Description #%d (force=%s)", jd_id, force)
            return True

    def update_status(self, jd_id: int, new_status: str) -> JobDescription:
        """Update Job Description status (Open, In Progress, On Hold, Closed, Draft).

        Args:
            jd_id: ID of the Job Description.
            new_status: Target status string.

        Returns:
            JobDescription: Updated Job Description instance.
        """
        valid_normalized = {s.lower(): s for s in VALID_JD_STATUSES}
        # Also support legacy Active / Inactive
        valid_normalized["active"] = "Open"
        valid_normalized["inactive"] = "Closed"

        target_status = valid_normalized.get(new_status.strip().lower())
        if not target_status:
            raise ValueError(
                f"Invalid status '{new_status}'. Allowed statuses: {', '.join(VALID_JD_STATUSES)}"
            )

        with get_session() as session:
            jd = session.get(JobDescription, jd_id)
            if not jd:
                raise ValueError(f"Job Description with ID {jd_id} not found.")

            old_status = jd.status
            jd.status = target_status
            jd.updated_at = datetime.utcnow()

            self._log_audit(
                session,
                entity_id=jd.id,
                action="update_status",
                details={"old_status": old_status, "new_status": target_status},
            )

            session.flush()
            logger.info("Updated JD #%d status from '%s' to '%s'", jd_id, old_status, target_status)

        return self.get_jd(jd_id)

    def toggle_status(self, jd_id: int) -> JobDescription:
        """Toggle Job Description status (Open <-> Closed).

        Args:
            jd_id: ID of the Job Description.

        Returns:
            JobDescription: Updated Job Description instance.
        """
        with get_session() as session:
            jd = session.get(JobDescription, jd_id)
            if not jd:
                raise ValueError(f"Job Description with ID {jd_id} not found.")

            # If Open/In Progress/Active, transition to Closed; otherwise reopen as Open
            if jd.status in ("Open", "In Progress", "Active"):
                new_status = "Closed"
            else:
                new_status = "Open"

            jd.status = new_status
            jd.updated_at = datetime.utcnow()

            self._log_audit(
                session,
                entity_id=jd.id,
                action="toggle_status",
                details={"new_status": new_status},
            )

            session.flush()

        return self.get_jd(jd_id)

    def get_jd_screening_summary(self, jd_id: int) -> Dict[str, Any]:
        """Retrieve complete screening evaluation summary for a specific Job Description.

        Returns candidate list, score distributions, and review status breakdown.

        Args:
            jd_id: Primary key of Job Description.

        Returns:
            dict containing:
                - total_screened (int)
                - by_category (dict)
                - by_review_status (dict)
                - average_score (float)
                - candidates (list of match records)
        """
        with get_session() as session:
            stmt = (
                select(CandidateMatch)
                .where(CandidateMatch.jd_id == jd_id)
                .options(
                    selectinload(CandidateMatch.candidate),
                )
                .order_by(CandidateMatch.match_score.desc())
            )
            matches = session.scalars(stmt).unique().all()

            total = len(matches)
            by_category: Dict[str, int] = {}
            by_review: Dict[str, int] = {}
            score_sum = 0.0
            candidate_rows = []

            for m in matches:
                cat = m.match_category or "unknown"
                by_category[cat] = by_category.get(cat, 0) + 1

                rev = m.human_review_status or "pending"
                by_review[rev] = by_review.get(rev, 0) + 1

                score_sum += m.match_score or 0.0

                cand = m.candidate
                candidate_rows.append({
                    "match_id": m.id,
                    "candidate_id": m.candidate_id,
                    "candidate_name": cand.name if cand else "Unknown",
                    "email": cand.email if cand else None,
                    "phone": cand.phone if cand else None,
                    "match_score": m.match_score,
                    "match_category": m.match_category,
                    "mandatory_met": f"{m.mandatory_met}/{m.mandatory_total}",
                    "preferred_met": f"{m.preferred_met}/{m.preferred_total}",
                    "human_review_status": m.human_review_status,
                    "reviewer_notes": m.reviewer_notes,
                    "last_screened_at": m.last_screened_at.strftime("%Y-%m-%d %H:%M") if m.last_screened_at else None,
                })

            avg_score = round(score_sum / total, 1) if total > 0 else 0.0

            return {
                "jd_id": jd_id,
                "total_screened": total,
                "average_score": avg_score,
                "by_category": by_category,
                "by_review_status": by_review,
                "candidates": candidate_rows,
            }

    def duplicate_jd(self, jd_id: int) -> JobDescription:
        """Duplicate an existing Job Description and clone its requirements.

        Args:
            jd_id: ID of the original Job Description to duplicate.

        Returns:
            JobDescription: The newly created duplicate Job Description.
        """
        with get_session() as session:
            stmt = (
                select(JobDescription)
                .where(JobDescription.id == jd_id)
                .options(selectinload(JobDescription.requirements))
            )
            original = session.scalars(stmt).unique().first()
            if not original:
                raise ValueError(f"Job Description with ID {jd_id} not found.")

            duplicate_title = f"{original.title} (Copy)"

            new_jd = JobDescription(
                title=duplicate_title,
                department=original.department,
                description_text=original.description_text,
                location=original.location,
                experience_min=original.experience_min,
                experience_max=original.experience_max,
                employment_type=original.employment_type,
                qualifications=original.qualifications,
                responsibilities=original.responsibilities,
                certifications=original.certifications,
                recruiter_notes=original.recruiter_notes,
                status="Active",
                analysis_status="not_analyzed",
                created_by="Recruiter",
            )
            session.add(new_jd)
            session.flush()

            # Clone requirements
            for req in original.requirements:
                cloned_req = JDRequirement(
                    jd_id=new_jd.id,
                    requirement_name=req.requirement_name,
                    category=req.category,
                    importance=req.importance,
                    original_evidence=req.original_evidence,
                    normalized_value=req.normalized_value,
                    weight=req.weight,
                    is_enabled=req.is_enabled,
                    recruiter_notes=req.recruiter_notes,
                )
                session.add(cloned_req)

            session.flush()

            # Create initial version snapshot
            self._create_version_snapshot_internal(session, new_jd)

            self._log_audit(
                session,
                entity_id=new_jd.id,
                action="duplicate",
                details={"duplicated_from": jd_id, "title": new_jd.title},
            )

            session.flush()
            return self.get_jd(new_jd.id)

    def _create_version_snapshot_internal(
        self, session, jd: JobDescription
    ) -> JDVersion:
        """Internal helper to create a version snapshot within an existing session."""
        version_count = (
            session.scalar(
                select(func.count())
                .select_from(JDVersion)
                .where(JDVersion.jd_id == jd.id)
            )
            or 0
        )
        next_version = version_count + 1

        # Fetch requirements if not loaded
        req_stmt = (
            select(JDRequirement)
            .where(JDRequirement.jd_id == jd.id)
            .order_by(JDRequirement.id.asc())
        )
        requirements = list(session.scalars(req_stmt).all())

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
            "status": jd.status,
            "requirements": [
                {
                    "name": r.requirement_name,
                    "category": r.category,
                    "importance": r.importance,
                    "normalized_value": r.normalized_value,
                    "weight": r.weight,
                    "is_enabled": r.is_enabled,
                }
                for r in requirements
            ],
        }

        version = JDVersion(
            jd_id=jd.id,
            version_number=next_version,
            snapshot_data=json.dumps(snapshot_dict),
        )
        session.add(version)
        session.flush()
        return version

    def create_jd_version_snapshot(self, jd_id: int) -> JDVersion:
        """Explicitly capture a historical version snapshot for a Job Description.

        Args:
            jd_id: ID of the Job Description.

        Returns:
            JDVersion: The recorded snapshot record.
        """
        with get_session() as session:
            jd = session.get(JobDescription, jd_id)
            if not jd:
                raise ValueError(f"Job Description with ID {jd_id} not found.")

            version = self._create_version_snapshot_internal(session, jd)
            self._log_audit(
                session,
                entity_id=jd.id,
                action="version_snapshot",
                details={"version_number": version.version_number},
            )
            return version

    def get_jd_versions(self, jd_id: int) -> List[JDVersion]:
        """Fetch all historical snapshots for a Job Description in reverse chronological order.

        Args:
            jd_id: ID of the Job Description.

        Returns:
            List[JDVersion]: List of versions ordered by version_number descending.
        """
        with get_session() as session:
            stmt = (
                select(JDVersion)
                .where(JDVersion.jd_id == jd_id)
                .order_by(JDVersion.version_number.desc())
            )
            return list(session.scalars(stmt).all())

    def get_jd_requirements(
        self, jd_id: int, enabled_only: bool = False
    ) -> List[JDRequirement]:
        """Fetch all atomic requirements linked to a Job Description.

        Args:
            jd_id: ID of the Job Description.
            enabled_only: If True, only return requirements where is_enabled is True.

        Returns:
            List[JDRequirement]: Ordered list of requirement models.
        """
        with get_session() as session:
            stmt = select(JDRequirement).where(JDRequirement.jd_id == jd_id)
            if enabled_only:
                stmt = stmt.where(JDRequirement.is_enabled.is_(True))
            stmt = stmt.order_by(JDRequirement.id.asc())
            return list(session.scalars(stmt).all())

    def add_requirement(self, jd_id: int, data: Dict[str, Any]) -> JDRequirement:
        """Add a single atomic requirement to a Job Description.

        Args:
            jd_id: ID of the target Job Description.
            data: Requirement attribute dictionary.

        Returns:
            JDRequirement: Created requirement record.
        """
        req_name = (data.get("requirement_name") or "").strip()
        if not req_name:
            raise ValueError("Requirement name is required and cannot be empty.")

        with get_session() as session:
            jd = session.get(JobDescription, jd_id)
            if not jd:
                raise ValueError(f"Job Description with ID {jd_id} not found.")

            req = JDRequirement(
                jd_id=jd_id,
                requirement_name=req_name,
                category=data.get("category", "mandatory_skill"),
                importance=data.get("importance", "mandatory"),
                original_evidence=data.get("original_evidence"),
                normalized_value=(data.get("normalized_value") or req_name).strip().lower(),
                weight=float(data.get("weight", 1.0)),
                is_enabled=bool(data.get("is_enabled", True)),
                recruiter_notes=data.get("recruiter_notes"),
            )
            session.add(req)
            session.flush()

            self._log_audit(
                session,
                entity_id=jd_id,
                action="add_requirement",
                details={"requirement_name": req.requirement_name, "category": req.category},
            )
            return req

    def update_requirement(self, req_id: int, data: Dict[str, Any]) -> JDRequirement:
        """Update an existing requirement.

        Args:
            req_id: Primary key ID of the requirement.
            data: Attributes to update.

        Returns:
            JDRequirement: Updated requirement instance.
        """
        with get_session() as session:
            req = session.get(JDRequirement, req_id)
            if not req:
                raise ValueError(f"JDRequirement with ID {req_id} not found.")

            if "requirement_name" in data and data["requirement_name"]:
                req.requirement_name = data["requirement_name"].strip()
            if "category" in data and data["category"]:
                req.category = data["category"]
            if "importance" in data and data["importance"]:
                req.importance = data["importance"]
            if "original_evidence" in data:
                req.original_evidence = data["original_evidence"]
            if "normalized_value" in data and data["normalized_value"]:
                req.normalized_value = data["normalized_value"].strip().lower()
            if "weight" in data and data["weight"] is not None:
                req.weight = float(data["weight"])
            if "is_enabled" in data:
                req.is_enabled = bool(data["is_enabled"])
            if "recruiter_notes" in data:
                req.recruiter_notes = data["recruiter_notes"]

            req.updated_at = datetime.utcnow()
            session.flush()
            return req

    def delete_requirement(self, req_id: int) -> bool:
        """Delete an atomic requirement by ID.

        Args:
            req_id: Primary key ID of the requirement.

        Returns:
            bool: True if deleted successfully, False if not found.
        """
        with get_session() as session:
            req = session.get(JDRequirement, req_id)
            if not req:
                return False

            jd_id = req.jd_id
            session.delete(req)
            session.flush()

            self._log_audit(
                session,
                entity_id=jd_id,
                action="delete_requirement",
                details={"requirement_id": req_id},
            )
            return True

    def save_requirements(
        self, jd_id: int, requirements: List[Dict[str, Any]]
    ) -> List[JDRequirement]:
        """Batch persist structured requirements for a Job Description.

        Replaces existing requirements, transitions analysis_status to 'analyzed',
        and generates a version snapshot of the newly analyzed state.

        Args:
            jd_id: ID of the Job Description.
            requirements: List of requirement specification dictionaries.

        Returns:
            List[JDRequirement]: List of persisted requirement models.
        """
        with get_session() as session:
            jd = session.get(JobDescription, jd_id)
            if not jd:
                raise ValueError(f"Job Description with ID {jd_id} not found.")

            # Clear existing requirements
            session.execute(
                delete(JDRequirement).where(JDRequirement.jd_id == jd_id)
            )

            saved_entities: List[JDRequirement] = []
            for item in requirements:
                name = (item.get("requirement_name") or "").strip()
                if not name:
                    continue

                req = JDRequirement(
                    jd_id=jd_id,
                    requirement_name=name,
                    category=item.get("category", "mandatory_skill"),
                    importance=item.get("importance", "mandatory"),
                    original_evidence=item.get("original_evidence"),
                    normalized_value=(item.get("normalized_value") or name).strip().lower(),
                    weight=float(item.get("weight", 1.0)),
                    is_enabled=bool(item.get("is_enabled", True)),
                    recruiter_notes=item.get("recruiter_notes"),
                )
                session.add(req)
                saved_entities.append(req)

            # Update JD analysis status
            jd.analysis_status = "analyzed"
            jd.updated_at = datetime.utcnow()
            session.flush()

            # Record version snapshot with new requirements
            self._create_version_snapshot_internal(session, jd)

            self._log_audit(
                session,
                entity_id=jd_id,
                action="save_requirements",
                details={
                    "total_saved": len(saved_entities),
                    "analysis_status": "analyzed",
                },
            )

            session.flush()
            return self.get_jd_requirements(jd_id)

    def mark_analyzed(self, jd_id: int) -> None:
        """Mark a Job Description analysis_status as 'analyzed'.

        Args:
            jd_id: ID of the Job Description.
        """
        with get_session() as session:
            jd = session.get(JobDescription, jd_id)
            if not jd:
                raise ValueError(f"Job Description with ID {jd_id} not found.")
            jd.analysis_status = "analyzed"
            jd.updated_at = datetime.utcnow()
            self._log_audit(
                session,
                entity_id=jd_id,
                action="mark_analyzed",
            )
