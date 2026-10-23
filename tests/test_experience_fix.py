import json
import pytest
from services.resume_parser import ResumeParserService
from services.scoring_service import ScoringService, parse_experience_range_from_text


def test_candidate_with_4_years_meets_4_year_requirement():
    """Verify candidate with 4.0+ years experience passes 4.0 yr minimum requirement."""
    scorer = ScoringService()
    req_name = "4.0+ Years Professional Experience"
    p_min, p_max = parse_experience_range_from_text(req_name)
    assert p_min == 4.0

    # 1. Candidate with 4 years stated in resume text
    cand_exp = [{"title": "QA Engineer", "duration": "Aug 2024 - Jan 2025"}]
    resume_text = (
        "Senior QA Engineer with 4.0+ Years Professional Experience in manual and automated testing.\n"
        "Lead QA Engineer at FYI Software (Aug 2024 - Jan 2025)"
    )
    score, msg = scorer.calculate_experience_score(
        candidate_experience=cand_exp,
        required_min=p_min,
        required_max=p_max,
        resume_text=resume_text,
    )
    assert score == 100.0
    assert "Meets required minimum (4 yrs)" in msg
    assert "4.0 yrs" in msg


def test_candidate_with_10_years_and_single_parsed_role():
    """Verify that a 10+ year veteran is not misclassified as 1.0 yr just because only 1 role was in JSON."""
    scorer = ScoringService()
    cand_exp = [{"title": "Lead QA Engineer", "company": "FYI Software", "duration": "Aug 2024 - Jan 2025"}]
    resume_text = (
        "KOPILA PARIYAR\n"
        "10+ Years QA Lead | Manual & Automated Testing\n"
        "PROFESSIONAL SUMMARY\n"
        "Senior QA Engineer with 10+ years of hands-on manual and automation testing experience.\n"
        "Aug 2024 - Jan 2025: Lead QA Engineer at FYI Software\n"
        "Sep 2022 - Aug 2024: Lead QA Engineer at Moolya Technologies\n"
        "May 2020 - Sep 2022: QA Engineer at BlockFi\n"
        "May 2018 - May 2020: SDET at Flipkart\n"
        "Jun 2016 - May 2018: QA Engineer at Amazon"
    )
    score, msg = scorer.calculate_experience_score(
        candidate_experience=cand_exp,
        required_min=4.0,
        resume_text=resume_text,
    )
    assert score == 100.0
    assert "Meets required minimum (4 yrs)" in msg
    assert "10.0 yrs" in msg


def test_parser_extracts_continuous_work_history_without_blank_lines():
    """Verify parser extracts multiple roles even if text has no double newlines between jobs."""
    parser = ResumeParserService()
    sample_text = (
        "PROFESSIONAL EXPERIENCE\n"
        "Lead QA Engineer\n"
        "FYI Software . Full-time\n"
        "Aug 2024 - Jan 2025\n"
        "Led QA validation for Android product lines.\n"
        "Lead Software Quality Assurance Engineer\n"
        "Moolya Technologies . Full-time\n"
        "Sep 2022 - Aug 2024\n"
        "Managed full QA lifecycle.\n"
        "Senior Software Engineer-QA\n"
        "BlockFi . Full-time\n"
        "May 2020 - Sep 2022\n"
        "Fintech transaction validation."
    )
    info = parser.extract_candidate_info(sample_text)
    assert len(info["experience"]) == 3
    assert info["experience"][0]["title"] == "Lead QA Engineer"
    assert info["experience"][1]["title"] == "Lead Software Quality Assurance Engineer"
    assert info["experience"][2]["title"] == "Senior Software Engineer-QA"


def test_parser_recovers_misplaced_experience_from_education():
    """Verify that jobs appearing after education in multi-column PDF layouts are not lost."""
    parser = ResumeParserService()
    sample_text = (
        "PROFESSIONAL EXPERIENCE\n"
        "Lead QA Engineer\n"
        "FYI Software\n"
        "Aug 2024 - Jan 2025\n"
        "EDUCATION\n"
        "B.E. - Computer Science\n"
        "Saveetha University\n"
        "2012-2015\n"
        "Senior Software Development Engineer in Test (SDET)\n"
        "Flipkart . Full-time\n"
        "May 2018 - May 2020\n"
        "Quality Assurance Engineer\n"
        "Amazon . Full-time\n"
        "Jun 2016 - May 2018"
    )
    info = parser.extract_candidate_info(sample_text)
    # Should extract B.E. in education
    assert len(info["education"]) >= 1
    assert any("B.E" in e.get("degree", "") for e in info["education"])

    # Should recover Flipkart and Amazon as experience
    exp_companies = [e.get("company", "") for e in info["experience"]]
    assert any("Flipkart" in c for c in exp_companies)
    assert any("Amazon" in c for c in exp_companies)


def test_candidate_truly_under_experience_correctly_flags_deficit():
    """Verify that a candidate who actually has 1.0 yr experience is still accurately flagged."""
    scorer = ScoringService()
    cand_exp = [{"title": "Junior QA", "duration": "Jan 2024 - Dec 2024"}]
    resume_text = "Junior QA with 1 year experience in manual testing."
    score, msg = scorer.calculate_experience_score(
        candidate_experience=cand_exp,
        required_min=4.0,
        resume_text=resume_text,
    )
    assert score == 25.0
    assert "Below required minimum (4 yrs): candidate has ~1.0 yrs (25% of requirement)." in msg


def test_dict_experience_with_years_field():
    """Verify that candidate experience dictionaries with 'years' fields are properly aggregated."""
    scorer = ScoringService()
    cand_exp = [
        {"role": "Senior Developer", "years": 2.5},
        {"role": "Lead Architect", "years": 2.0},
    ]
    score, msg = scorer.calculate_experience_score(
        candidate_experience=cand_exp,
        required_min=4.0,
    )
    assert score == 100.0
    assert "Meets required minimum (4 yrs)" in msg
    assert "4.5 yrs" in msg

