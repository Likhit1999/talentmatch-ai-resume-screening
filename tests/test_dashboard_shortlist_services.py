"""Unit and integration tests for export, shortlist, audit services, and UI modules."""

import json
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import (
    ApplicationSetting,
    AuditLog,
    Base,
    Candidate,
    CandidateMatch,
    JobDescription,
    ScreeningBatch,
    ScreeningRun,
    Shortlist,
    ShortlistCandidate,
)
from services.audit_service import AuditService
from services.export_service import ExportService
from services.shortlist_service import ShortlistService
from ui.dashboard import render_dashboard
from ui.history import render_screening_history
from ui.settings import render_settings
from ui.shortlist import render_shortlist


def test_ui_callables():
    """Verify UI render functions are imported and callable."""
    assert callable(render_dashboard)
    assert callable(render_shortlist)
    assert callable(render_screening_history)
    assert callable(render_settings)


def test_export_matches_to_excel_and_csv(tmp_path, monkeypatch):
    """Test exporting matches to Excel and CSV."""
    service = ExportService()
    monkeypatch.setattr(service, "exports_dir", tmp_path)

    sample_matches = [
        {
            "candidate_name": "Alice Johnson",
            "jd_title": "Senior Python Developer",
            "match_score": 88.5,
            "match_category": "strong_match",
            "mandatory_met": 4,
            "mandatory_total": 4,
            "mandatory_missing": [],
            "preferred_met": 2,
            "preferred_total": 3,
            "experience_score": 90.0,
            "qualification_score": 85.0,
            "human_review_status": "pending",
            "reviewer_notes": "Strong candidate",
            "screening_date": "2026-10-19 10:00:00",
            "matching_method": "Hybrid",
        },
        {
            "candidate_name": "Bob Smith",
            "jd_title": "Senior Python Developer",
            "match_score": 52.0,
            "match_category": "needs_review",
            "mandatory_met": 2,
            "mandatory_total": 4,
            "mandatory_missing": ["Docker", "Kubernetes"],
            "preferred_met": 1,
            "preferred_total": 3,
            "experience_score": 55.0,
            "qualification_score": 70.0,
            "human_review_status": "reviewed",
            "reviewer_notes": "Lacks cloud deployment skills",
            "screening_date": "2026-10-19 10:05:00",
            "matching_method": "Hybrid",
        },
    ]

    # Excel export
    excel_path = service.export_matches_to_excel(sample_matches, jd_title="Senior Python Developer")
    assert Path(excel_path).exists()
    assert Path(excel_path).suffix == ".xlsx"

    # CSV export
    csv_path = service.export_matches_to_csv(sample_matches, jd_title="Senior Python Developer")
    assert Path(csv_path).exists()
    assert Path(csv_path).suffix == ".csv"
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        content = f.read()
        assert "Alice Johnson" in content
        assert "Senior Python Developer" in content
        assert "88.5" in content


def test_export_shortlist_to_excel(tmp_path, monkeypatch):
    """Test exporting shortlist data to Excel."""
    service = ExportService()
    monkeypatch.setattr(service, "exports_dir", tmp_path)

    shortlist_payload = {
        "id": 1,
        "name": "Backend Tier 1",
        "jd_title": "Python Lead",
        "status": "active",
        "description": "High-priority candidates",
        "created_at": "2026-10-19 09:30:00",
        "candidates": [
            {
                "candidate_id": 101,
                "candidate_name": "Alice Johnson",
                "email": "alice@example.com",
                "phone": "+1-555-0101",
                "match_score": 92.0,
                "match_category": "strong_match",
                "status": "shortlisted",
                "recruiter_notes": "Great experience in fast-growth SaaS",
                "added_at": "2026-10-19 10:00:00",
            }
        ],
    }

    excel_path = service.export_shortlist_to_excel(shortlist_payload)
    assert Path(excel_path).exists()
    assert Path(excel_path).suffix == ".xlsx"


