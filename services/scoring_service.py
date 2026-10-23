"""Scoring engine and assessment calculation service for TalentMatch AI.

Provides transparent, configurable scoring across mandatory skills, experience,
preferred skills, domain responsibilities, and qualifications/certifications.
Supports custom weighting, auto-normalization, and multi-tier match categorization.
"""

from datetime import datetime
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

MONTH_MAP: Dict[str, int] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Default scoring weights (percentages summing to 100.0)
DEFAULT_SCORING_WEIGHTS: Dict[str, float] = {
    "mandatory_skills": 50.0,
    "experience": 20.0,
    "preferred_skills": 15.0,
    "domain_responsibilities": 10.0,
    "qualifications_certifications": 5.0,
}

# Match category thresholds and definitions
MATCH_CATEGORIES = {
    "strong_match": "Strong Match",
    "potential_match": "Potential Match",
    "needs_review": "Needs Review",
    "insufficient_evidence": "Insufficient Evidence",
}

# Educational degree hierarchy mapping
DEGREE_LEVELS = {
    "doctorate": 4,
    "phd": 4,
    "ph.d": 4,
    "master": 3,
    "m.tech": 3,
    "mtech": 3,
    "m.s": 3,
    "ms": 3,
    "msc": 3,
    "m.sc": 3,
    "mca": 3,
    "mba": 3,
    "m.e": 3,
    "me": 3,
    "bachelor": 2,
    "b.tech": 2,
    "btech": 2,
    "b.e": 2,
    "be": 2,
    "b.s": 2,
    "bs": 2,
    "bsc": 2,
    "b.sc": 2,
    "bca": 2,
    "bba": 2,
    "b.com": 2,
    "associate": 1,
    "diploma": 1,
}


def parse_experience_range_from_text(text: str) -> Tuple[Optional[float], Optional[float]]:
    """Extract minimum and maximum years of experience from requirement or JD text.

    Examples:
        '4-5 Years Software/QA Experience' -> (4.0, 5.0)
        '4 to 5 years' -> (4.0, 5.0)
        '5+ years Software Engineering' -> (5.0, None)
        'Minimum 3 years in React' -> (3.0, None)
        'At least 7 yrs experience' -> (7.0, None)
        '3 years experience' -> (3.0, None)

    Args:
        text: Raw requirement string or description excerpt.

    Returns:
        Tuple of (min_years, max_years) or (None, None) if no duration is found.
    """
    if not text:
        return None, None

    # Pattern 1: Hyphenated or 'to' range: '4-5 years', '4 to 5 years', '4 - 5 yrs'
    range_match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*(?:\+)?\s*(?:years?|yrs?)",
        text,
        re.IGNORECASE,
    )
    if range_match:
        try:
            return float(range_match.group(1)), float(range_match.group(2))
        except ValueError:
            pass

    # Pattern 2: '5+ years', 'minimum 5 years', 'at least 5 years', '5 years of'
    min_match = re.search(
        r"(?:min(?:imum)?|at\s+least)?\s*(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)",
        text,
        re.IGNORECASE,
    )
    if min_match:
        try:
            return float(min_match.group(1)), None
        except ValueError:
            pass

    return None, None


