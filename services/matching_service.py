"""Matching engine orchestrator service for TalentMatch AI.

Coordinates candidate-job requirement matching, exact/normalized/synonym/boundary-aware
skill matching, candidate profile parsing, batch screening execution, match persistence,
evidence tracking, and recruiter review lifecycle.
"""

import concurrent.futures
from datetime import datetime
import json
import logging
import re
import threading
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from config.settings import get_settings
from database.connection import get_session
from database.models import (
    AuditLog,
    Candidate,
    CandidateMatch,
    JDRequirement,
    JobDescription,
    MatchEvidence,
    RecruiterReview,
    ResumeDocument,
    ScreeningBatch,
    ScreeningRun,
    Shortlist,
    ShortlistCandidate,
)
from services.scoring_service import ScoringService

logger = logging.getLogger(__name__)

# Canonical Skill Synonyms & Aliases Map
SKILL_SYNONYMS: Dict[str, str] = {
    # Programming Languages
    "py": "Python",
    "py3": "Python",
    "python3": "Python",
    "js": "JavaScript",
    "es6": "JavaScript",
    "es6+": "JavaScript",
    "ts": "TypeScript",
    "golang": "Go",
    "c++": "C++",
    "cplusplus": "C++",
    "cpp": "C++",
    "c#": "C#",
    "csharp": "C#",
    "c sharp": "C#",
    # Frontend
    "react": "React",
    "reactjs": "React",
    "react.js": "React",
    "vue": "Vue.js",
    "vuejs": "Vue.js",
    "vue.js": "Vue.js",
    "angular": "Angular",
    "angularjs": "Angular",
    "nextjs": "Next.js",
    "next.js": "Next.js",
    "html": "HTML",
    "html5": "HTML",
    "css": "CSS",
    "css3": "CSS",
    # Backend
    "node": "Node.js",
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "express": "Express.js",
    "expressjs": "Express.js",
    "django": "Django",
    "flask": "Flask",
    "fastapi": "FastAPI",
    "spring": "Spring Boot",
    "springboot": "Spring Boot",
    "spring boot": "Spring Boot",
    "dotnet": ".NET",
    ".net": ".NET",
    ".net core": ".NET Core",
    "asp.net": "ASP.NET Core",
    # Databases
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "psql": "PostgreSQL",
    "mongo": "MongoDB",
    "mongodb": "MongoDB",
    "ms sql": "Microsoft SQL Server",
    "mssql": "Microsoft SQL Server",
    "sql server": "Microsoft SQL Server",
    "elastic": "Elasticsearch",
    "elasticsearch": "Elasticsearch",
    "redis": "Redis",
    "dynamo": "DynamoDB",
    "dynamodb": "DynamoDB",
    # Cloud & DevOps
    "aws": "AWS",
    "amazon web services": "AWS",
    "gcp": "Google Cloud Platform (GCP)",
    "google cloud": "Google Cloud Platform (GCP)",
    "google cloud platform": "Google Cloud Platform (GCP)",
    "azure": "Microsoft Azure",
    "ms azure": "Microsoft Azure",
    "k8s": "Kubernetes",
    "kube": "Kubernetes",
    "docker": "Docker",
    "ci/cd": "CI/CD",
    "cicd": "CI/CD",
    "ci / cd": "CI/CD",
    "terraform": "Terraform",
    "actions": "GitHub Actions",
    "gh actions": "GitHub Actions",
    # Data & AI
    "ml": "Machine Learning",
    "dl": "Deep Learning",
    "ai": "Artificial Intelligence",
    "genai": "Generative AI",
    "gen ai": "Generative AI",
    "llm": "Large Language Models (LLM)",
    "llms": "Large Language Models (LLM)",
    "nlp": "Natural Language Processing (NLP)",
    "cv": "Computer Vision",
    "bi": "Business Intelligence",
    "powerbi": "Power BI",
    "power-bi": "Power BI",
    "spark": "Apache Spark",
    "kafka": "Apache Kafka",
    "airflow": "Apache Airflow",
    "hadoop": "Apache Hadoop",
    "tf": "TensorFlow",
    "sklearn": "Scikit-Learn",
    "scikit-learn": "Scikit-Learn",
    "scikit learn": "Scikit-Learn",
    # Architecture & Protocols
    "rest": "REST API",
    "restful": "REST API",
    "rest api": "REST API",
    "restful api": "REST API",
    "restful apis": "REST API",
    "rest apis": "REST API",
    "graphql": "GraphQL",
    "grpc": "gRPC",
    "microservices": "Microservices",
    "oop": "Object-Oriented Programming (OOP)",
    "oops": "Object-Oriented Programming (OOP)",
    "tdd": "Test-Driven Development (TDD)",
    "bdd": "Behavior-Driven Development (BDD)",
    # Certifications
    "pmp": "PMP",
    "csm": "Certified ScrumMaster (CSM)",
    "cissp": "CISSP",
    "aws csa": "AWS Certified Solutions Architect",
}


