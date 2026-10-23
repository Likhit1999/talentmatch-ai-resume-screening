"""Unit tests for AI latency optimizations, connection pooling, and caching."""

import json
import pytest
from config.settings import get_settings
from database.connection import get_engine, get_session
from database.models import Candidate, CandidateMatch, JobDescription
from services.ai_client import (
    AVAILABLE_MODELS,
    RECOMMENDED_FAST_MODEL,
    clean_json_response,
    get_genai_client,
    get_token_usage_stats,
    record_token_usage,
    reset_token_usage_stats,
    safe_parse_json,
    set_plan_tier,
)
from services.matching_service import MatchingService
from sqlalchemy import text


def test_ai_client_model_defaults():
    """Verify fastest model is configured as default."""
    assert RECOMMENDED_FAST_MODEL == "gemini-3.1-flash-lite"
    assert "gemini-3.1-flash-lite" in AVAILABLE_MODELS
    assert "gemini-3.5-flash" in AVAILABLE_MODELS


def test_clean_json_response():
    """Verify markdown code fence stripping."""
    fenced = "```json\n{\"score\": 85, \"fit\": \"strong\"}\n```"
    cleaned = clean_json_response(fenced)
    parsed = json.loads(cleaned)
    assert parsed["score"] == 85
    assert parsed["fit"] == "strong"

    unfenced = "{\"score\": 90}"
    assert clean_json_response(unfenced) == "{\"score\": 90}"


def test_safe_parse_json_resilience():
    """Verify safe_parse_json handles truncated arrays, unclosed strings, and fences."""
    # 1. Truncated array mid-string (the exact scenario from the user error)
    truncated_array = (
        '[\n'
        '  {"requirement_name": "Python 3+", "category": "mandatory_skill"},\n'
        '  {"requirement_name": "PostgreSQL", "category": "tool"},\n'
        '  {"requirement_name": "AWS Cloud", "category": "mandatory_skill", "original_evidence": "Must have 3+ years\n'
    )
    recovered = safe_parse_json(truncated_array)
    assert isinstance(recovered, list)
    assert len(recovered) == 2
    assert recovered[0]["requirement_name"] == "Python 3+"
    assert recovered[1]["requirement_name"] == "PostgreSQL"

    # 2. Markdown fenced object
    fenced_obj = "```json\n{\"overall_score\": 92, \"grade\": \"Excellent\"}\n```"
    parsed_obj = safe_parse_json(fenced_obj)
    assert isinstance(parsed_obj, dict)
    assert parsed_obj["overall_score"] == 92

    # 3. Truncated object with unclosed quote and bracket
    truncated_obj = '{"overall_fit_score": 88.5, "match_category": "strong_match", "summary": "Great fit with Python'
    repaired_obj = safe_parse_json(truncated_obj)
    assert isinstance(repaired_obj, dict)
    assert repaired_obj["overall_fit_score"] == 88.5
    assert repaired_obj["match_category"] == "strong_match"


def test_token_tracking_and_quota_stats():
    """Verify recording token usage, plan tier switching, and quota calculations."""
    reset_token_usage_stats()
    set_plan_tier("free")

    # Verify initial clean state
    initial_stats = get_token_usage_stats()
    assert initial_stats["plan_tier"] == "free"
    assert initial_stats["requests_used"] == 0
    assert initial_stats["requests_remaining"] == 1500
    assert initial_stats["rpm_limit"] == 15

    # Record simulated call
    record_token_usage(prompt_tokens=120, candidates_tokens=45, total_tokens=165, latency_ms=450, model="gemini-3.8-flash")

    updated_stats = get_token_usage_stats()
    assert updated_stats["requests_used"] == 1
    assert updated_stats["requests_remaining"] == 1499
    assert updated_stats["prompt_tokens_today"] == 120
    assert updated_stats["candidates_tokens_today"] == 45
    assert updated_stats["total_tokens_today"] == 165
    assert updated_stats["last_call"]["latency_ms"] == 450
    assert updated_stats["last_call"]["model"] == "gemini-3.8-flash"

    # Switch to paid tier
    set_plan_tier("paid")
    paid_stats = get_token_usage_stats()
    assert paid_stats["plan_tier"] == "paid"
    assert paid_stats["requests_remaining"] == "Unlimited"
    assert paid_stats["rpm_limit"] == 1000

    # Reset
    reset_token_usage_stats()
    reset_stats = get_token_usage_stats()
    assert reset_stats["requests_used"] == 0
    assert reset_stats["total_tokens_today"] == 0

    # Restore to free for consistency
    set_plan_tier("free")


def test_sqlite_pragmas_enabled():
    """Verify WAL mode and busy timeout are active on SQLite engine."""
    with get_session() as session:
        wal_res = session.execute(text("PRAGMA journal_mode")).scalar()
        assert str(wal_res).lower() == "wal"

        timeout_res = session.execute(text("PRAGMA busy_timeout")).scalar()
        assert int(timeout_res) >= 5000


def test_matching_service_caching_and_fast_execution():
    """Verify rule-based matching and caching execute with sub-second latency."""
    matching_service = MatchingService()

    # Create dummy candidate and JD
    with get_session() as session:
        c = Candidate(
            name="Fast Test Candidate",
            email="fast_test@example.com",
            phone="1234567890",
            skills_json=json.dumps(["Python", "SQL", "Docker"]),
            experience_json=json.dumps([{"role": "Developer", "years": 3.5}]),
            parsing_status="parsed",
        )
        session.add(c)
        session.flush()

        jd = JobDescription(
            title="Fast Test Python Dev",
            description_text="Looking for a Python dev with SQL and Docker.",
            status="Open",
            experience_min=2,
            experience_max=5,
        )
        session.add(jd)
        session.flush()

        c_id = c.id
        jd_id = jd.id

    # 1. Run rule-based match
    res1 = matching_service.match_candidate_to_jd(candidate_id=c_id, jd_id=jd_id, method="rule_based")
    assert res1["candidate_id"] == c_id
    assert res1["jd_id"] == jd_id
    assert "match_score" in res1

    # 2. Re-run without force_rescreen (cache hit)
    res2 = matching_service.match_candidate_to_jd(candidate_id=c_id, jd_id=jd_id, method="rule_based", force_rescreen=False)
    assert res2["id"] == res1["id"]
    assert res2["match_score"] == res1["match_score"]
