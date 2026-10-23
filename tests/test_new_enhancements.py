"""Automated tests for new platform enhancements:
1. ZIP bulk archive resume extraction and processing.
2. Batch-wise role categorization (e.g. QA profiles).
3. JD workflow status transitions (Open, In Progress, On Hold, Closed, Draft).
4. JD screening summary reporting at the requisition level.
5. Email outreach template formatting.
"""

import io
import zipfile
import pytest

from database.connection import init_db
from database.models import Candidate, JobDescription
from services.candidate_service import CandidateService
from services.email_service import EmailService
from services.jd_service import JDService, VALID_JD_STATUSES
from services.resume_parser import ResumeParserService


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    init_db()


def test_zip_resume_extraction():
    """Verify that a ZIP archive containing multiple resume files can be extracted."""
    parser = ResumeParserService()

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("alice_qa.txt", "Alice Doe\nQA Automation Engineer\nalice@example.com\nSkills: Selenium, Cypress, Python, Pytest")
        z.writestr("bob_qa.txt", "Bob Vance\nSenior SDET\nbob@example.com\nSkills: Java, TestNG, Appium, REST Assured")
        z.writestr("notes.ignore.csv", "id,note\n1,skip this file")

    zip_bytes = zip_buffer.getvalue()
    files, warnings = parser.extract_from_zip(zip_bytes, "qa_resumes.zip")

    assert len(files) == 2
    filenames = [f["filename"] for f in files]
    assert "alice_qa.txt" in filenames
    assert "bob_qa.txt" in filenames
    assert any("notes.ignore.csv" in w for w in warnings)


def test_candidate_service_zip_upload_and_role_tag():
    """Verify processing a ZIP upload and tagging profiles with a target role category."""
    import uuid
    service = CandidateService()
    test_token = uuid.uuid4().hex[:6]

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            f"charlie_{test_token}.txt",
            f"Charlie Brown\nQA Engineer\ncharlie.{test_token}@example.com\nSkills: Playwright, Cucumber, Python"
        )
        z.writestr(
            f"diana_{test_token}.txt",
            f"Diana Prince\nQA Lead\ndiana.{test_token}@example.com\nSkills: Selenium, Postman, JIRA, Agile"
        )

    zip_bytes = zip_buffer.getvalue()
    outcome = service.process_zip_upload(
        zip_bytes=zip_bytes,
        zip_filename=f"qa_batch_{test_token}.zip",
        job_category="QA Engineer / Automation",
    )

    created_ids = []
    try:
        assert outcome["total"] == 2
        assert outcome["success_count"] == 2
        for r in outcome["results"]:
            if r.get("candidate_id"):
                created_ids.append(r["candidate_id"])

        cands, _ = service.get_candidates(job_category="QA Engineer")
        cand_ids = [c["id"] for c in cands]
        assert any(cid in cand_ids for cid in created_ids)
        for c in cands:
            if c["id"] in created_ids:
                assert c["name"] in ("Charlie Brown", "Diana Prince")
                assert c["job_category"] == "QA Engineer / Automation"
                # Unmasked contact details check
                assert c["email"] is not None and "@" in c["email"]
    finally:
        for cid in created_ids:
            service.delete_candidate(cid)


def test_jd_workflow_statuses():
    """Verify full lifecycle of JD workflow statuses."""
    service = JDService()

    created = service.create_jd({
        "title": "Lead QA Automation Engineer",
        "description_text": "Looking for a Lead QA engineer with 5+ years experience in Python and Selenium.",
        "status": "Open",
    })

    assert created.status in ("Open", "Active")

    # Update to In Progress
    updated = service.update_status(created.id, "In Progress")
    assert updated.status == "In Progress"

    # Update to On Hold
    updated2 = service.update_status(created.id, "On Hold")
    assert updated2.status == "On Hold"

    # Update to Closed
    updated3 = service.update_status(created.id, "Closed")
    assert updated3.status == "Closed"

    # Update to Draft
    updated4 = service.update_status(created.id, "Draft")
    assert updated4.status == "Draft"

    # Invalid status should raise ValueError
    with pytest.raises(ValueError):
        service.update_status(created.id, "InvalidStatusXYZ")


def test_jd_screening_summary():
    """Verify requisition-level candidate screening summary."""
    service = JDService()
    summary = service.get_jd_screening_summary(1)

    assert "total_screened" in summary
    assert "by_category" in summary
    assert "by_review_status" in summary
    assert "candidates" in summary
    assert isinstance(summary["candidates"], list)


