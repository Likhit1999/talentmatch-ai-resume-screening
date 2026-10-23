"""Shortlist management service for TalentMatch AI.

Handles candidate shortlisting, pipeline stage updates, recruiter evaluations,
status transitions, and integration with the export engine and audit log.
"""

from collections import Counter
from datetime import datetime
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.orm import joinedload, selectinload

from database.connection import get_session
from database.models import (
    AuditLog,
    Candidate,
    CandidateMatch,
    JobDescription,
    Shortlist,
    ShortlistCandidate,
)
from services.export_service import ExportService

logger = logging.getLogger(__name__)

VALID_SHORTLIST_STATUSES = ["shortlisted", "interview_scheduled", "on_hold", "not_selected"]


class ShortlistService:
    """Service orchestrating candidate shortlists and recruitment pipeline stages."""

    def __init__(self, export_service: Optional[ExportService] = None) -> None:
        self.export_service = export_service or ExportService()

    def _log_audit(
        self,
        session,
        entity_id: Optional[int],
        action: str,
        details: Optional[Dict[str, Any]] = None,
        performed_by: Optional[str] = None,
    ) -> None:
        """Internal helper to write to the audit log."""
        try:
            audit = AuditLog(
                entity_type="Shortlist",
                entity_id=entity_id,
                action=action,
                details_json=json.dumps(details) if details else None,
                performed_by=performed_by or "Recruiter",
                performed_at=datetime.utcnow(),
            )
            session.add(audit)
        except Exception as exc:
            logger.warning("Failed to record shortlist audit log: %s", exc)

    def create_shortlist(
        self, name: str, jd_id: int, description: Optional[str] = None, created_by: str = "Recruiter"
    ) -> Dict[str, Any]:
        """Create a new candidate shortlist container for a Job Description.

        Args:
            name: Shortlist display name.
            jd_id: Target Job Description identifier.
            description: Optional descriptive notes.
            created_by: User attribution.

        Returns:
            dict: Serialized shortlist record.

        Raises:
            ValueError: If name is empty or Job Description does not exist.
        """
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("Shortlist name cannot be empty.")

        with get_session() as session:
            jd = session.get(JobDescription, jd_id)
            if not jd:
                raise ValueError(f"Job Description with ID {jd_id} not found.")

            shortlist = Shortlist(
                name=clean_name,
                jd_id=jd_id,
                description=description.strip() if description else None,
                status="active",
                created_by=created_by,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(shortlist)
            session.flush()

            shortlist_id = shortlist.id
            self._log_audit(
                session,
                entity_id=shortlist_id,
                action="create",
                details={"name": clean_name, "jd_id": jd_id, "jd_title": jd.title},
                performed_by=created_by,
            )

        logger.info("Created shortlist #%d ('%s') for JD #%d", shortlist_id, clean_name, jd_id)
        return self.get_shortlist(shortlist_id)

    def get_shortlist(self, shortlist_id: int) -> Dict[str, Any]:
        """Retrieve complete shortlist entity with candidate items and match details.

        Args:
            shortlist_id: Primary key of Shortlist.

        Returns:
            dict: Serialized shortlist structure.

        Raises:
            ValueError: If shortlist does not exist.
        """
        with get_session() as session:
            stmt = (
                select(Shortlist)
                .where(Shortlist.id == shortlist_id)
                .options(
                    joinedload(Shortlist.job_description),
                    selectinload(Shortlist.candidates).joinedload(ShortlistCandidate.candidate),
                    selectinload(Shortlist.candidates).joinedload(ShortlistCandidate.candidate_match),
                )
            )
            shortlist = session.scalars(stmt).unique().first()
            if not shortlist:
                raise ValueError(f"Shortlist with ID {shortlist_id} not found.")

            return self._serialize_shortlist(shortlist)

    def sync_unassigned_shortlisted_matches(self) -> int:
        """Find any CandidateMatches marked as 'shortlisted' that are not yet in a Shortlist pipeline.

        Creates active shortlists per Job Description as needed and assigns the candidate records.

        Returns:
            int: Number of new shortlist candidate records populated.
        """
        synced_count = 0
        with get_session() as session:
            # Query matches with human_review_status == 'shortlisted'
            matches = session.scalars(
                select(CandidateMatch).where(CandidateMatch.human_review_status == "shortlisted")
            ).all()

            for match in matches:
                # Find active shortlist for this requisition
                sl_stmt = (
                    select(Shortlist)
                    .where(Shortlist.jd_id == match.jd_id, Shortlist.status == "active")
                    .order_by(Shortlist.created_at.asc())
                )
                active_sl = session.scalars(sl_stmt).first()
                if not active_sl:
                    jd = session.get(JobDescription, match.jd_id)
                    jd_title = jd.title if jd else f"Requisition #{match.jd_id}"
                    active_sl = Shortlist(
                        name=f"{jd_title} - Shortlist",
                        jd_id=match.jd_id,
                        description=f"Auto-generated pipeline for shortlisted candidates from {jd_title}.",
                        status="active",
                        created_by="Recruiter",
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                    )
                    session.add(active_sl)
                    session.flush()

                # Check if already added
                entry_stmt = select(ShortlistCandidate).where(
                    ShortlistCandidate.shortlist_id == active_sl.id,
                    ShortlistCandidate.candidate_id == match.candidate_id,
                )
                existing = session.scalars(entry_stmt).first()
                if not existing:
                    entry = ShortlistCandidate(
                        shortlist_id=active_sl.id,
                        candidate_id=match.candidate_id,
                        candidate_match_id=match.id,
                        status="shortlisted",
                        recruiter_notes=match.reviewer_notes,
                        added_at=match.last_screened_at or datetime.utcnow(),
                        reviewed_at=datetime.utcnow(),
                    )
                    session.add(entry)
                    synced_count += 1
                else:
                    if existing.candidate_match_id != match.id:
                        existing.candidate_match_id = match.id

                active_sl.updated_at = datetime.utcnow()

            session.flush()

        logger.info("Synchronized %d shortlisted candidates into pipelines.", synced_count)
        return synced_count

    def get_shortlists(
        self, jd_id: Optional[int] = None, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve shortlists with optional filtering by JD or status.

        Args:
            jd_id: Optional Job Description ID filter.
            status: Optional status filter ('active', 'archived', or 'all').

        Returns:
            list of serialized shortlist summaries.
        """
        with get_session() as session:
            stmt = (
                select(Shortlist)
                .options(
                    joinedload(Shortlist.job_description),
                    selectinload(Shortlist.candidates).joinedload(ShortlistCandidate.candidate),
                    selectinload(Shortlist.candidates).joinedload(ShortlistCandidate.candidate_match),
                )
            )

            if jd_id:
                stmt = stmt.where(Shortlist.jd_id == jd_id)

            if status and status.lower() != "all":
                stmt = stmt.where(Shortlist.status == status.strip().lower())

            stmt = stmt.order_by(Shortlist.created_at.desc())
            shortlists = session.scalars(stmt).unique().all()

            return [self._serialize_shortlist(s) for s in shortlists]

    def add_candidate(
        self,
        shortlist_id: int,
        candidate_id: int,
        match_id: Optional[int] = None,
        notes: Optional[str] = None,
        performed_by: str = "Recruiter",
    ) -> Dict[str, Any]:
        """Add candidate to a shortlist, or update status/notes if already present.

        Args:
            shortlist_id: Shortlist ID.
            candidate_id: Candidate ID.
            match_id: Optional CandidateMatch ID. If omitted, looks up best existing match.
            notes: Recruiter notes for this candidate.
            performed_by: User attribution.

        Returns:
            dict: Serialized shortlist candidate entry.
        """
        with get_session() as session:
            shortlist = session.get(Shortlist, shortlist_id)
            if not shortlist:
                raise ValueError(f"Shortlist #{shortlist_id} not found.")

            candidate = session.get(Candidate, candidate_id)
            if not candidate:
                raise ValueError(f"Candidate #{candidate_id} not found.")

            # If match_id not provided, look for match between candidate and shortlist.jd_id
            resolved_match_id = match_id
            if not resolved_match_id:
                m_stmt = (
                    select(CandidateMatch.id)
                    .where(
                        CandidateMatch.candidate_id == candidate_id,
                        CandidateMatch.jd_id == shortlist.jd_id,
                    )
                    .order_by(CandidateMatch.last_screened_at.desc())
                )
                resolved_match_id = session.scalar(m_stmt)

            stmt = select(ShortlistCandidate).where(
                ShortlistCandidate.shortlist_id == shortlist_id,
                ShortlistCandidate.candidate_id == candidate_id,
            )
            existing = session.scalars(stmt).first()

            if existing:
                existing.status = "shortlisted"
                if notes:
                    existing.recruiter_notes = notes.strip()
                if resolved_match_id:
                    existing.candidate_match_id = resolved_match_id
                existing.reviewed_at = datetime.utcnow()
                session.flush()
                entry = existing
            else:
                entry = ShortlistCandidate(
                    shortlist_id=shortlist_id,
                    candidate_id=candidate_id,
                    candidate_match_id=resolved_match_id,
                    status="shortlisted",
                    recruiter_notes=notes.strip() if notes else None,
                    added_at=datetime.utcnow(),
                    reviewed_at=datetime.utcnow(),
                )
                session.add(entry)
                session.flush()

            # Also sync human review status on CandidateMatch if present
            if resolved_match_id:
                m_obj = session.get(CandidateMatch, resolved_match_id)
                if m_obj:
                    m_obj.human_review_status = "shortlisted"
                    if notes:
                        m_obj.reviewer_notes = notes.strip()

            shortlist.updated_at = datetime.utcnow()

            self._log_audit(
                session,
                entity_id=shortlist_id,
                action="add_candidate",
                details={
                    "candidate_id": candidate_id,
                    "candidate_name": candidate.name,
                    "match_id": resolved_match_id,
                },
                performed_by=performed_by,
            )

            return {
                "id": entry.id,
                "shortlist_id": entry.shortlist_id,
                "candidate_id": entry.candidate_id,
                "candidate_name": candidate.name,
                "status": entry.status,
                "recruiter_notes": entry.recruiter_notes,
                "match_id": entry.candidate_match_id,
                "added_at": entry.added_at.strftime("%Y-%m-%d %H:%M:%S") if entry.added_at else None,
            }

    def remove_candidate(
        self, shortlist_id: int, candidate_id: int, performed_by: str = "Recruiter"
    ) -> bool:
        """Remove candidate association from a shortlist.

        Args:
            shortlist_id: Target Shortlist ID.
            candidate_id: Target Candidate ID.
            performed_by: User attribution.

        Returns:
            bool: True if candidate was found and removed, False otherwise.
        """
        with get_session() as session:
            stmt = select(ShortlistCandidate).where(
                ShortlistCandidate.shortlist_id == shortlist_id,
                ShortlistCandidate.candidate_id == candidate_id,
            )
            entry = session.scalars(stmt).first()
            if not entry:
                return False

            session.delete(entry)

            # Update shortlist updated_at timestamp
            shortlist = session.get(Shortlist, shortlist_id)
            if shortlist:
                shortlist.updated_at = datetime.utcnow()

            self._log_audit(
                session,
                entity_id=shortlist_id,
                action="remove_candidate",
                details={"candidate_id": candidate_id},
                performed_by=performed_by,
            )
            return True

    def update_candidate_status(
        self,
        shortlist_id: int,
        candidate_id: int,
        status: str,
        notes: Optional[str] = None,
        performed_by: str = "Recruiter",
    ) -> Dict[str, Any]:
        """Update candidate pipeline stage and notes within a shortlist.

        Args:
            shortlist_id: Shortlist ID.
            candidate_id: Candidate ID.
            status: New stage ('shortlisted', 'interview_scheduled', 'on_hold', 'not_selected').
            notes: Optional updated recruiter notes.
            performed_by: User attribution.

        Returns:
            dict: Updated candidate item data.

        Raises:
            ValueError: If status is invalid or candidate not found in shortlist.
        """
        clean_status = (status or "").strip().lower()
        if clean_status not in VALID_SHORTLIST_STATUSES:
            raise ValueError(f"Invalid status '{status}'. Must be one of {VALID_SHORTLIST_STATUSES}.")

        with get_session() as session:
            stmt = select(ShortlistCandidate).where(
                ShortlistCandidate.shortlist_id == shortlist_id,
                ShortlistCandidate.candidate_id == candidate_id,
            )
            entry = session.scalars(stmt).first()
            if not entry:
                raise ValueError(f"Candidate #{candidate_id} not found in shortlist #{shortlist_id}.")

            entry.status = clean_status
            entry.reviewed_at = datetime.utcnow()
            if notes is not None:
                entry.recruiter_notes = notes.strip() if notes else None

            # Sync CandidateMatch human_review_status if attached
            if entry.candidate_match_id:
                m_obj = session.get(CandidateMatch, entry.candidate_match_id)
                if m_obj:
                    m_obj.human_review_status = clean_status
                    if notes is not None:
                        m_obj.reviewer_notes = notes.strip() if notes else None

            shortlist = session.get(Shortlist, shortlist_id)
            if shortlist:
                shortlist.updated_at = datetime.utcnow()

            self._log_audit(
                session,
                entity_id=shortlist_id,
                action="update_candidate_status",
                details={"candidate_id": candidate_id, "new_status": clean_status},
                performed_by=performed_by,
            )

            session.flush()
            return {
                "id": entry.id,
                "shortlist_id": entry.shortlist_id,
                "candidate_id": entry.candidate_id,
                "status": entry.status,
                "recruiter_notes": entry.recruiter_notes,
                "reviewed_at": entry.reviewed_at.strftime("%Y-%m-%d %H:%M:%S") if entry.reviewed_at else None,
            }

    def archive_shortlist(self, shortlist_id: int, performed_by: str = "Recruiter") -> Dict[str, Any]:
        """Mark a shortlist as archived.

        Args:
            shortlist_id: Target Shortlist ID.
            performed_by: User attribution.

        Returns:
            dict: Updated shortlist structure.
        """
        with get_session() as session:
            shortlist = session.get(Shortlist, shortlist_id)
            if not shortlist:
                raise ValueError(f"Shortlist #{shortlist_id} not found.")

            shortlist.status = "archived"
            shortlist.updated_at = datetime.utcnow()

            self._log_audit(
                session,
                entity_id=shortlist_id,
                action="archive",
                details={"name": shortlist.name},
                performed_by=performed_by,
            )

        return self.get_shortlist(shortlist_id)

    def export_shortlist(self, shortlist_id: int, format: str = "excel") -> str:
        """Export shortlist collection to Excel or CSV.

        Args:
            shortlist_id: Target Shortlist ID.
            format: 'excel' or 'csv'.

        Returns:
            str: Path to generated file.
        """
        data = self.get_shortlist(shortlist_id)
        if format.lower() == "csv":
            import pandas as pd
            candidates = data.get("candidates", [])
            rows = []
            for c in candidates:
                rows.append({
                    "Shortlist Name": data["name"],
                    "Job Requisition": data["jd_title"],
                    "Candidate ID": c["candidate_id"],
                    "Candidate Name": c["candidate_name"],
                    "Email": c["email"],
                    "Phone": c["phone"],
                    "Match Score": c["match_score"],
                    "Match Category": c["match_category"],
                    "Pipeline Status": c["status"],
                    "Recruiter Notes": c["recruiter_notes"],
                    "Added Date": c["added_at"],
                    "Reviewed Date": c["reviewed_at"],
                })
            df = pd.DataFrame(rows)
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"shortlist_{data['name'][:30]}_{shortlist_id}_{ts}.csv"
            clean_filename = "".join(x for x in filename if x.isalnum() or x in "._- ")
            file_path = self.export_service.exports_dir / clean_filename
            df.to_csv(file_path, index=False, encoding="utf-8-sig")
            return str(file_path)
        else:
            return self.export_service.export_shortlist_to_excel(data)

    def get_shortlist_stats(self, shortlist_id: int) -> Dict[str, Any]:
        """Compute recruitment pipeline stage counts, score aggregations, and top skills.

        Args:
            shortlist_id: Target Shortlist ID.

        Returns:
            dict containing pipeline telemetry.
        """
        data = self.get_shortlist(shortlist_id)
        candidates = data.get("candidates", [])

        status_counts = {st: 0 for st in VALID_SHORTLIST_STATUSES}
        scores = []
        skills_counter: Counter = Counter()

        for c in candidates:
            st = c.get("status")
            if st in status_counts:
                status_counts[st] += 1
            else:
                status_counts[st] = status_counts.get(st, 0) + 1

            if c.get("match_score") is not None:
                try:
                    scores.append(float(c["match_score"]))
                except (ValueError, TypeError):
                    pass

            for skill in c.get("skills", []):
                if skill and skill.strip():
                    skills_counter[skill.strip().title()] += 1

        avg_score = (sum(scores) / len(scores)) if scores else 0.0
        min_score = min(scores) if scores else 0.0
        max_score = max(scores) if scores else 0.0

        return {
            "total_candidates": len(candidates),
            "by_status": status_counts,
            "avg_match_score": round(avg_score, 1),
            "min_score": round(min_score, 1),
            "max_score": round(max_score, 1),
            "top_skills": dict(skills_counter.most_common(10)),
        }

    def _serialize_shortlist(self, shortlist: Shortlist) -> Dict[str, Any]:
        """Convert Shortlist ORM object into a dictionary representation."""
        jd_title = shortlist.job_description.title if shortlist.job_description else f"JD #{shortlist.jd_id}"
        candidates = []

        for entry in shortlist.candidates:
            cand = entry.candidate
            cand_name = cand.name if cand else f"Candidate #{entry.candidate_id}"
            cand_email = cand.email if cand else None
            cand_phone = cand.phone if cand else None
            skills = cand.get_skills() if cand else []

            match = entry.candidate_match
            match_score = float(match.match_score) if match else None
            match_cat = match.match_category if match else "needs_review"

            candidates.append({
                "entry_id": entry.id,
                "candidate_id": entry.candidate_id,
                "candidate_name": cand_name,
                "name": cand_name,
                "email": cand_email,
                "phone": cand_phone,
                "skills": skills,
                "match_id": entry.candidate_match_id,
                "match_score": match_score,
                "match_category": match_cat,
                "status": entry.status,
                "recruiter_notes": entry.recruiter_notes,
                "notes": entry.recruiter_notes,
                "added_at": entry.added_at.strftime("%Y-%m-%d %H:%M") if entry.added_at else None,
                "reviewed_at": entry.reviewed_at.strftime("%Y-%m-%d %H:%M") if entry.reviewed_at else None,
            })

        return {
            "id": shortlist.id,
            "name": shortlist.name,
            "jd_id": shortlist.jd_id,
            "jd_title": jd_title,
            "description": shortlist.description,
            "status": shortlist.status,
            "created_by": shortlist.created_by,
            "candidate_count": len(candidates),
            "created_at": shortlist.created_at.strftime("%Y-%m-%d %H:%M") if shortlist.created_at else None,
            "updated_at": shortlist.updated_at.strftime("%Y-%m-%d %H:%M") if shortlist.updated_at else None,
            "candidates": candidates,
        }