class MatchingService:
    """Orchestration service for candidate matching, requirement scoring, and batch evaluation."""

    def __init__(self, scoring_service: Optional[ScoringService] = None) -> None:
        """Initialize matching service with scoring engine and configuration."""
        self.scoring = scoring_service or ScoringService()
        self.settings = get_settings()

    def build_candidate_data(self, candidate: Any) -> Dict[str, Any]:
        """Extract structured profile dictionary from Candidate ORM entity or mapping.

        Args:
            candidate: Candidate instance or dict.

        Returns:
            Dict[str, Any]: Structured candidate attributes ready for matching.
        """
        if isinstance(candidate, dict):
            return dict(candidate)

        # Deserialize JSON fields safely
        skills = candidate.get_skills() if hasattr(candidate, "get_skills") else []
        if not skills and candidate.skills_json:
            try:
                skills = json.loads(candidate.skills_json)
            except Exception:
                skills = []

        experience = []
        if candidate.experience_json:
            try:
                experience = json.loads(candidate.experience_json)
            except Exception:
                experience = []

        education = []
        if candidate.education_json:
            try:
                education = json.loads(candidate.education_json)
            except Exception:
                education = []

        certifications = []
        if candidate.certifications_json:
            try:
                certifications = json.loads(candidate.certifications_json)
            except Exception:
                certifications = []

        # Extract text from attached resume documents
        resume_text = ""
        resume_filename = "resume.pdf"
        if hasattr(candidate, "resumes") and candidate.resumes:
            first_resume = candidate.resumes[0]
            resume_text = first_resume.resume_text or ""
            resume_filename = first_resume.original_filename or "resume.pdf"

        parsing_warnings = []
        if candidate.parsing_warnings:
            try:
                parsing_warnings = json.loads(candidate.parsing_warnings)
            except Exception:
                parsing_warnings = [candidate.parsing_warnings]

        return {
            "id": candidate.id,
            "name": candidate.name,
            "email": candidate.email,
            "phone": candidate.phone,
            "skills": skills,
            "experience": experience,
            "education": education,
            "certifications": certifications,
            "resume_summary": candidate.resume_summary or "",
            "resume_text": resume_text,
            "resume_filename": resume_filename,
            "parsing_status": candidate.parsing_status,
            "parsing_warnings": parsing_warnings,
            "upload_batch_id": candidate.upload_batch_id,
        }

    def build_requirement_data(self, requirements: List[Any]) -> List[Dict[str, Any]]:
        """Convert JDRequirement models to standardized dictionaries.

        Args:
            requirements: List of JDRequirement ORM models or dicts.

        Returns:
            List[Dict[str, Any]]: Standardized requirements list.
        """
        req_list: List[Dict[str, Any]] = []
        for req in requirements:
            if isinstance(req, dict):
                req_list.append(dict(req))
            else:
                req_list.append({
                    "id": req.id,
                    "jd_id": req.jd_id,
                    "requirement_name": req.requirement_name,
                    "category": req.category,
                    "importance": req.importance,
                    "normalized_value": req.normalized_value or req.requirement_name,
                    "weight": float(req.weight or 1.0),
                    "is_enabled": bool(req.is_enabled),
                    "original_evidence": req.original_evidence,
                    "recruiter_notes": req.recruiter_notes,
                })
        return req_list

    def match_domain_or_responsibility(
        self,
        candidate_skills: List[Any],
        requirement_name: str,
        normalized_value: Optional[str] = None,
        resume_text: str = "",
        candidate_summary: str = "",
    ) -> Dict[str, Any]:
        """Perform boundary-aware and conceptual matching for domain knowledge or job responsibilities.

        Unlike atomic technical skills (e.g. 'Python'), domain requirements (e.g. 'Master Data Management (MDM) Testing Experience')
        and responsibilities (e.g. 'Develop Automated Test Scripts for Data Validation') are descriptive phrases.
        This method checks:
        1. Acronym presence (e.g. '(MDM)' -> 'MDM') in resume text, summary, and skills.
        2. Normalized phrase presence (replacing underscores with spaces).
        3. Domain synonym and cluster matching (e.g. MDM <-> data management, data governance, data warehousing).
        4. Sub-concept and multi-word semantic coverage across skills and experience text.
        """
        raw_name = requirement_name.strip()
        norm_name = (normalized_value or raw_name).strip()
        lower_raw = raw_name.lower()
        lower_norm = norm_name.lower()

        clean_skills = [
            (s.get("name", "") if isinstance(s, dict) else str(s)).strip().lower()
            for s in (candidate_skills or [])
        ]
        clean_skills_set = set(clean_skills)

        # Build full searchable candidate corpus (summary + resume text)
        full_corpus = f"{candidate_summary} {resume_text}".strip()
        full_corpus_lower = full_corpus.lower()

        # 1. Extract and check acronym in parentheses, e.g. '(MDM)' -> 'mdm'
        acronym_match = re.search(r"\(([A-Za-z0-9#+.-]+)\)", raw_name)
        if acronym_match:
            acronym = acronym_match.group(1).lower()
            if len(acronym) >= 2:
                if acronym in clean_skills_set:
                    return {
                        "status": "matched",
                        "evidence": f"Acronym '{acronym.upper()}' identified in verified technical skills.",
                        "confidence": 0.95,
                    }
                acr_pattern = re.compile(rf"(?<![\w#+.-]){re.escape(acronym)}(?![\w#+.-])", re.IGNORECASE)
                m = acr_pattern.search(full_corpus)
                if m:
                    start = max(0, m.start() - 40)
                    end = min(len(full_corpus), m.end() + 40)
                    snip = "..." + full_corpus[start:end].replace("\n", " ").strip() + "..."
                    return {
                        "status": "matched",
                        "evidence": f"Identified acronym '{acronym.upper()}' in resume: \"{snip}\"",
                        "confidence": 0.92,
                    }

        # 2. Check full phrase or normalized phrase with underscores converted to spaces
        clean_phrases = [
            norm_name.replace("_", " "),
            re.sub(r"\([^)]*\)", "", raw_name).strip(),
            raw_name,
        ]
        for phrase in clean_phrases:
            p_clean = phrase.strip().lower()
            if len(p_clean) >= 3 and p_clean in full_corpus_lower:
                idx = full_corpus_lower.find(p_clean)
                start = max(0, idx - 40)
                end = min(len(full_corpus), idx + len(p_clean) + 40)
                snip = "..." + full_corpus[start:end].replace("\n", " ").strip() + "..."
                return {
                    "status": "matched",
                    "evidence": f"Direct domain/responsibility reference found in resume: \"{snip}\"",
                    "confidence": 0.92,
                }

        # 3. Domain synonym clusters mapping
        DOMAIN_SYNONYM_MAP = {
            "master_data_management": ["data management", "data governance", "data warehousing", "data warehouse", "mdm", "etl", "data quality", "data integration"],
            "mdm": ["master data", "data governance", "data management", "data warehousing", "data warehouse", "etl"],
            "data_governance": ["compliance", "retention policies", "data classification", "legal hold", "data management", "purview"],
            "data_pipeline": ["data pipelines", "data pipeline", "etl", "data warehousing", "data processing", "data validation"],
            "data_validation": ["data validation", "data integrity", "sql validation", "backend validation", "database testing"],
            "api_testing": ["api validation", "api testing", "rest api", "postman", "endpoints", "request/response"],
            "validate_api_endpoints": ["api validation", "api testing", "rest api", "postman", "payloads", "status codes", "api testing"],
            "design_automated_test_plans": ["test plans", "test cases", "test suites", "automated test", "test automation", "regression suite"],
            "develop_automated_test_scripts": ["automated validation", "automated test", "automation suites", "data validation", "test scripts", "automation components"],
            "fintech": ["banking", "payments", "cards", "financial", "trading", "insurance", "pci-dss"],
            "healthcare": ["hipaa", "ehr", "emr", "clinical", "hospital", "patient", "medical"],
            "ecommerce": ["e-commerce", "retail", "shopify", "magento", "checkout", "cart"],
            "ediscovery": ["e-discovery", "electronic data processing", "data governance", "compliance", "retention policies"],
        }

        relevant_synonyms: List[str] = []
        if lower_norm in DOMAIN_SYNONYM_MAP:
            relevant_synonyms.extend(DOMAIN_SYNONYM_MAP[lower_norm])
        for k, syn_list in DOMAIN_SYNONYM_MAP.items():
            if k in lower_raw or k in lower_norm:
                relevant_synonyms.extend(syn_list)

        matched_synonyms = []
        for syn in set(relevant_synonyms):
            if syn in full_corpus_lower or syn in clean_skills_set:
                matched_synonyms.append(syn)

        if len(matched_synonyms) >= 2:
            return {
                "status": "matched",
                "evidence": f"Candidate demonstrates strong domain alignment: verified experience in {', '.join(sorted(matched_synonyms)[:4])}.",
                "confidence": 0.90,
            }
        elif len(matched_synonyms) == 1:
            return {
                "status": "partial",
                "evidence": f"Candidate demonstrates partial domain exposure: verified '{matched_synonyms[0]}'.",
                "confidence": 0.75,
            }

        # 4. Multi-word composite concept coverage
        stop_words = {
            "and", "the", "for", "with", "using", "based", "across", "from", "into",
            "experience", "testing", "tests", "test", "requirement", "skills",
            "knowledge", "understanding", "ability", "proven", "strong", "good",
        }
        tokens = [
            w for w in re.findall(r"\b[a-zA-Z]{3,}\b", f"{raw_name} {norm_name.replace('_', ' ')}".lower())
            if w not in stop_words
        ]
        unique_tokens = list(dict.fromkeys(tokens))

        if unique_tokens:
            matched_tokens = [w for w in unique_tokens if w in full_corpus_lower or w in clean_skills_set]
            ratio = len(matched_tokens) / len(unique_tokens)

            if ratio >= 0.65:
                return {
                    "status": "matched",
                    "evidence": f"Demonstrated domain/responsibility competency: matched concepts ({', '.join(matched_tokens)}).",
                    "confidence": 0.85,
                }
            elif ratio >= 0.35:
                return {
                    "status": "partial",
                    "evidence": f"Partial responsibility overlap: identified related competencies ({', '.join(matched_tokens)}).",
                    "confidence": 0.70,
                }

        return {
            "status": "not_found",
            "evidence": f"Domain / Responsibility '{raw_name}' not identified in resume profile.",
            "confidence": 0.85,
        }

    def match_skill(
        self,
        candidate_skills: List[Any],
        requirement_name: str,
        normalized_value: Optional[str] = None,
        resume_text: str = "",
    ) -> Dict[str, Any]:
        """Perform boundary-aware matching of a single skill against candidate data.

        Matches via:
        1. Exact case-insensitive match in parsed candidate skills
        2. Canonical / synonym mapping match in candidate skills
        3. Strict word-boundary regex search in full resume plain text
        4. Safe partial match (excluding substring false-positives like Java in JavaScript)

        Args:
            candidate_skills: List of candidate skill strings or dicts.
            requirement_name: Name of the skill requirement.
            normalized_value: Canonical name or alias if known.
            resume_text: Raw plain text of the candidate's resume.

        Returns:
            Dict[str, Any]: {
                "status": "matched" | "partial" | "not_found" | "uncertain",
                "evidence": str,
                "confidence": float
            }
        """
        raw_name = requirement_name.strip()
        norm_name = (normalized_value or raw_name).strip()
        lower_raw = raw_name.lower()
        lower_norm = norm_name.lower()

        # Resolve canonical form from synonyms map
        canonical_target = SKILL_SYNONYMS.get(lower_norm, SKILL_SYNONYMS.get(lower_raw, norm_name))
        lower_canonical = canonical_target.lower()

        # Clean candidate skills
        cand_skills_clean: List[str] = []
        cand_skills_canonical: Set[str] = set()

        for s in candidate_skills or []:
            s_name = s.get("name", "") if isinstance(s, dict) else str(s)
            s_clean = s_name.strip().lower()
            if s_clean:
                cand_skills_clean.append(s_clean)
                cand_canon = SKILL_SYNONYMS.get(s_clean, s_name.strip())
                cand_skills_canonical.add(cand_canon.lower())

        # 1. Exact or Canonical Match in candidate's structured skill set
        if lower_canonical in cand_skills_canonical or lower_raw in cand_skills_clean or lower_norm in cand_skills_clean:
            return {
                "status": "matched",
                "evidence": f"Identified in verified technical skills: '{canonical_target}'.",
                "confidence": 0.96,
            }

        # 2. Strict Boundary Search in Resume Text
        if resume_text:
            text_match, snippet = self._find_in_text_with_boundaries(
                target=canonical_target,
                aliases=[raw_name, norm_name, lower_raw, lower_norm],
                text=resume_text,
            )
            if text_match:
                return {
                    "status": "matched",
                    "evidence": f"Found in resume content: \"{snippet}\"",
                    "confidence": 0.88,
                }

        # 3. Boundary-aware Partial / Token Overlap Match
        # E.g. "PostgreSQL Database" matches "PostgreSQL"
        target_tokens = set(re.findall(r"\b[a-zA-Z0-9#+.-]{2,}\b", lower_canonical.replace("_", " ")))
        target_tokens.discard("and")
        target_tokens.discard("the")
        target_tokens.discard("for")

        if len(target_tokens) > 1:
            for cand_skill in cand_skills_clean:
                cand_tokens = set(re.findall(r"\b[a-zA-Z0-9#+.-]{2,}\b", cand_skill))
                overlap = target_tokens.intersection(cand_tokens)
                if len(overlap) >= max(1, len(target_tokens) - 1):
                    return {
                        "status": "partial",
                        "evidence": f"Partial match with candidate skill '{cand_skill}'.",
                        "confidence": 0.72,
                    }

        # 4. Check for ambiguous or partial mentions in resume text
        for token in target_tokens:
            if len(token) >= 4 and resume_text:
                token_pattern = re.compile(rf"(?<![\w#+.-]){re.escape(token)}(?![\w#+.-])", re.IGNORECASE)
                if token_pattern.search(resume_text):
                    return {
                        "status": "uncertain",
                        "evidence": f"Related keyword '{token}' mentioned, but full requirement '{canonical_target}' requires verification.",
                        "confidence": 0.50,
                    }

        return {
            "status": "not_found",
            "evidence": f"Requirement '{canonical_target}' not found in candidate skills or resume document.",
            "confidence": 0.90,
        }

    def _find_in_text_with_boundaries(
        self, target: str, aliases: List[str], text: str
    ) -> Tuple[bool, str]:
        """Search text using boundary-aware regex to prevent substring collisions."""
        search_terms = {target, target.replace("_", " ")} | set(aliases) | {a.replace("_", " ") for a in aliases}

        for term in search_terms:
            t = term.strip()
            if not t or len(t) < 1:
                continue

            escaped = re.escape(t)

            # Special case boundary rules for single/short letters or compound words
            lower_t = t.lower()
            if lower_t == "java":
                # Java must not be followed by Script
                pattern = re.compile(r"(?<![\w#+.-])java(?![\w#+.-]|(?:\s*script\b))", re.IGNORECASE)
            elif lower_t in ("c", "r"):
                # C or R must not be adjacent to letters, plus, or hash
                pattern = re.compile(rf"(?<![\w#+.-]){escaped}(?![\w#+.-])", re.IGNORECASE)
            elif lower_t in ("go", "golang"):
                pattern = re.compile(r"(?<![\w#+.-])(?:go|golang)(?![\w#+.-])", re.IGNORECASE)
            elif lower_t in ("c++", "cpp", "cplusplus"):
                pattern = re.compile(r"(?<![\w#+.-])(?:c\+\+|cpp|cplusplus)(?![\w#+.-])", re.IGNORECASE)
            elif lower_t in ("c#", "csharp"):
                pattern = re.compile(r"(?<![\w#+.-])(?:c#|csharp)(?![\w#+.-])", re.IGNORECASE)
            elif lower_t in (".net", "dotnet"):
                pattern = re.compile(r"(?<![\w#+.-])(?:\.net|dotnet)(?![\w#+.-])", re.IGNORECASE)
            else:
                pattern = re.compile(rf"(?<![\w#+.-]){escaped}(?![\w#+.-])", re.IGNORECASE)

            match = pattern.search(text)
            if match:
                # Extract surrounding snippet (up to 75 characters on each side)
                start = max(0, match.start() - 40)
                end = min(len(text), match.end() + 40)
                snippet = "..." + text[start:end].replace("\n", " ").strip() + "..."
                return True, snippet

        return False, ""

    def _screen_candidate_with_ai(
        self,
        candidate_data: Dict[str, Any],
        jd: Any,
        req_data_list: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Perform semantic LLM screening of a candidate against a JD using Google Gemini.

        Evaluates conceptual and transferable competence, depth of experience, and returns
        structured fit assessment, strengths, gaps, confidence, and tailored interview questions.

        Returns:
            Optional[Dict[str, Any]]: Structured AI evaluation, or None if unavailable/error.
        """
        settings = get_settings()
        api_key = settings.get_api_key()
        model_name = settings.get_model()

        if not api_key:
            return None

        try:
            from services.ai_client import generate_fast_ai_content

            cand_skills = ", ".join(candidate_data.get("skills", [])[:25]) or "None extracted"
            clean_resume = re.sub(r"\n\s*\n+", "\n\n", (candidate_data.get("resume_text") or "").strip())[:3500]

            top_reqs = sorted(
                req_data_list,
                key=lambda r: 0 if r.get("importance") == "mandatory" else 1
            )[:10]
            reqs_summary = [
                f"- [{r.get('importance', 'mandatory').upper()}] {r.get('requirement_name')} ({r.get('category')})"
                for r in top_reqs
            ]
            reqs_text = "\n".join(reqs_summary)

            prompt = (
                "You are an expert technical recruitment evaluator. Assess this candidate's fit for the Job Description.\n\n"
                f"JOB TITLE: {jd.title}\n"
                f"EXPERIENCE REQUIRED: {jd.experience_min or 0} to {jd.experience_max or 'any'} years\n"
                f"KEY REQUIREMENTS:\n{reqs_text}\n\n"
                f"CANDIDATE: {candidate_data.get('name') or candidate_data.get('full_name', 'Unknown')}\n"
                f"PARSED SKILLS: {cand_skills}\n"
                f"RESUME EXCERPT:\n{clean_resume}\n\n"
                "Return a JSON object with this exact schema:\n"
                "{\n"
                '  "overall_fit_score": <float 0.0 to 100.0>,\n'
                '  "match_category": <"strong_match" | "potential_match" | "needs_review" | "insufficient_evidence">,\n'
                '  "confidence": <float 0.0 to 1.0>,\n'
                '  "summary": <concise 1-2 sentence executive evaluation of candidate fit>,\n'
                '  "strengths": [<2-3 concise bullet points highlighting key advantages>],\n'
                '  "gaps": [<1-2 concise bullet points identifying deficits or risks>],\n'
                '  "interview_questions": [<2 tailored technical interview questions>]\n'
                "}"
            )

            raw_text = generate_fast_ai_content(
                prompt=prompt,
                model=model_name,
                api_key=api_key,
                max_output_tokens=800,
                temperature=0.1,
                json_mode=True,
            )

            if not raw_text:
                return None

            from services.ai_client import safe_parse_json
            ai_data = safe_parse_json(raw_text)
            if isinstance(ai_data, dict) and "overall_fit_score" in ai_data:
                logger.info(
                    "AI candidate screening completed for '%s' against '%s' (Score: %s, Category: %s).",
                    candidate_data.get("full_name"),
                    jd.title,
                    ai_data.get("overall_fit_score"),
                    ai_data.get("match_category"),
                )
                return ai_data

        except Exception as exc:
            logger.warning("AI candidate screening failed (%s); falling back to rule-based evaluation.", exc)

        return None

    def match_candidate_to_jd(
        self,
        candidate_id: int,
        jd_id: int,
        method: str = "rule_based",
        weights: Optional[Dict[str, float]] = None,
        screening_run_id: Optional[int] = None,
        force_rescreen: bool = False,
    ) -> Dict[str, Any]:
        """Execute full screening pipeline for a candidate against a Job Description.

        Loads candidate and JD records, runs atomic requirement evaluations,
        computes transparent scores, and persists CandidateMatch and MatchEvidence.

        Args:
            candidate_id: Primary key of Candidate.
            jd_id: Primary key of JobDescription.
            method: Screening method ('rule_based' or 'ai_assisted').
            weights: Optional custom scoring weights dictionary.
            screening_run_id: Optional ScreeningRun correlation identifier.
            force_rescreen: If False, reuses existing match if candidate/JD hasn't changed.

        Returns:
            Dict[str, Any]: Persisted CandidateMatch result dictionary.
        """
        # Instant cache bypass: if already evaluated with matching method and not outdated
        if not force_rescreen and not weights:
            with get_session() as session:
                match_stmt = select(CandidateMatch).where(
                    CandidateMatch.candidate_id == candidate_id,
                    CandidateMatch.jd_id == jd_id,
                )
                existing = session.scalars(match_stmt).first()
                if existing and existing.last_screened_at:
                    is_ai_result = bool(existing.reviewer_notes and "AI Fit Assessment" in existing.reviewer_notes)
                    if (method == "ai_assisted" and is_ai_result) or (method == "rule_based" and not is_ai_result):
                        cand_time = session.scalar(select(Candidate.updated_at).where(Candidate.id == candidate_id)) or datetime.min
                        jd_time = session.scalar(select(JobDescription.updated_at).where(JobDescription.id == jd_id)) or datetime.min
                        if existing.last_screened_at >= cand_time and existing.last_screened_at >= jd_time:
                            logger.info("Serving cached match result for Candidate #%d on JD #%d (0ms)", candidate_id, jd_id)
                            return self.get_match_detail(existing.id)

        with get_session() as session:
            # 1. Load candidate with resumes
            c_stmt = (
                select(Candidate)
                .where(Candidate.id == candidate_id)
                .options(joinedload(Candidate.resumes))
            )
            candidate = session.scalars(c_stmt).unique().first()
            if not candidate:
                raise ValueError(f"Candidate #{candidate_id} not found.")

            # 2. Load JD with enabled requirements
            j_stmt = (
                select(JobDescription)
                .where(JobDescription.id == jd_id)
                .options(selectinload(JobDescription.requirements))
            )
            jd = session.scalars(j_stmt).unique().first()
            if not jd:
                raise ValueError(f"Job Description #{jd_id} not found.")

            candidate_data = self.build_candidate_data(candidate)
            # Inject JD experience range into candidate data for scoring
            candidate_data["experience_min"] = jd.experience_min
            candidate_data["experience_max"] = jd.experience_max

            requirements = [r for r in jd.requirements if r.is_enabled]
            req_data_list = self.build_requirement_data(requirements)

            # 3. Evaluate each atomic requirement to generate MatchEvidence
            evidence_records: List[Dict[str, Any]] = []
            for req in req_data_list:
                cat = req["category"]
                req_name = req["requirement_name"]
                norm_val = req["normalized_value"]

                if cat in ("mandatory_skill", "preferred_skill", "tool"):
                    skill_res = self.match_skill(
                        candidate_skills=candidate_data["skills"],
                        requirement_name=req_name,
                        normalized_value=norm_val,
                        resume_text=candidate_data["resume_text"],
                    )
                    evidence_records.append({
                        "requirement_id": req["id"],
                        "match_status": skill_res["status"],
                        "evidence_text": skill_res["evidence"],
                        "confidence": skill_res["confidence"],
                        "explanation": f"Evaluated skill requirement '{req_name}'. Status: {skill_res['status']}.",
                        "needs_human_review": skill_res["status"] in ("partial", "uncertain"),
                    })

                elif cat == "experience":
                    cand_exp = candidate_data.get("experience", [])
                    from services.scoring_service import parse_experience_range_from_text

                    # Extract range specifically from this requirement text if present (e.g. '4-5 Years Software/QA Experience')
                    p_min, p_max = parse_experience_range_from_text(
                        f"{req_name} {req.get('original_evidence', '')} {req.get('normalized_value', '')}"
                    )
                    effective_min = p_min if p_min is not None else jd.experience_min
                    effective_max = p_max if p_max is not None else jd.experience_max

                    score_exp, msg_exp = self.scoring.calculate_experience_score(
                        cand_exp,
                        required_min=effective_min,
                        required_max=effective_max,
                        resume_text=candidate_data["resume_text"],
                    )
                    st = "matched" if score_exp >= 80 else ("partial" if score_exp >= 50 else "not_found")
                    conf = 0.95 if effective_min is not None else 0.75
                    evidence_records.append({
                        "requirement_id": req["id"],
                        "match_status": st,
                        "evidence_text": msg_exp,
                        "confidence": conf,
                        "explanation": f"Experience evaluation against '{req_name}': {msg_exp}",
                        "needs_human_review": st != "matched",
                    })

                elif cat in ("education", "certification"):
                    score_qual, msg_qual = self.scoring.calculate_qualification_score(
                        candidate_education=candidate_data.get("education", []),
                        candidate_certs=candidate_data.get("certifications", []),
                        required_qualifications=[req] if cat == "education" else [],
                        required_certs=[req] if cat == "certification" else [],
                    )
                    st = "matched" if score_qual >= 75 else ("partial" if score_qual >= 40 else "not_found")
                    evidence_records.append({
                        "requirement_id": req["id"],
                        "match_status": st,
                        "evidence_text": msg_qual,
                        "confidence": 0.85,
                        "explanation": f"Qualification check for '{req_name}': {msg_qual}",
                        "needs_human_review": st != "matched",
                    })

                else:  # domain, responsibility, other
                    domain_res = self.match_domain_or_responsibility(
                        candidate_skills=candidate_data["skills"],
                        requirement_name=req_name,
                        normalized_value=norm_val,
                        resume_text=candidate_data["resume_text"],
                        candidate_summary=candidate_data.get("resume_summary", ""),
                    )
                    evidence_records.append({
                        "requirement_id": req["id"],
                        "match_status": domain_res["status"],
                        "evidence_text": domain_res["evidence"],
                        "confidence": domain_res["confidence"],
                        "explanation": f"Domain/Responsibility review for '{req_name}'.",
                        "needs_human_review": domain_res["status"] in ("partial", "uncertain"),
                    })

            # If AI-Assisted screening is chosen, perform deep semantic evaluation using Gemini
            ai_eval: Optional[Dict[str, Any]] = None
            if method == "ai_assisted":
                ai_eval = self._screen_candidate_with_ai(candidate_data, jd, req_data_list)
                if ai_eval and "evaluations" in ai_eval:
                    eval_map = {e.get("requirement_id"): e for e in ai_eval["evaluations"] if "requirement_id" in e}
                    for ev in evidence_records:
                        r_id = ev.get("requirement_id")
                        if r_id in eval_map:
                            ai_item = eval_map[r_id]
                            ai_status = str(ai_item.get("match_status", "")).lower()
                            if ai_status in ("matched", "partial", "not_found", "uncertain"):
                                ev["match_status"] = ai_status
                            if ai_item.get("evidence_text"):
                                ev["evidence_text"] = ai_item["evidence_text"]
                            if ai_item.get("confidence") is not None:
                                ev["confidence"] = float(ai_item["confidence"])
                            if ai_item.get("explanation"):
                                ev["explanation"] = f"AI Evaluation: {ai_item['explanation']}"
                            ev["needs_human_review"] = ev["match_status"] in ("partial", "uncertain", "not_found")

            # 4. Compute overall score and breakdown via ScoringService
            score_result = self.scoring.calculate_score(
                candidate_data=candidate_data,
                jd_requirements=req_data_list,
                weights=weights,
                precalculated_evidence=evidence_records,
            )

            # If AI screening succeeded, blend score and enrich summary/strengths/gaps
            ai_notes_text = None
            if ai_eval:
                ai_score = float(ai_eval.get("overall_fit_score", score_result["total_score"]))
                # Balanced blend: 40% transparent deterministic rubric + 60% semantic evaluation
                score_result["total_score"] = round(0.4 * score_result["total_score"] + 0.6 * ai_score, 1)
                score_result["confidence"] = float(ai_eval.get("confidence", 0.92))
                if ai_eval.get("match_category"):
                    score_result["match_category"] = ai_eval["match_category"]
                if ai_eval.get("strengths"):
                    score_result["strengths"] = ai_eval["strengths"]
                if ai_eval.get("gaps"):
                    score_result["gaps"] = ai_eval["gaps"]

                notes_parts = []
                if ai_eval.get("summary"):
                    notes_parts.append(f"🤖 AI Fit Assessment:\n{ai_eval['summary']}")
                if ai_eval.get("interview_questions"):
                    q_str = "\n".join(f"- {q}" for q in ai_eval["interview_questions"])
                    notes_parts.append(f"💡 Recommended Interview Questions:\n{q_str}")
                if notes_parts:
                    ai_notes_text = "\n\n".join(notes_parts)

            # 5. Persist or Update CandidateMatch in Database
            match_stmt = select(CandidateMatch).where(
                CandidateMatch.candidate_id == candidate_id,
                CandidateMatch.jd_id == jd_id,
            )
            candidate_match = session.scalars(match_stmt).first()

            if not candidate_match:
                candidate_match = CandidateMatch(
                    candidate_id=candidate_id,
                    jd_id=jd_id,
                    screening_run_id=screening_run_id,
                    match_score=score_result["total_score"],
                    match_category=score_result["match_category"],
                    mandatory_met=score_result["mandatory_met"],
                    mandatory_total=score_result["mandatory_total"],
                    mandatory_missing_json=json.dumps(score_result["mandatory_missing"]),
                    preferred_met=score_result["preferred_met"],
                    preferred_total=score_result["preferred_total"],
                    experience_score=score_result["experience_score"],
                    qualification_score=score_result["qualification_score"],
                    domain_score=score_result["domain_score"],
                    strengths_json=json.dumps(score_result["strengths"]),
                    gaps_json=json.dumps(score_result["gaps"]),
                    confidence=score_result["confidence"],
                    parsing_warnings=(
                        json.dumps(candidate_data["parsing_warnings"])
                        if candidate_data["parsing_warnings"]
                        else None
                    ),
                    human_review_status="pending",
                    reviewer_notes=ai_notes_text,
                    last_screened_at=datetime.utcnow(),
                )
                session.add(candidate_match)
                session.flush()
            else:
                # Update existing match
                if screening_run_id:
                    candidate_match.screening_run_id = screening_run_id
                candidate_match.match_score = score_result["total_score"]
                candidate_match.match_category = score_result["match_category"]
                candidate_match.mandatory_met = score_result["mandatory_met"]
                candidate_match.mandatory_total = score_result["mandatory_total"]
                candidate_match.mandatory_missing_json = json.dumps(score_result["mandatory_missing"])
                candidate_match.preferred_met = score_result["preferred_met"]
                candidate_match.preferred_total = score_result["preferred_total"]
                candidate_match.experience_score = score_result["experience_score"]
                candidate_match.qualification_score = score_result["qualification_score"]
                candidate_match.domain_score = score_result["domain_score"]
                candidate_match.strengths_json = json.dumps(score_result["strengths"])
                candidate_match.gaps_json = json.dumps(score_result["gaps"])
                candidate_match.confidence = score_result["confidence"]
                if ai_notes_text and not candidate_match.reviewer_notes:
                    candidate_match.reviewer_notes = ai_notes_text
                candidate_match.last_screened_at = datetime.utcnow()

                # Clean prior evidence records for replacement
                session.execute(
                    delete(MatchEvidence).where(MatchEvidence.candidate_match_id == candidate_match.id)
                )
                session.flush()

            # 6. Insert new MatchEvidence records
            for ev_item in score_result.get("evidence", []):
                r_id = ev_item.get("requirement_id")
                if not r_id:
                    continue
                evidence_row = MatchEvidence(
                    candidate_match_id=candidate_match.id,
                    requirement_id=r_id,
                    match_status=ev_item.get("match_status", "not_found"),
                    evidence_text=ev_item.get("evidence_text"),
                    confidence=float(ev_item.get("confidence", 0.8)),
                    explanation=ev_item.get("explanation"),
                    needs_human_review=bool(ev_item.get("needs_human_review", False)),
                )
                session.add(evidence_row)

            # Audit log
            audit = AuditLog(
                entity_type="CandidateMatch",
                entity_id=candidate_match.id,
                action="screen",
                details_json=json.dumps({
                    "candidate_id": candidate_id,
                    "jd_id": jd_id,
                    "score": score_result["total_score"],
                    "category": score_result["match_category"],
                    "method": method,
                }),
                performed_by="system",
            )
            session.add(audit)
            session.flush()

            match_id = candidate_match.id

        # Return detached serialized outcome
        return self.get_match_detail(match_id)

    def run_batch_matching(
        self,
        jd_ids: List[int],
        candidate_ids: Optional[List[int]] = None,
        method: str = "rule_based",
        weights: Optional[Dict[str, float]] = None,
        progress_callback: Optional[Any] = None,
        force_rescreen: bool = True,
    ) -> Dict[str, Any]:
        """Execute automated screening across a matrix of JDs and candidates.

        Creates a ScreeningBatch, evaluates all (JD, Candidate) pairs (concurrently if AI-assisted),
        generates ScreeningRun records, tracks progress, and records batch metrics.

        Args:
            jd_ids: List of target Job Description IDs.
            candidate_ids: Optional list of Candidate IDs (defaults to all parsed candidates).
            method: Screening method ('rule_based' or 'ai_assisted').
            weights: Optional custom scoring weights.
            progress_callback: Optional callable(completed, total, current_desc) for progress updates.
            force_rescreen: Whether to recalculate matches or reuse fresh cached matches.

        Returns:
            Dict[str, Any]: {
                "batch_id": int,
                "total_pairs": int,
                "completed": int,
                "failed": int,
                "results": List[Dict[str, Any]]
            }
        """
        if not jd_ids:
            raise ValueError("At least one Job Description ID must be provided.")

        with get_session() as session:
            # Resolve candidate IDs if omitted
            if not candidate_ids:
                stmt = select(Candidate.id).order_by(Candidate.id.asc())
                candidate_ids = list(session.scalars(stmt).all())

            if not candidate_ids:
                return {
                    "batch_id": 0,
                    "total_pairs": 0,
                    "completed": 0,
                    "failed": 0,
                    "results": [],
                }

            # Create ScreeningBatch
            batch = ScreeningBatch(
                name=f"Batch Screening {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
                description=f"Automated evaluation across {len(jd_ids)} JD(s) and {len(candidate_ids)} candidate(s).",
                jd_ids_json=json.dumps(jd_ids),
                candidate_count=len(candidate_ids),
                status="processing",
                matching_method=method,
                scoring_config_json=json.dumps(weights) if weights else None,
                created_by="Recruiter",
            )
            session.add(batch)
            session.flush()
            batch_id = batch.id

        total_pairs = len(jd_ids) * len(candidate_ids)
        completed_count = 0
        failed_count = 0
        results: List[Dict[str, Any]] = []

        pairs: List[Tuple[int, int, int, int]] = []
        for j_idx, jd_id in enumerate(jd_ids, start=1):
            for c_idx, candidate_id in enumerate(candidate_ids, start=1):
                pairs.append((j_idx, jd_id, c_idx, candidate_id))

        def process_pair_work(item: Tuple[int, int, int, int]) -> Optional[Dict[str, Any]]:
            j_idx, jd_id, c_idx, candidate_id = item
            run_id: Optional[int] = None

            with get_session() as session:
                run = ScreeningRun(
                    batch_id=batch_id,
                    jd_id=jd_id,
                    candidate_id=candidate_id,
                    status="running",
                    matching_method=method,
                    scoring_config_json=json.dumps(weights) if weights else None,
                )
                session.add(run)
                session.flush()
                run_id = run.id

            try:
                match_res = self.match_candidate_to_jd(
                    candidate_id=candidate_id,
                    jd_id=jd_id,
                    method=method,
                    weights=weights,
                    screening_run_id=run_id,
                    force_rescreen=force_rescreen,
                )
                with get_session() as session:
                    run_obj = session.get(ScreeningRun, run_id)
                    if run_obj:
                        run_obj.status = "completed"
                        run_obj.completed_at = datetime.utcnow()
                return match_res

            except Exception as exc:
                logger.error(
                    "Screening failed for candidate #%d on JD #%d: %s",
                    candidate_id,
                    jd_id,
                    exc,
                    exc_info=True,
                )
                with get_session() as session:
                    run_obj = session.get(ScreeningRun, run_id)
                    if run_obj:
                        run_obj.status = "failed"
                        run_obj.completed_at = datetime.utcnow()
                return None

        # For AI-assisted screening across multiple candidates, execute in parallel for 3-4x throughput
        if method == "ai_assisted" and len(pairs) > 1:
            max_workers = min(3, len(pairs))
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_pair = {executor.submit(process_pair_work, p): p for p in pairs}
                for future in concurrent.futures.as_completed(future_to_pair):
                    p = future_to_pair[future]
                    j_idx, jd_id, c_idx, candidate_id = p
                    try:
                        res = future.result()
                        if res:
                            results.append(res)
                            completed_count += 1
                        else:
                            failed_count += 1
                    except Exception as err:
                        logger.error("Screening thread error: %s", err)
                        failed_count += 1

                    if progress_callback:
                        progress_callback(
                            completed_count + failed_count,
                            total_pairs,
                            f"Screened candidate {c_idx}/{len(candidate_ids)} for JD {j_idx}/{len(jd_ids)}",
                        )
        else:
            for p in pairs:
                j_idx, jd_id, c_idx, candidate_id = p
                res = process_pair_work(p)
                if res:
                    results.append(res)
                    completed_count += 1
                else:
                    failed_count += 1

                if progress_callback:
                    progress_callback(
                        completed_count + failed_count,
                        total_pairs,
                        f"Screened candidate {c_idx}/{len(candidate_ids)} for JD {j_idx}/{len(jd_ids)}",
                    )

        # Mark batch completed
        with get_session() as session:
            batch_obj = session.get(ScreeningBatch, batch_id)
            if batch_obj:
                batch_obj.status = "completed" if failed_count == 0 else "completed_with_errors"
                batch_obj.completed_at = datetime.utcnow()

        return {
            "batch_id": batch_id,
            "total_pairs": total_pairs,
            "completed": completed_count,
            "failed": failed_count,
            "results": results,
        }

    def get_match_results(
        self,
        jd_id: int,
        filters: Optional[Dict[str, Any]] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Retrieve paginated match results for a JD with filters and total count.

        Args:
            jd_id: Primary key of Job Description.
            filters: Optional dictionary containing:
                - min_score (float)
                - max_score (float)
                - category (str)
                - human_review_status (str)
                - search (str)
            offset: SQL offset.
            limit: Page size limit.

        Returns:
            Tuple[List[Dict[str, Any]], int]: (List of match result dictionaries, Total matching count).
        """
        filters = filters or {}
        clauses = [CandidateMatch.jd_id == jd_id]

        if filters.get("min_score") is not None:
            clauses.append(CandidateMatch.match_score >= float(filters["min_score"]))

        if filters.get("max_score") is not None:
            clauses.append(CandidateMatch.match_score <= float(filters["max_score"]))

        if filters.get("category") and filters["category"] != "All":
            clauses.append(CandidateMatch.match_category == filters["category"])

        if filters.get("human_review_status") and filters["human_review_status"] != "All":
            clauses.append(CandidateMatch.human_review_status == filters["human_review_status"])

        search = (filters.get("search") or "").strip()

        with get_session() as session:
            # Count query
            count_stmt = (
                select(func.count())
                .select_from(CandidateMatch)
                .join(Candidate, CandidateMatch.candidate_id == Candidate.id)
                .where(*clauses)
            )
            if search:
                s_pattern = f"%{search}%"
                count_stmt = count_stmt.where(
                    or_(
                        Candidate.name.ilike(s_pattern),
                        Candidate.email.ilike(s_pattern),
                        Candidate.skills_json.ilike(s_pattern),
                    )
                )

            total_count = session.scalar(count_stmt) or 0

            # Records query
            stmt = (
                select(CandidateMatch)
                .join(Candidate, CandidateMatch.candidate_id == Candidate.id)
                .where(*clauses)
                .options(
                    joinedload(CandidateMatch.candidate).joinedload(Candidate.resumes),
                    joinedload(CandidateMatch.job_description),
                )
            )
            if search:
                s_pattern = f"%{search}%"
                stmt = stmt.where(
                    or_(
                        Candidate.name.ilike(s_pattern),
                        Candidate.email.ilike(s_pattern),
                        Candidate.skills_json.ilike(s_pattern),
                    )
                )

            stmt = stmt.order_by(CandidateMatch.match_score.desc()).offset(offset).limit(limit)
            matches = session.scalars(stmt).unique().all()

            results = [self._serialize_match(m) for m in matches]
            return results, total_count

    def get_candidate_matches(self, candidate_id: int) -> List[Dict[str, Any]]:
        """Retrieve all matches evaluated for a candidate across Job Descriptions.

        Args:
            candidate_id: Primary key of Candidate.

        Returns:
            List[Dict[str, Any]]: Serialized match summaries.
        """
        with get_session() as session:
            stmt = (
                select(CandidateMatch)
                .where(CandidateMatch.candidate_id == candidate_id)
                .options(
                    joinedload(CandidateMatch.job_description),
                    joinedload(CandidateMatch.candidate),
                )
                .order_by(CandidateMatch.match_score.desc())
            )
            matches = session.scalars(stmt).unique().all()
            return [self._serialize_match(m) for m in matches]

    def get_match_detail(self, match_id: int) -> Dict[str, Any]:
        """Fetch full details, requirements breakdown, and evidence for a match.

        Args:
            match_id: Primary key ID of CandidateMatch.

        Returns:
            Dict[str, Any]: Comprehensive match result.
        """
        with get_session() as session:
            stmt = (
                select(CandidateMatch)
                .where(CandidateMatch.id == match_id)
                .options(
                    joinedload(CandidateMatch.candidate).joinedload(Candidate.resumes),
                    joinedload(CandidateMatch.job_description).selectinload(JobDescription.requirements),
                    joinedload(CandidateMatch.match_evidences).joinedload(MatchEvidence.requirement),
                    joinedload(CandidateMatch.recruiter_reviews),
                )
            )
            match = session.scalars(stmt).unique().first()
            if not match:
                raise ValueError(f"CandidateMatch #{match_id} not found.")

            return self._serialize_match(match, include_deep_evidence=True)

    def update_review_status(
        self,
        match_id: int,
        status: str,
        notes: Optional[str] = None,
        reason: Optional[str] = None,
        reviewer: str = "Recruiter",
    ) -> Dict[str, Any]:
        """Record human recruiter verification decision on a candidate match.

        Updates CandidateMatch human review fields and logs a RecruiterReview record.

        Args:
            match_id: Primary key ID of CandidateMatch.
            status: New review status ('pending', 'reviewed', 'shortlisted', 'on_hold', 'not_selected').
            notes: Optional reviewer commentary.
            reason: Optional justification for status transition.
            reviewer: Identifier of the recruiter submitting the review.

        Returns:
            Dict[str, Any]: Updated match detail dictionary.
        """
        with get_session() as session:
            match = session.get(CandidateMatch, match_id)
            if not match:
                raise ValueError(f"CandidateMatch #{match_id} not found.")

            prev_status = match.human_review_status
            match.human_review_status = status
            if notes is not None:
                match.reviewer_notes = notes
            if reason is not None:
                match.reviewer_decision_reason = reason

            review = RecruiterReview(
                candidate_match_id=match_id,
                reviewer=reviewer,
                action="status_change",
                previous_status=prev_status,
                new_status=status,
                reason=reason,
                notes=notes,
            )
            session.add(review)

            audit = AuditLog(
                entity_type="CandidateMatch",
                entity_id=match_id,
                action="recruiter_review",
                details_json=json.dumps({
                    "previous_status": prev_status,
                    "new_status": status,
                    "reason": reason,
                }),
                performed_by=reviewer,
            )
            session.add(audit)

            # Auto-sync to Shortlist pipeline if candidate is marked as 'shortlisted'
            if status == "shortlisted":
                # Find or create active shortlist for this Job Description
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
                        created_by=reviewer,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                    )
                    session.add(active_sl)
                    session.flush()

                # Add candidate to shortlist if not already added
                cand_sl_stmt = select(ShortlistCandidate).where(
                    ShortlistCandidate.shortlist_id == active_sl.id,
                    ShortlistCandidate.candidate_id == match.candidate_id,
                )
                existing_entry = session.scalars(cand_sl_stmt).first()
                if existing_entry:
                    existing_entry.status = "shortlisted"
                    existing_entry.candidate_match_id = match_id
                    if notes:
                        existing_entry.recruiter_notes = notes.strip()
                    existing_entry.reviewed_at = datetime.utcnow()
                else:
                    new_entry = ShortlistCandidate(
                        shortlist_id=active_sl.id,
                        candidate_id=match.candidate_id,
                        candidate_match_id=match_id,
                        status="shortlisted",
                        recruiter_notes=notes.strip() if notes else None,
                        added_at=datetime.utcnow(),
                        reviewed_at=datetime.utcnow(),
                    )
                    session.add(new_entry)

                active_sl.updated_at = datetime.utcnow()

            session.flush()

        return self.get_match_detail(match_id)

    def rerun_matching(
        self,
        match_id: int,
        method: Optional[str] = None,
        weights: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """Re-execute screening evaluation for an existing match record.

        Args:
            match_id: Primary key ID of CandidateMatch.
            method: Screening method ('rule_based' or 'ai_assisted').
            weights: Optional updated scoring weights.

        Returns:
            Dict[str, Any]: Freshly computed match dictionary.
        """
        with get_session() as session:
            match = session.get(CandidateMatch, match_id)
            if not match:
                raise ValueError(f"CandidateMatch #{match_id} not found.")
            cand_id = match.candidate_id
            jd_id = match.jd_id

        return self.match_candidate_to_jd(
            candidate_id=cand_id,
            jd_id=jd_id,
            method=method or "rule_based",
            weights=weights,
        )

    def _serialize_match(
        self, match: CandidateMatch, include_deep_evidence: bool = False
    ) -> Dict[str, Any]:
        """Convert a CandidateMatch entity and relations into a detached JSON-serializable dict."""
        cand = match.candidate
        jd = match.job_description

        # Parse json attributes
        mandatory_missing = []
        if match.mandatory_missing_json:
            try:
                mandatory_missing = json.loads(match.mandatory_missing_json)
            except Exception:
                mandatory_missing = []

        strengths = []
        if match.strengths_json:
            try:
                strengths = json.loads(match.strengths_json)
            except Exception:
                strengths = []

        gaps = []
        if match.gaps_json:
            try:
                gaps = json.loads(match.gaps_json)
            except Exception:
                gaps = []

        cand_skills = cand.get_skills() if cand and hasattr(cand, "get_skills") else []
        cand_resumes = getattr(cand, "resumes", []) if cand else []
        resume_name = cand_resumes[0].original_filename if cand_resumes else "resume.pdf"

        res: Dict[str, Any] = {
            "id": match.id,
            "candidate_id": match.candidate_id,
            "candidate_name": cand.name if cand else "Unknown",
            "candidate_email": cand.email if cand else "",
            "candidate_phone": cand.phone if cand else "",
            "candidate_skills": cand_skills,
            "candidate_resume_filename": resume_name,
            "jd_id": match.jd_id,
            "jd_title": jd.title if jd else "Unknown",
            "jd_department": jd.department if jd else "",
            "match_score": match.match_score,
            "match_category": match.match_category,
            "mandatory_met": match.mandatory_met,
            "mandatory_total": match.mandatory_total,
            "mandatory_missing": mandatory_missing,
            "preferred_met": match.preferred_met,
            "preferred_total": match.preferred_total,
            "experience_score": match.experience_score,
            "qualification_score": match.qualification_score,
            "domain_score": match.domain_score,
            "strengths": strengths,
            "gaps": gaps,
            "confidence": match.confidence,
            "human_review_status": match.human_review_status,
            "reviewer_notes": match.reviewer_notes,
            "reviewer_decision_reason": match.reviewer_decision_reason,
            "last_screened_at": match.last_screened_at.isoformat() if match.last_screened_at else None,
        }

        if include_deep_evidence:
            ev_list = []
            for ev in getattr(match, "match_evidences", []):
                req = ev.requirement
                ev_list.append({
                    "id": ev.id,
                    "requirement_id": ev.requirement_id,
                    "requirement_name": req.requirement_name if req else "Requirement",
                    "category": req.category if req else "other",
                    "importance": req.importance if req else "mandatory",
                    "weight": req.weight if req else 1.0,
                    "match_status": ev.match_status,
                    "evidence_text": ev.evidence_text,
                    "confidence": ev.confidence,
                    "explanation": ev.explanation,
                    "needs_human_review": ev.needs_human_review,
                })
            res["evidence"] = ev_list

            rev_list = []
            for rev in getattr(match, "recruiter_reviews", []):
                rev_list.append({
                    "reviewer": rev.reviewer,
                    "action": rev.action,
                    "previous_status": rev.previous_status,
                    "new_status": rev.new_status,
                    "reason": rev.reason,
                    "notes": rev.notes,
                    "reviewed_at": rev.reviewed_at.isoformat() if rev.reviewed_at else None,
                })
            res["reviews"] = rev_list

        return res
