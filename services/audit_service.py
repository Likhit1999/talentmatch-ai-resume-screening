"""Audit logging and screening run telemetry service for TalentMatch AI.

Records system activity logs, provides filtering and query access for governance,
formats live recent activity streams, and retrieves batch screening run histories.
"""

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from database.connection import get_session
from database.models import (
    AuditLog,
    CandidateMatch,
    JobDescription,
    ScreeningBatch,
    ScreeningRun,
)

logger = logging.getLogger(__name__)


def _format_time_ago(dt: Optional[datetime]) -> str:
    """Format datetime into a friendly relative time string."""
    if not dt:
        return "Unknown time"

    now = datetime.now(timezone.utc) if dt.tzinfo else datetime.utcnow()
    diff = now - dt

    seconds = int(diff.total_seconds())
    if seconds < 0:
        return "Just now"
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 7:
        return f"{days}d ago"
    if days < 30:
        weeks = days // 7
        return f"{weeks}w ago"
    return dt.strftime("%b %d, %Y")


def _get_entity_icon(entity_type: str) -> str:
    """Return appropriate emoji icon for entity type."""
    t = (entity_type or "").lower()
    if "candidate" in t:
        return "👤"
    if "job" in t or "jd" in t:
        return "📋"
    if "shortlist" in t:
        return "📑"
    if "batch" in t or "screening" in t or "run" in t:
        return "⚡"
    if "setting" in t:
        return "⚙️"
    if "review" in t:
        return "🔍"
    return "🛡️"