def test_shortlist_service_and_audit_service(tmp_path, monkeypatch):
    """Integration test for ShortlistService and AuditService with database transactions."""
    from database.connection import get_session

    audit_svc = AuditService()
    shortlist_svc = ShortlistService()

    # 1. Log an action and verify
    audit_svc.log_action("TestEntity", 999, "create", {"foo": "bar"}, performed_by="Tester")
    logs, count = audit_svc.get_audit_log(entity_type="TestEntity", limit=5)
    assert count >= 1
    assert any(l["entity_id"] == 999 for l in logs)

    # Recent activity
    recent = audit_svc.get_recent_activity(limit=5)
    assert len(recent) > 0

    # 2. Setup a test JD and Candidate in DB
    with get_session() as session:
        jd = JobDescription(
            title="Test Automation Architect",
            description_text="Leading QA automation architecture.",
            status="Active",
        )
        session.add(jd)
        cand = Candidate(
            name="Charlie QA",
            email="charlie@example.com",
            skills_json=json.dumps(["Selenium", "Pytest", "Python"]),
            parsing_status="parsed",
        )
        session.add(cand)
        session.flush()
        jd_id = jd.id
        cand_id = cand.id

    # 3. Create shortlist
    sl_created = shortlist_svc.create_shortlist(
        name="QA Leads", jd_id=jd_id, description="Automation specialists"
    )
    sl_id = sl_created["id"]
    assert sl_id is not None
    assert sl_created["name"] == "QA Leads"

    # 4. Add candidate to shortlist
    entry = shortlist_svc.add_candidate(sl_id, cand_id, notes="Top test specialist")
    assert entry["candidate_id"] == cand_id

    # 5. Update candidate status
    updated = shortlist_svc.update_candidate_status(sl_id, cand_id, "interview_scheduled", "Cleared initial screen")
    assert updated["status"] == "interview_scheduled"

    # 6. Retrieve shortlist and stats
    fetched = shortlist_svc.get_shortlist(sl_id)
    assert len(fetched["candidates"]) == 1
    assert fetched["candidates"][0]["status"] == "interview_scheduled"

    stats = shortlist_svc.get_shortlist_stats(sl_id)
    assert stats["total_candidates"] == 1
    assert stats["by_status"]["interview_scheduled"] == 1

    # 7. Export shortlist
    monkeypatch.setattr(shortlist_svc.export_service, "exports_dir", tmp_path)
    csv_exp = shortlist_svc.export_shortlist(sl_id, format="csv")
    assert Path(csv_exp).exists()
    assert Path(csv_exp).suffix == ".csv"

    # 8. Archive shortlist
    archived = shortlist_svc.archive_shortlist(sl_id)
    assert archived["status"] == "archived"

    # 9. Remove candidate
    removed = shortlist_svc.remove_candidate(sl_id, cand_id)
    assert removed is True
    assert len(shortlist_svc.get_shortlist(sl_id)["candidates"]) == 0


def test_audit_log_pyarrow_compatibility():
    """Verify audit log table with mixed entity_id (integers and None) converts to PyArrow without error."""
    import pandas as pd
    import pyarrow as pa

    # Simulate logs where some items have entity_id as integer and others as None
    simulated_logs = [
        {"id": 1, "performed_at": "2026-10-20 12:00:00", "performed_by": "Recruiter", "entity_type": "Candidate", "entity_id": 42, "action": "create", "details": {"info": "test"}},
        {"id": 2, "performed_at": "2026-10-20 12:01:00", "performed_by": "Recruiter", "entity_type": "Export", "entity_id": None, "action": "export", "details": {"type": "all"}},
    ]

    log_table = []
    for item in simulated_logs:
        details_preview = str(item["details"])[:60] + "..." if len(str(item["details"])) > 60 else str(item["details"])
        entity_id_display = str(item["entity_id"]) if item.get("entity_id") is not None else "—"
        log_table.append({
            "ID": item["id"],
            "Timestamp": item["performed_at"],
            "User": item.get("performed_by") or "System",
            "Entity": item["entity_type"],
            "Entity ID": entity_id_display,
            "Action": item["action"].upper(),
            "Details Preview": details_preview,
        })

    df = pd.DataFrame(log_table)
    # PyArrow Table conversion is what Streamlit st.dataframe runs internally
    pa_table = pa.Table.from_pandas(df)
    assert pa_table.num_rows == 2
    assert "Entity ID" in pa_table.column_names