def test_email_template_no_duplicate_regards():
    """Verify inquiry template has subject without 'at Our Team', requested details, and exactly one 'Best regards'."""
    email_service = EmailService()
    tpl = email_service.generate_candidate_inquiry_template(
        candidate_name="John Doe",
        job_title="Software Engineer",
        recruiter_name="Talent Acquisition Team",
    )

    # Subject check
    assert "at Our Team" not in tpl["subject"]
    assert tpl["subject"] == "Next Steps - Application for Software Engineer"

    # Body checks
    body = tpl["body"]
    assert body.count("Best regards,") == 1
    assert "Dear John Doe," in body
    assert "Name: John Doe" in body
    assert "Current Company:" in body
    assert "Total Experience:" in body
    assert "Relevant Experience:" in body
    assert "Current salary package:" in body
    assert "Expected salary package:" in body
    assert "Notice period:" in body
    assert "Current Location:" in body
    assert "Reason for job change:" in body
    assert "Any offers in hand?:" in body
    assert "Highest education & year:" in body


def test_database_danger_zone_purge():
    """Verify DatabaseManager.clear_candidate_and_screening_data safely purges data."""
    from database.connection import DatabaseManager
    db_mgr = DatabaseManager()
    outcome = db_mgr.clear_candidate_and_screening_data()
    assert "candidates_deleted" in outcome
    assert "resumes_deleted" in outcome
    assert "matches_deleted" in outcome
    assert "shortlists_deleted" in outcome


def test_atomic_experience_requirement_evaluation_and_deficit_flagging():
    """Verify that a candidate with 1.5 yrs experience correctly fails a 4-5 yrs requirement."""
    from services.scoring_service import ScoringService, parse_experience_range_from_text

    scorer = ScoringService()

    # 1. Verify parsing
    req_name = "4-5 Years Software/QA Experience"
    p_min, p_max = parse_experience_range_from_text(req_name)
    assert p_min == 4.0
    assert p_max == 5.0

    # 2. Evaluate candidate with 1.5 years experience
    cand_exp = [{"duration": "1.5 years", "title": "QA Tester"}]
    score, msg = scorer.calculate_experience_score(
        candidate_experience=cand_exp,
        required_min=p_min,
        required_max=p_max,
        resume_text="1.5 years of QA testing experience.",
    )

    # 3. Must NOT say '(no minimum requirement specified)'
    assert "(no minimum requirement specified)" not in msg
    assert "Below required minimum (4-5 yrs)" in msg
    assert score < 50.0  # ~37.5%
    assert score == 37.5

    # 4. Status determination must be 'not_found' (fails requirement, not matched!)
    status = "matched" if score >= 80 else ("partial" if score >= 50 else "not_found")
    assert status == "not_found"


def test_domain_and_responsibility_matching():
    """Verify that descriptive domain knowledge and responsibilities match conceptually and semantically."""
    from services.matching_service import MatchingService

    ms = MatchingService()

    cand_skills = ["Postman", "Selenium", "SQL", "Pentaho Data Integration"]
    resume_text = (
        "Experienced in data governance, retention and compliance platforms. "
        "Ensured quality across data management modules, ETL and data warehousing through Pentaho. "
        "Created comprehensive automated test plans, regression suites, and test cases. "
        "Developed automated validation components for data integrity checks. "
        "Conducted API testing using Postman to validate request/response payloads and endpoints."
    )

    # 1. Acronym and conceptual cluster domain matching (MDM)
    res_mdm = ms.match_domain_or_responsibility(
        candidate_skills=cand_skills,
        requirement_name="Master Data Management (MDM) Testing Experience",
        normalized_value="master_data_management",
        resume_text=resume_text,
    )
    assert res_mdm["status"] == "matched"
    assert "data governance" in res_mdm["evidence"].lower() or "data management" in res_mdm["evidence"].lower()

    # 2. Responsibility test plan matching
    res_plans = ms.match_domain_or_responsibility(
        candidate_skills=cand_skills,
        requirement_name="Design Automated Test Plans for Data Pipelines",
        normalized_value="design_automated_test_plans",
        resume_text=resume_text,
    )
    assert res_plans["status"] == "matched"

    # 3. Responsibility test script validation matching
    res_scripts = ms.match_domain_or_responsibility(
        candidate_skills=cand_skills,
        requirement_name="Develop Automated Test Scripts for Data Validation",
        normalized_value="develop_automated_test_scripts",
        resume_text=resume_text,
    )
    assert res_scripts["status"] == "matched"

    # 4. Responsibility API endpoints matching
    res_api = ms.match_domain_or_responsibility(
        candidate_skills=cand_skills,
        requirement_name="Validate API Endpoints and Downstream Data",
        normalized_value="validate_api_endpoints",
        resume_text=resume_text,
    )
    assert res_api["status"] == "matched"
    assert "postman" in res_api["evidence"].lower() or "api" in res_api["evidence"].lower()