class AuditService:
    """Service providing audit logging, governance trail, and screening history."""

    def __init__(self) -> None:
        pass

    def log_action(
        self,
        entity_type: str,
        entity_id: Optional[int],
        action: str,
        details: Optional[Dict[str, Any]] = None,
        performed_by: Optional[str] = None,
    ) -> None:
        """Record an immutable audit log entry in the database.

        Args:
            entity_type: Model name (e.g. 'JobDescription', 'Candidate', 'Shortlist', 'Setting').
            entity_id: Primary key of the affected entity.
            action: Verb describing the operation (e.g. 'create', 'update', 'delete', 'export').
            details: Optional dictionary containing event parameters or diffs.
            performed_by: User or system identifier.
        """
        try:
            with get_session() as session:
                audit = AuditLog(
                    entity_type=entity_type.strip(),
                    entity_id=entity_id,
                    action=action.strip().lower(),
                    details_json=json.dumps(details) if details else None,
                    performed_by=performed_by.strip() if performed_by else "system",
                    performed_at=datetime.utcnow(),
                )
                session.add(audit)
                session.flush()
                logger.debug(
                    "Recorded audit log: %s #%s -> %s by %s",
                    entity_type,
                    entity_id,
                    action,
                    performed_by,
                )
        except Exception as exc:
            logger.error("Failed to persist audit log entry: %s", exc, exc_info=True)

    def get_audit_log(
        self,
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        action: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Query paginated audit log entries with optional filters.

        Args:
            entity_type: Optional filter by entity type (case-insensitive, 'all' returns all).
            entity_id: Optional exact entity ID filter.
            action: Optional action verb filter.
            offset: Record offset for pagination.
            limit: Maximum records to return.

        Returns:
            Tuple of (list of audit log dictionaries, total matching count).
        """
        clauses = []

        if entity_type and entity_type.strip().lower() != "all":
            clauses.append(func.lower(AuditLog.entity_type) == entity_type.strip().lower())

        if entity_id is not None:
            clauses.append(AuditLog.entity_id == entity_id)

        if action and action.strip().lower() != "all":
            clauses.append(func.lower(AuditLog.action) == action.strip().lower())

        with get_session() as session:
            count_stmt = select(func.count()).select_from(AuditLog)
            if clauses:
                count_stmt = count_stmt.where(*clauses)
            total_count = session.scalar(count_stmt) or 0

            stmt = select(AuditLog)
            if clauses:
                stmt = stmt.where(*clauses)

            stmt = stmt.order_by(AuditLog.performed_at.desc()).offset(offset).limit(limit)
            logs = session.scalars(stmt).all()

            results = []
            for item in logs:
                details_dict = {}
                if item.details_json:
                    try:
                        details_dict = json.loads(item.details_json)
                    except Exception:
                        details_dict = {"raw": item.details_json}

                results.append({
                    "id": item.id,
                    "entity_type": item.entity_type,
                    "entity_id": item.entity_id,
                    "action": item.action,
                    "details": details_dict,
                    "details_json": item.details_json,
                    "performed_by": item.performed_by or "system",
                    "performed_at": item.performed_at.strftime("%Y-%m-%d %H:%M:%S") if item.performed_at else None,
                    "time_ago": _format_time_ago(item.performed_at),
                    "icon": _get_entity_icon(item.entity_type),
                })

            return results, total_count

    def get_recent_activity(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Fetch the most recent system activities formatted for dashboard feeds.

        Args:
            limit: Maximum number of events to return.

        Returns:
            list of activity dicts with human-readable summary, icon, and relative timestamp.
        """
        logs, _ = self.get_audit_log(limit=limit)
        feed = []

        for log in logs:
            action = log["action"].replace("_", " ").title()
            entity = log["entity_type"]
            entity_id = log["entity_id"]
            user = log["performed_by"]
            details = log["details"]

            # Construct human-readable summary
            summary = f"{user} performed {action} on {entity}"
            if entity_id:
                summary += f" #{entity_id}"

            if details:
                if "name" in details:
                    summary += f" ('{details['name']}')"
                elif "title" in details:
                    summary += f" ('{details['title']}')"
                elif "candidate_name" in details:
                    summary += f" ('{details['candidate_name']}')"
                elif "new_status" in details:
                    summary += f" [Status: {details['new_status']}]"

            feed.append({
                "id": log["id"],
                "icon": log["icon"],
                "summary": summary,
                "action": action,
                "entity": entity,
                "entity_id": entity_id,
                "user": user,
                "timestamp": log["performed_at"],
                "time_ago": log["time_ago"],
                "details": details,
            })

        return feed

    def get_screening_history(
        self, jd_id: Optional[int] = None, offset: int = 0, limit: int = 50
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Fetch historical screening batches with aggregates and execution statistics.

        Args:
            jd_id: Optional Job Description ID filter.
            offset: Record offset for pagination.
            limit: Page size.

        Returns:
            Tuple of (list of screening batch dictionaries, total batch count).
        """
        with get_session() as session:
            stmt = (
                select(ScreeningBatch)
                .options(
                    selectinload(ScreeningBatch.runs)
                    .selectinload(ScreeningRun.candidate_matches)
                    .joinedload(CandidateMatch.job_description)
                )
            )

            if jd_id is not None:
                # Filter batches that evaluated this JD
                stmt = stmt.join(ScreeningBatch.runs).where(ScreeningRun.jd_id == jd_id)

            count_stmt = select(func.count(ScreeningBatch.id.distinct()))
            if jd_id is not None:
                count_stmt = count_stmt.select_from(ScreeningBatch).join(ScreeningBatch.runs).where(ScreeningRun.jd_id == jd_id)
            else:
                count_stmt = count_stmt.select_from(ScreeningBatch)

            total_count = session.scalar(count_stmt) or 0

            stmt = stmt.distinct().order_by(ScreeningBatch.created_at.desc()).offset(offset).limit(limit)
            batches = session.scalars(stmt).unique().all()

            results = []
            for b in batches:
                runs = b.runs
                matches: List[CandidateMatch] = []
                jd_titles_set = set()

                for r in runs:
                    for m in r.candidate_matches:
                        matches.append(m)
                        if m.job_description and m.job_description.title:
                            jd_titles_set.add(m.job_description.title)

                scores = [float(m.match_score) for m in matches if m.match_score is not None]
                avg_score = (sum(scores) / len(scores)) if scores else 0.0

                strong_matches = sum(1 for s in scores if s >= 80.0)
                potential_matches = sum(1 for s in scores if 60.0 <= s < 80.0)
                review_matches = sum(1 for s in scores if s < 60.0)

                results.append({
                    "id": b.id,
                    "name": b.name,
                    "description": b.description or "Automated screening run",
                    "status": b.status,
                    "matching_method": b.matching_method or "Hybrid",
                    "candidate_count": b.candidate_count if b.candidate_count > 0 else len(runs),
                    "run_count": len(runs),
                    "match_count": len(matches),
                    "average_score": round(avg_score, 1),
                    "strong_matches": strong_matches,
                    "potential_matches": potential_matches,
                    "review_matches": review_matches,
                    "jd_titles": sorted(list(jd_titles_set)),
                    "created_at": b.created_at.strftime("%Y-%m-%d %H:%M") if b.created_at else None,
                    "completed_at": b.completed_at.strftime("%Y-%m-%d %H:%M") if b.completed_at else None,
                    "created_by": b.created_by or "Recruiter",
                })

            return results, total_count