class ScoringService:
    """Configurable scoring engine for candidate-job requirement evaluations."""

    def __init__(self, default_weights: Optional[Dict[str, float]] = None) -> None:
        """Initialize scoring service with default or custom weight configurations."""
        self.default_weights = (
            self.validate_weights(default_weights)
            if default_weights
            else dict(DEFAULT_SCORING_WEIGHTS)
        )

    @staticmethod
    def get_default_weights() -> Dict[str, float]:
        """Return a copy of the system default scoring weights.

        Returns:
            Dict[str, float]: Default weights dictionary summing to 100.0.
        """
        return dict(DEFAULT_SCORING_WEIGHTS)

    @staticmethod
    def validate_weights(weights: Optional[Dict[str, float]]) -> Dict[str, float]:
        """Validate and normalize weight configuration so sum equals 100.0%.

        Args:
            weights: Dictionary of category weights.

        Returns:
            Dict[str, float]: Normalized weights summing to 100.0.
        """
        if not weights:
            return dict(DEFAULT_SCORING_WEIGHTS)

        sanitized: Dict[str, float] = {}
        for key in DEFAULT_SCORING_WEIGHTS.keys():
            val = weights.get(key, DEFAULT_SCORING_WEIGHTS[key])
            try:
                num = float(val)
                sanitized[key] = max(0.0, num)
            except (ValueError, TypeError):
                sanitized[key] = DEFAULT_SCORING_WEIGHTS[key]

        total = sum(sanitized.values())
        if total <= 0:
            return dict(DEFAULT_SCORING_WEIGHTS)

        # Scale weights to sum exactly to 100.0
        normalized = {k: round((v / total) * 100.0, 2) for k, v in sanitized.items()}
        # Correct floating point rounding discrepancy on the largest component
        diff = 100.0 - sum(normalized.values())
        if abs(diff) > 0.001:
            max_key = max(normalized, key=normalized.get)  # type: ignore[arg-type]
            normalized[max_key] = round(normalized[max_key] + diff, 2)

        return normalized

    @staticmethod
    def categorize_match(score: float, mandatory_met: int, mandatory_total: int) -> str:
        """Categorize match into strong_match, potential_match, needs_review, or insufficient_evidence.

        Rules:
        - strong_match: score >= 70 AND all mandatory requirements met
        - potential_match: score >= 50 OR most mandatory requirements met (>= 60%)
        - needs_review: score >= 30 OR at least some evidence met
        - insufficient_evidence: score < 30 AND low evidence

        Args:
            score: Overall match score (0-100).
            mandatory_met: Count of mandatory requirements satisfied.
            mandatory_total: Total count of mandatory requirements in JD.

        Returns:
            str: One of 'strong_match', 'potential_match', 'needs_review', 'insufficient_evidence'.
        """
        all_mandatory_met = (mandatory_total == 0) or (mandatory_met >= mandatory_total)
        most_mandatory_met = (
            mandatory_total > 0 and (mandatory_met / mandatory_total) >= 0.60
        )

        if score >= 70.0 and all_mandatory_met:
            return "strong_match"
        elif score >= 50.0 or most_mandatory_met:
            return "potential_match"
        elif score >= 30.0 or mandatory_met > 0:
            return "needs_review"
        else:
            return "insufficient_evidence"

    def calculate_experience_score(
        self,
        candidate_experience: Any,
        required_min: Optional[float] = None,
        required_max: Optional[float] = None,
        resume_text: str = "",
    ) -> Tuple[float, str]:
        """Parse years from candidate experience and compare to required JD range.

        Args:
            candidate_experience: List of experience dicts, float, or raw string.
            required_min: Minimum years required by JD (or None).
            required_max: Maximum years required by JD (or None).
            resume_text: Full resume text for supplementary year extraction.

        Returns:
            Tuple[float, str]: (Experience score 0-100, human-readable justification).
        """
        years = self._extract_total_experience_years(candidate_experience, resume_text)

        # Case 1: No JD experience requirements set
        if (required_min is None or required_min <= 0) and (
            required_max is None or required_max <= 0
        ):
            if years > 0:
                return (
                    100.0,
                    f"Candidate has ~{years:.1f} years of experience (no minimum requirement specified).",
                )
            return (
                100.0,
                "No minimum experience requirement specified in Job Description.",
            )

        min_exp = float(required_min or 0.0)
        max_exp = float(required_max or 0.0) if required_max is not None else None

        # Case 2: Candidate has met or exceeded minimum experience
        if years >= min_exp:
            if max_exp and max_exp >= min_exp:
                if years <= max_exp:
                    return (
                        100.0,
                        f"Experience matches required range ({min_exp:.0f}-{max_exp:.0f} yrs): candidate has ~{years:.1f} yrs.",
                    )
                else:
                    over_diff = years - max_exp
                    if over_diff > 8.0:
                        score = 90.0  # slight overqualification note, still very strong
                        return (
                            score,
                            f"Exceeds required range ({min_exp:.0f}-{max_exp:.0f} yrs): candidate has ~{years:.1f} yrs (highly experienced).",
                        )
                    return (
                        100.0,
                        f"Exceeds required range ({min_exp:.0f}-{max_exp:.0f} yrs): candidate has ~{years:.1f} yrs.",
                    )
            return (
                100.0,
                f"Meets required minimum ({min_exp:.0f} yrs): candidate has ~{years:.1f} yrs.",
            )

        # Case 3: Candidate has less than minimum experience
        if min_exp > 0:
            ratio = max(0.0, min(1.0, years / min_exp))
            score = round(ratio * 100.0, 1)
            target_str = f"{min_exp:.0f}-{max_exp:.0f} yrs" if (max_exp and max_exp > min_exp) else f"{min_exp:.0f} yrs"
            return (
                score,
                f"Below required minimum ({target_str}): candidate has ~{years:.1f} yrs ({score:.0f}% of requirement).",
            )

        return (100.0, f"Candidate has ~{years:.1f} years of experience.")

    @staticmethod
    def _parse_date_token(token: str) -> Optional[float]:
        """Convert a date token (e.g. 'Aug 2024', '2024', 'Present') to a float year."""
        t = token.strip().lower()
        now = datetime.now()
        if t in ("present", "current", "now", "ongoing"):
            return float(now.year) + (now.month - 1) / 12.0

        m_month_yr = re.search(r"([a-z]{3})[a-z]*\.?\s*(\d{4})", t)
        if m_month_yr:
            mon = MONTH_MAP.get(m_month_yr.group(1), 1)
            yr = int(m_month_yr.group(2))
            return yr + (mon - 1) / 12.0

        m_yr = re.search(r"\b(19\d{2}|20\d{2})\b", t)
        if m_yr:
            return float(m_yr.group(1))
        return None

    @classmethod
    def _parse_duration_interval(cls, duration_str: str) -> Optional[Tuple[float, float]]:
        """Parse start and end year floats from duration text (e.g. 'Jan 2018 - Present')."""
        if not duration_str:
            return None

        pattern = re.compile(
            r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*)?(\b(?:19|20)\d{2}\b)\s*(?:-|–|—|to)\s*(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*)?(\b(?:19|20)\d{2}\b|present|current|now|ongoing)",
            re.IGNORECASE,
        )
        match = pattern.search(duration_str)
        if match:
            full_match = match.group(0)
            parts = re.split(r"[-–—]|to", full_match, maxsplit=1)
            if len(parts) == 2:
                s = cls._parse_date_token(parts[0])
                e = cls._parse_date_token(parts[1])
                if s is not None and e is not None and e >= s:
                    return (s, e)
        return None

    @classmethod
    def _extract_intervals_from_text(cls, text: str) -> List[Tuple[float, float]]:
        """Scan freeform text for non-education employment date intervals."""
        if not text:
            return []
        pattern = re.compile(
            r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*)?\b(?:19|20)\d{2}\b\s*(?:-|–|—|to)\s*(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*)?(?:\b(?:19|20)\d{2}\b|present|current|now|ongoing)",
            re.IGNORECASE,
        )
        intervals: List[Tuple[float, float]] = []
        edu_indicators = [
            "university", "college", "polytechnic", "bachelor", "b.e", "b.tech",
            "diploma", "cgpa", "degree", "master", "m.tech", "phd", "graduat",
        ]
        for m in pattern.finditer(text):
            start_pos = max(0, m.start() - 100)
            end_pos = min(len(text), m.end() + 100)
            surrounding = text[start_pos:end_pos].lower()
            if any(k in surrounding for k in edu_indicators):
                continue
            parts = re.split(r"[-–—]|to", m.group(0), maxsplit=1)
            if len(parts) == 2:
                s = cls._parse_date_token(parts[0])
                e = cls._parse_date_token(parts[1])
                if s is not None and e is not None and e >= s:
                    intervals.append((s, e))
        return intervals

    @staticmethod
    def _extract_explicit_experience_years(text: str) -> float:
        """Extract declared total years of experience from resume text and summaries."""
        if not text:
            return 0.0
        explicit_vals: List[float] = []

        # Pattern 1: 'X+ years of ... experience'
        p1 = re.finditer(
            r"\b(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)(?:\s+of)?(?:\s+(?:[a-zA-Z/&.-]+\s+){0,6})?experience\b",
            text,
            re.IGNORECASE,
        )
        for m in p1:
            try:
                v = float(m.group(1))
                if 0.5 <= v <= 45:
                    explicit_vals.append(v)
            except ValueError:
                pass

        # Pattern 2: 'Total Experience: X years' or 'Experience: X years'
        p2 = re.finditer(
            r"\b(?:total\s+)?experience\s*[:\-–]\s*(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)",
            text,
            re.IGNORECASE,
        )
        for m in p2:
            try:
                v = float(m.group(1))
                if 0.5 <= v <= 45:
                    explicit_vals.append(v)
            except ValueError:
                pass

        # Pattern 3: 'X+ years QA/developer/engineer/etc.'
        p3 = re.finditer(
            r"\b(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\s+(?:qa|lead|developer|engineer|software|sdet|it|testing|design|devops|data|consultant|frontend|backend|fullstack|full-stack)\b",
            text,
            re.IGNORECASE,
        )
        for m in p3:
            try:
                v = float(m.group(1))
                if 0.5 <= v <= 45:
                    explicit_vals.append(v)
            except ValueError:
                pass

        # Pattern 4: 'over X years of experience'
        p4 = re.finditer(
            r"\b(?:over|more\s+than)\s+(\d+(?:\.\d+)?)\s*(?:\+)?\s*(?:years?|yrs?)",
            text,
            re.IGNORECASE,
        )
        for m in p4:
            try:
                v = float(m.group(1))
                if 0.5 <= v <= 45:
                    explicit_vals.append(v)
            except ValueError:
                pass

        return max(explicit_vals) if explicit_vals else 0.0

    def _extract_total_experience_years(
        self, candidate_experience: Any, resume_text: str = ""
    ) -> float:
        """Helper to extract or estimate total years of experience from structured or unstructured data."""
        if isinstance(candidate_experience, (int, float)):
            return float(candidate_experience)

        structured_years = 0.0
        parsed_intervals: List[Tuple[float, float]] = []

        if isinstance(candidate_experience, list) and candidate_experience:
            for item in candidate_experience:
                if isinstance(item, (int, float)):
                    structured_years += float(item)
                elif isinstance(item, dict):
                    # Check for explicit year fields
                    for yk in ("years", "experience_years", "total_years"):
                        if item.get(yk) is not None:
                            try:
                                structured_years += float(item[yk])
                                break
                            except (ValueError, TypeError):
                                pass

                    duration_str = str(
                        item.get("duration", "") or item.get("period", "") or item.get("dates", "") or ""
                    )
                    interval = self._parse_duration_interval(duration_str)
                    if interval:
                        parsed_intervals.append(interval)
                    else:
                        years_match = re.search(
                            r"(\d+(?:\.\d+)?)\s*(?:\+)?\s*(?:years?|yrs?)",
                            duration_str,
                            re.IGNORECASE,
                        )
                        if years_match:
                            try:
                                structured_years += float(years_match.group(1))
                            except ValueError:
                                pass
                        months_match = re.search(
                            r"(\d+(?:\.\d+)?)\s*(?:months?|mos?)",
                            duration_str,
                            re.IGNORECASE,
                        )
                        if months_match:
                            try:
                                structured_years += round(float(months_match.group(1)) / 12.0, 1)
                            except ValueError:
                                pass

        if parsed_intervals:
            structured_span = self._compute_span_from_intervals(parsed_intervals)
            structured_years = max(structured_years, structured_span)

        # 2. Extract employment date intervals directly from resume text
        text_intervals = self._extract_intervals_from_text(resume_text)
        text_span = self._compute_span_from_intervals(text_intervals) if text_intervals else 0.0

        # 3. Extract explicit experience declarations from resume text
        explicit_years = self._extract_explicit_experience_years(resume_text)

        # Take the maximum substantiated experience value
        total = max(structured_years, text_span, explicit_years)
        if total <= 0.0 and isinstance(candidate_experience, list) and candidate_experience:
            total = round(len(candidate_experience) * 1.5, 1)

        return round(max(0.0, total), 1)

    @staticmethod
    def _compute_span_from_intervals(intervals: List[Tuple[float, float]]) -> float:
        """Sort intervals and compute union span to avoid double-counting overlapping roles."""
        if not intervals:
            return 0.0
        sorted_intervals = sorted(intervals, key=lambda x: x[0])
        merged = [sorted_intervals[0]]
        for start, end in sorted_intervals[1:]:
            last_start, last_end = merged[-1]
            if start <= last_end:
                merged[-1] = (last_start, max(last_end, end))
            else:
                merged.append((start, end))

        total = sum(max(0.2, end - start) for start, end in merged)
        return round(total, 1)

    def calculate_qualification_score(
        self,
        candidate_education: List[Any],
        candidate_certs: List[Any],
        required_qualifications: List[Any],
        required_certs: List[Any],
    ) -> Tuple[float, str]:
        """Compare candidate degrees and certifications against JD requirements.

        Args:
            candidate_education: List of education dicts or strings.
            candidate_certs: List of candidate certification strings.
            required_qualifications: List of required educational criteria.
            required_certs: List of required certification requirements.

        Returns:
            Tuple[float, str]: (Qualification score 0-100, explanation string).
        """
        has_edu_req = bool(required_qualifications)
        has_cert_req = bool(required_certs)

        if not has_edu_req and not has_cert_req:
            return (
                100.0,
                "No specific degree or certification requirements mandated.",
            )

        edu_score = 100.0
        cert_score = 100.0
        explanations = []

        # 1. Evaluate Education if required
        if has_edu_req:
            edu_score, edu_msg = self._evaluate_education(
                candidate_education, required_qualifications
            )
            explanations.append(edu_msg)

        # 2. Evaluate Certifications if required
        if has_cert_req:
            cert_score, cert_msg = self._evaluate_certifications(
                candidate_certs, required_certs
            )
            explanations.append(cert_msg)

        # Weighted combination
        if has_edu_req and has_cert_req:
            final_score = round(0.60 * edu_score + 0.40 * cert_score, 1)
        elif has_edu_req:
            final_score = round(edu_score, 1)
        else:
            final_score = round(cert_score, 1)

        summary_explanation = " | ".join(explanations)
        return (final_score, summary_explanation)

    def _evaluate_education(
        self, candidate_education: List[Any], required_qualifications: List[Any]
    ) -> Tuple[float, str]:
        """Score candidate degrees against required educational qualifications."""
        if not required_qualifications:
            return (100.0, "Education requirements satisfied.")

        cand_highest_level = 0
        cand_degrees_text = []

        for item in candidate_education or []:
            text = ""
            if isinstance(item, dict):
                text = f"{item.get('degree', '')} {item.get('institution', '')}"
            elif isinstance(item, str):
                text = item
            cand_degrees_text.append(text.lower())
            for deg_token, lvl in DEGREE_LEVELS.items():
                if deg_token in text.lower():
                    cand_highest_level = max(cand_highest_level, lvl)

        # Find target required level
        target_level = 2  # default Bachelor's
        for req in required_qualifications:
            req_text = (
                req.get("requirement_name", "") if isinstance(req, dict) else str(req)
            ).lower()
            for deg_token, lvl in DEGREE_LEVELS.items():
                if deg_token in req_text:
                    target_level = max(target_level, lvl)

        if cand_highest_level >= target_level:
            return (100.0, "Candidate meets or exceeds required educational degree level.")
        elif cand_highest_level == target_level - 1 and cand_highest_level > 0:
            return (
                75.0,
                f"Candidate holds associate or intermediate degree below target level.",
            )
        elif cand_highest_level > 0:
            return (50.0, "Candidate holds partial degree qualifications.")
        elif candidate_education:
            return (60.0, "Education history present; formal degree level unverified.")
        else:
            return (30.0, "No formal educational degrees identified in profile.")

    def _evaluate_certifications(
        self, candidate_certs: List[Any], required_certs: List[Any]
    ) -> Tuple[float, str]:
        """Score candidate certifications against required certifications."""
        if not required_certs:
            return (100.0, "Certifications satisfied.")

        cand_certs_clean = [
            (c.get("name", "") if isinstance(c, dict) else str(c)).lower()
            for c in candidate_certs or []
        ]

        matched_count = 0
        missing_certs = []

        for req in required_certs:
            req_name = (
                req.get("requirement_name", "") if isinstance(req, dict) else str(req)
            ).strip()
            req_lower = req_name.lower()

            matched = False
            for cand_c in cand_certs_clean:
                if req_lower in cand_c or cand_c in req_lower:
                    matched = True
                    break

            if matched:
                matched_count += 1
            else:
                missing_certs.append(req_name)

        total_req = len(required_certs)
        score = round((matched_count / total_req) * 100.0, 1)

        if missing_certs:
            msg = f"Certifications: {matched_count}/{total_req} verified (Missing: {', '.join(missing_certs[:3])})."
        else:
            msg = f"All {total_req} required certifications verified."

        return (score, msg)

    def calculate_score(
        self,
        candidate_data: Dict[str, Any],
        jd_requirements: List[Any],
        weights: Optional[Dict[str, float]] = None,
        precalculated_evidence: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Calculate comprehensive score, category, breakdown, and evidence justification.

        Args:
            candidate_data: Structured candidate attributes (skills, experience, education, certs).
            jd_requirements: List of JDRequirement objects or dictionaries.
            weights: Optional custom category weights (normalized to 100.0%).
            precalculated_evidence: Optional pre-evaluated requirement evidence list.

        Returns:
            Dict[str, Any] containing comprehensive assessment results.
        """
        cfg_weights = self.validate_weights(weights or self.default_weights)

        # 1. Structure requirements
        structured_reqs: List[Dict[str, Any]] = []
        for r in jd_requirements:
            if hasattr(r, "id"):
                structured_reqs.append({
                    "id": r.id,
                    "requirement_name": r.requirement_name,
                    "category": r.category,
                    "importance": r.importance,
                    "normalized_value": r.normalized_value or r.requirement_name,
                    "weight": float(getattr(r, "weight", 1.0) or 1.0),
                    "is_enabled": getattr(r, "is_enabled", True),
                    "original_evidence": getattr(r, "original_evidence", None),
                })
            elif isinstance(r, dict):
                structured_reqs.append({
                    "id": r.get("id", 0),
                    "requirement_name": r.get("requirement_name", ""),
                    "category": r.get("category", "mandatory_skill"),
                    "importance": r.get("importance", "mandatory"),
                    "normalized_value": r.get("normalized_value") or r.get("requirement_name", ""),
                    "weight": float(r.get("weight", 1.0) or 1.0),
                    "is_enabled": r.get("is_enabled", True),
                    "original_evidence": r.get("original_evidence"),
                })

        enabled_reqs = [r for r in structured_reqs if r.get("is_enabled", True)]

        # Group requirements by component category
        mandatory_reqs = [
            r for r in enabled_reqs
            if r["category"] in ("mandatory_skill", "tool") and r["importance"] == "mandatory"
            or r["category"] == "mandatory_skill"
        ]
        preferred_reqs = [
            r for r in enabled_reqs
            if r["category"] in ("preferred_skill", "tool") and r["importance"] == "preferred"
            or r["category"] == "preferred_skill"
        ]
        experience_reqs = [r for r in enabled_reqs if r["category"] == "experience"]
        domain_reqs = [
            r for r in enabled_reqs
            if r["category"] in ("domain", "responsibility", "other")
        ]
        education_reqs = [r for r in enabled_reqs if r["category"] == "education"]
        cert_reqs = [r for r in enabled_reqs if r["category"] == "certification"]

        # Map precalculated evidence if provided
        evidence_by_req_id: Dict[int, Dict[str, Any]] = {}
        if precalculated_evidence:
            for ev in precalculated_evidence:
                r_id = ev.get("requirement_id")
                if r_id:
                    evidence_by_req_id[r_id] = ev

        candidate_skills = set(
            s.lower().strip()
            for s in (candidate_data.get("skills") or [])
            if isinstance(s, str)
        )
        resume_text = candidate_data.get("resume_text", "") or ""

        # 2. Evaluate Mandatory Skills
        mandatory_met = 0
        mandatory_total = len(mandatory_reqs)
        mandatory_missing: List[str] = []
        mandatory_uncertain: List[str] = []
        mandatory_weighted_sum = 0.0
        mandatory_weight_total = 0.0
        evidence_list: List[Dict[str, Any]] = []

        for req in mandatory_reqs:
            w = max(0.1, req["weight"])
            mandatory_weight_total += w
            ev = evidence_by_req_id.get(req["id"])
            status = ev.get("match_status") if ev else None

            if not status:
                status, ev_text, conf = self._quick_match_requirement(
                    req, candidate_skills, resume_text
                )
                ev = {
                    "requirement_id": req["id"],
                    "match_status": status,
                    "evidence_text": ev_text,
                    "confidence": conf,
                    "explanation": f"Mandatory skill check: '{req['requirement_name']}' is {status}.",
                    "needs_human_review": status in ("partial", "uncertain"),
                }

            evidence_list.append(ev)

            if status == "matched":
                mandatory_met += 1
                mandatory_weighted_sum += w * 1.0
            elif status == "partial":
                mandatory_uncertain.append(req["requirement_name"])
                mandatory_weighted_sum += w * 0.5
            elif status == "uncertain":
                mandatory_uncertain.append(req["requirement_name"])
                mandatory_weighted_sum += w * 0.4
            else:
                mandatory_missing.append(req["requirement_name"])
                mandatory_weighted_sum += w * 0.0

        mandatory_score = (
            round((mandatory_weighted_sum / mandatory_weight_total) * 100.0, 1)
            if mandatory_weight_total > 0
            else 100.0
        )

        # 3. Evaluate Preferred Skills
        preferred_met = 0
        preferred_total = len(preferred_reqs)
        preferred_weighted_sum = 0.0
        preferred_weight_total = 0.0

        for req in preferred_reqs:
            w = max(0.1, req["weight"])
            preferred_weight_total += w
            ev = evidence_by_req_id.get(req["id"])
            status = ev.get("match_status") if ev else None

            if not status:
                status, ev_text, conf = self._quick_match_requirement(
                    req, candidate_skills, resume_text
                )
                ev = {
                    "requirement_id": req["id"],
                    "match_status": status,
                    "evidence_text": ev_text,
                    "confidence": conf,
                    "explanation": f"Preferred skill check: '{req['requirement_name']}' is {status}.",
                    "needs_human_review": status in ("partial", "uncertain"),
                }

            evidence_list.append(ev)

            if status == "matched":
                preferred_met += 1
                preferred_weighted_sum += w * 1.0
            elif status in ("partial", "uncertain"):
                preferred_weighted_sum += w * 0.5

        preferred_score = (
            round((preferred_weighted_sum / preferred_weight_total) * 100.0, 1)
            if preferred_weight_total > 0
            else 100.0
        )

        # 4. Evaluate Experience
        req_min = candidate_data.get("experience_min")
        req_max = candidate_data.get("experience_max")

        # If experience range is not provided at JD level, infer from experience requirements
        if (req_min is None or float(req_min) <= 0) and experience_reqs:
            for ereq in experience_reqs:
                p_min, p_max = parse_experience_range_from_text(
                    f"{ereq.get('requirement_name', '')} {ereq.get('original_evidence', '')}"
                )
                if p_min is not None:
                    req_min = p_min
                    req_max = p_max
                    break

        cand_exp = candidate_data.get("experience", [])
        experience_score, exp_msg = self.calculate_experience_score(
            cand_exp, required_min=req_min, required_max=req_max, resume_text=resume_text
        )

        # Also evaluate atomic experience requirements if present
        for req in experience_reqs:
            ev = evidence_by_req_id.get(req["id"])
            if not ev:
                specific_min, specific_max = parse_experience_range_from_text(
                    f"{req.get('requirement_name', '')} {req.get('original_evidence', '')}"
                )
                if specific_min is not None:
                    req_exp_score, req_exp_msg = self.calculate_experience_score(
                        cand_exp, required_min=specific_min, required_max=specific_max, resume_text=resume_text
                    )
                else:
                    req_exp_score, req_exp_msg = experience_score, exp_msg

                status_val = "matched" if req_exp_score >= 80 else ("partial" if req_exp_score >= 50 else "not_found")
                ev = {
                    "requirement_id": req["id"],
                    "match_status": status_val,
                    "evidence_text": req_exp_msg,
                    "confidence": 0.92 if specific_min is not None else 0.85,
                    "explanation": f"Experience evaluation against '{req.get('requirement_name', '')}': {req_exp_msg}",
                    "needs_human_review": status_val != "matched",
                }
            evidence_list.append(ev)

        # 5. Evaluate Qualifications & Certifications
        cand_edu = candidate_data.get("education", [])
        cand_certs = candidate_data.get("certifications", [])
        qual_score, qual_msg = self.calculate_qualification_score(
            candidate_education=cand_edu,
            candidate_certs=cand_certs,
            required_qualifications=education_reqs,
            required_certs=cert_reqs,
        )

        for req in education_reqs + cert_reqs:
            ev = evidence_by_req_id.get(req["id"])
            if not ev:
                status = "matched" if qual_score >= 70 else ("partial" if qual_score >= 50 else "not_found")
                ev = {
                    "requirement_id": req["id"],
                    "match_status": status,
                    "evidence_text": qual_msg,
                    "confidence": 0.80,
                    "explanation": f"Qualification verification: {qual_msg}",
                    "needs_human_review": status in ("partial", "not_found"),
                }
            evidence_list.append(ev)

        # 6. Evaluate Domain & Responsibilities
        domain_weighted_sum = 0.0
        domain_weight_total = 0.0
        for req in domain_reqs:
            w = max(0.1, req["weight"])
            domain_weight_total += w
            ev = evidence_by_req_id.get(req["id"])
            status = ev.get("match_status") if ev else None

            if not status:
                status, ev_text, conf = self._quick_match_requirement(
                    req, candidate_skills, resume_text
                )
                ev = {
                    "requirement_id": req["id"],
                    "match_status": status,
                    "evidence_text": ev_text,
                    "confidence": conf,
                    "explanation": f"Domain / Responsibility: '{req['requirement_name']}' is {status}.",
                    "needs_human_review": status in ("partial", "uncertain"),
                }

            evidence_list.append(ev)
            if status == "matched":
                domain_weighted_sum += w * 1.0
            elif status in ("partial", "uncertain"):
                domain_weighted_sum += w * 0.5

        domain_score = (
            round((domain_weighted_sum / domain_weight_total) * 100.0, 1)
            if domain_weight_total > 0
            else 100.0
        )

        # 7. Dynamic Weight Distribution for Active Components
        active_components: Dict[str, float] = {}
        # Mandatory skills: active if mandatory requirements exist
        if mandatory_total > 0:
            active_components["mandatory_skills"] = cfg_weights["mandatory_skills"]
        # Preferred skills: active if preferred requirements exist
        if preferred_total > 0:
            active_components["preferred_skills"] = cfg_weights["preferred_skills"]
        # Experience: active if experience requirements or JD bounds exist
        if experience_reqs or req_min is not None or req_max is not None:
            active_components["experience"] = cfg_weights["experience"]
        # Domain: active if domain/responsibility requirements exist
        if domain_reqs:
            active_components["domain_responsibilities"] = cfg_weights["domain_responsibilities"]
        # Qualifications: active if education or cert requirements exist
        if education_reqs or cert_reqs:
            active_components["qualifications_certifications"] = cfg_weights["qualifications_certifications"]

        # If no explicit category requirements exist, default to all components
        if not active_components:
            active_components = dict(cfg_weights)

        active_sum = sum(active_components.values())
        rebalanced_weights = {
            k: (v / active_sum) for k, v in active_components.items()
        }

        # Component scores dictionary
        component_scores = {
            "mandatory_skills": mandatory_score,
            "experience": experience_score,
            "preferred_skills": preferred_score,
            "domain_responsibilities": domain_score,
            "qualifications_certifications": qual_score,
        }

        total_score = 0.0
        for comp, rel_weight in rebalanced_weights.items():
            total_score += component_scores[comp] * rel_weight

        total_score = round(max(0.0, min(100.0, total_score)), 1)

        # 8. Match Category
        match_category = self.categorize_match(total_score, mandatory_met, mandatory_total)

        # 9. Strengths & Gaps Identification
        strengths: List[str] = []
        gaps: List[str] = []

        # Mandatory analysis
        if mandatory_total > 0:
            if mandatory_met == mandatory_total:
                strengths.append(f"Satisfies all {mandatory_total} mandatory skill requirements.")
            else:
                gaps.append(
                    f"Missing {len(mandatory_missing)} mandatory skill(s): {', '.join(mandatory_missing[:4])}."
                )

        if mandatory_uncertain:
            gaps.append(
                f"Needs recruiter verification for: {', '.join(mandatory_uncertain[:3])}."
            )

        # Experience analysis
        if experience_score >= 90:
            strengths.append(exp_msg)
        elif experience_score < 70:
            gaps.append(exp_msg)

        # Preferred analysis
        if preferred_total > 0 and preferred_met > 0:
            strengths.append(f"Matched {preferred_met}/{preferred_total} preferred skills.")

        # Qualification analysis
        if (education_reqs or cert_reqs) and qual_score >= 80:
            strengths.append(qual_msg)
        elif (education_reqs or cert_reqs) and qual_score < 60:
            gaps.append(qual_msg)

        # 10. Confidence Score
        confidence = self._compute_confidence(
            evidence_list=evidence_list,
            resume_text=resume_text,
            candidate_data=candidate_data,
        )

        return {
            "total_score": total_score,
            "match_category": match_category,
            "mandatory_met": mandatory_met,
            "mandatory_total": mandatory_total,
            "mandatory_missing": mandatory_missing,
            "mandatory_uncertain": mandatory_uncertain,
            "preferred_met": preferred_met,
            "preferred_total": preferred_total,
            "experience_score": experience_score,
            "qualification_score": qual_score,
            "domain_score": domain_score,
            "strengths": strengths,
            "gaps": gaps,
            "confidence": confidence,
            "component_scores": component_scores,
            "evidence": evidence_list,
        }

    def _quick_match_requirement(
        self, req: Dict[str, Any], candidate_skills: Set[str], resume_text: str
    ) -> Tuple[str, str, float]:
        """Fallback boundary-aware text match for requirements if not pre-matched."""
        name = req.get("normalized_value") or req.get("requirement_name", "")
        name_clean = name.strip().lower()

        # Check candidate parsed skills
        if name_clean in candidate_skills:
            return ("matched", f"Found '{name}' in candidate skills profile.", 0.95)

        # Check in resume text with boundary regex
        if resume_text:
            escaped = re.escape(name_clean)
            pattern = re.compile(rf"(?<![\w#+.-]){escaped}(?![\w#+.-])", re.IGNORECASE)
            match = pattern.search(resume_text)
            if match:
                start = max(0, match.start() - 40)
                end = min(len(resume_text), match.end() + 40)
                snippet = "..." + resume_text[start:end].replace("\n", " ").strip() + "..."
                return ("matched", f"Mentioned in resume: {snippet}", 0.85)

        return ("not_found", f"Requirement '{name}' not identified in resume profile.", 0.90)

    @staticmethod
    def _compute_confidence(
        evidence_list: List[Dict[str, Any]],
        resume_text: str,
        candidate_data: Dict[str, Any],
    ) -> float:
        """Calculate overall engine confidence based on evidence quality and text depth."""
        if not evidence_list:
            base_conf = 0.50
        else:
            conf_values = [ev.get("confidence", 0.7) for ev in evidence_list]
            base_conf = sum(conf_values) / len(conf_values)

        # Adjust for resume text length
        text_len = len(resume_text.strip().split()) if resume_text else 0
        if text_len < 50:
            base_conf *= 0.70  # significant penalty for very short text
        elif text_len < 120:
            base_conf *= 0.85
        elif text_len > 400:
            base_conf = min(0.98, base_conf * 1.05)

        # Check parsing warnings
        warnings = candidate_data.get("parsing_warnings")
        if warnings:
            base_conf *= 0.90

        return round(max(0.20, min(0.99, base_conf)), 2)
