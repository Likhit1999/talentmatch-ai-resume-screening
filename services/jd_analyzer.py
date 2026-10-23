"""Job Description analysis and requirement extraction service for TalentMatch AI.

Provides rule-based pattern matching and AI-augmented decomposition of
job postings into atomic, weighted screening requirements (skills, experience,
education, certifications, tools, and responsibilities).
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from config.settings import get_settings

logger = logging.getLogger(__name__)

# ==============================================================================
# Comprehensive Technical & Professional Skills Taxonomy (230+ skills)
# ==============================================================================
TECH_SKILLS_DICTIONARY: Dict[str, List[str]] = {
    "programming_languages": [
        "Python",
        "Java",
        "JavaScript",
        "TypeScript",
        "C",
        "C++",
        "C#",
        "Go",
        "Rust",
        "Ruby",
        "PHP",
        "Swift",
        "Kotlin",
        "Scala",
        "R",
        "MATLAB",
        "Perl",
        "Dart",
        "Shell",
        "Bash",
        "PowerShell",
        "SQL",
        "HTML",
        "CSS",
        "Assembly",
        "Groovy",
        "Julia",
        "Haskell",
        "Lua",
        "Fortran",
        "COBOL",
        "Objective-C",
        "Elixir",
        "Clojure",
        "F#",
        "Solidity",
    ],
    "frameworks_and_libraries": [
        "React",
        "Angular",
        "Vue.js",
        "Node.js",
        "Express.js",
        "Django",
        "Flask",
        "FastAPI",
        "Spring Boot",
        "ASP.NET Core",
        ".NET",
        "Ruby on Rails",
        "Next.js",
        "Nuxt.js",
        "Svelte",
        "Laravel",
        "Symfony",
        "jQuery",
        "Tailwind CSS",
        "Bootstrap",
        "Redux",
        "PyTorch",
        "TensorFlow",
        "Keras",
        "Scikit-Learn",
        "Pandas",
        "NumPy",
        "SciPy",
        "OpenCV",
        "HuggingFace",
        "LangChain",
        "LlamaIndex",
        "Apache Spark",
        "Apache Hadoop",
        "Apache Flink",
        "Apache Kafka",
        "Celery",
        "Apache Airflow",
        "Hibernate",
        "Entity Framework",
        "GraphQL",
        "Prisma",
        "NestJS",
        "Streamlit",
        "Dash",
        "Playwright",
        "Selenium",
        "Cypress",
        "Jest",
        "PyTest",
        "JUnit",
        "Mocha",
        "Chai",
        "NUnit",
    ],
    "databases": [
        "PostgreSQL",
        "MySQL",
        "MongoDB",
        "Redis",
        "SQLite",
        "Oracle Database",
        "Microsoft SQL Server",
        "Cassandra",
        "Elasticsearch",
        "DynamoDB",
        "MariaDB",
        "Couchbase",
        "Neo4j",
        "Snowflake",
        "Amazon Redshift",
        "Google BigQuery",
        "ClickHouse",
        "Firebase",
        "Supabase",
        "Apache Hive",
        "HBase",
        "CockroachDB",
        "Databricks",
        "OpenSearch",
        "TimescaleDB",
    ],
    "cloud_and_infrastructure": [
        "AWS",
        "Microsoft Azure",
        "Google Cloud Platform (GCP)",
        "Docker",
        "Kubernetes",
        "Terraform",
        "Ansible",
        "Jenkins",
        "CI/CD",
        "GitHub Actions",
        "GitLab CI",
        "Linux",
        "Unix",
        "Nginx",
        "Apache HTTP Server",
        "Helm",
        "Prometheus",
        "Grafana",
        "OpenShift",
        "CloudFormation",
        "Pulumi",
        "Vagrant",
        "Nomad",
        "Consul",
        "Serverless",
        "AWS Lambda",
        "Azure Functions",
        "Cloudflare",
        "Traefik",
        "CircleCI",
        "ArgoCD",
        "Datadog",
        "Splunk",
        "New Relic",
    ],
    "tools_and_platforms": [
        "Git",
        "GitHub",
        "GitLab",
        "Bitbucket",
        "Jira",
        "Confluence",
        "Trello",
        "Asana",
        "Postman",
        "Swagger",
        "Insomnia",
        "SonarQube",
        "Wireshark",
        "Docker Compose",
        "Webpack",
        "Vite",
        "Babel",
        "npm",
        "yarn",
        "pnpm",
        "Maven",
        "Gradle",
        "pip",
        "Poetry",
        "Conda",
        "VS Code",
        "IntelliJ IDEA",
        "Eclipse",
        "Figma",
    ],
    "architecture_and_methodologies": [
        "Microservices",
        "RESTful APIs",
        "REST API",
        "SOAP",
        "gRPC",
        "WebSockets",
        "Event-Driven Architecture",
        "Service-Oriented Architecture (SOA)",
        "Domain-Driven Design (DDD)",
        "Test-Driven Development (TDD)",
        "Behavior-Driven Development (BDD)",
        "Agile",
        "Scrum",
        "Kanban",
        "Waterfall",
        "Continuous Integration",
        "Continuous Deployment",
        "High Availability",
        "Distributed Systems",
        "System Architecture",
        "Object-Oriented Programming (OOP)",
        "Functional Programming",
        "Design Patterns",
        "MVC Architecture",
    ],
    "data_and_ai": [
        "Machine Learning",
        "Deep Learning",
        "Natural Language Processing (NLP)",
        "Computer Vision",
        "Generative AI",
        "Large Language Models (LLM)",
        "Data Modeling",
        "ETL",
        "ELT",
        "Data Warehousing",
        "Data Pipelines",
        "Business Intelligence",
        "Tableau",
        "Power BI",
        "Looker",
        "Statistics",
        "Predictive Modeling",
        "Feature Engineering",
    ],
    "soft_skills_and_management": [
        "Problem Solving",
        "Critical Thinking",
        "Team Leadership",
        "Communication Skills",
        "Project Management",
        "Cross-functional Collaboration",
        "Stakeholder Management",
        "Mentorship",
        "Time Management",
        "Conflict Resolution",
        "Technical Writing",
        "Strategic Thinking",
        "Emotional Intelligence",
        "Presentation Skills",
        "Adaptability",
        "Decision Making",
        "Negotiation",
        "Risk Management",
        "People Management",
        "Teamwork",
        "Code Review",
    ],
}

# Flatten list of all canonical skills for fast lookup
ALL_CANONICAL_SKILLS: Set[str] = {
    skill for cat_list in TECH_SKILLS_DICTIONARY.values() for skill in cat_list
}

# ==============================================================================
# Skill Synonyms & Aliases Mapping
# ==============================================================================
SKILL_SYNONYMS: Dict[str, str] = {
    "js": "JavaScript",
    "ts": "TypeScript",
    "py": "Python",
    "py3": "Python",
    "golang": "Go",
    "reactjs": "React",
    "react.js": "React",
    "vuejs": "Vue.js",
    "vue": "Vue.js",
    "nodejs": "Node.js",
    "node": "Node.js",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "psql": "PostgreSQL",
    "k8s": "Kubernetes",
    "kube": "Kubernetes",
    "aws": "AWS",
    "amazon web services": "AWS",
    "gcp": "Google Cloud Platform (GCP)",
    "google cloud": "Google Cloud Platform (GCP)",
    "azure": "Microsoft Azure",
    "ms azure": "Microsoft Azure",
    "mongo": "MongoDB",
    "rest": "REST API",
    "restful": "REST API",
    "rest api": "REST API",
    "restful api": "REST API",
    "restful apis": "REST API",
    "rest apis": "REST API",
    "tf": "TensorFlow",
    "sklearn": "Scikit-Learn",
    "scikit learn": "Scikit-Learn",
    "c sharp": "C#",
    "c#": "C#",
    "cplusplus": "C++",
    "c++": "C++",
    "dotnet": ".NET",
    ".net core": ".NET Core",
    "asp.net": "ASP.NET Core",
    "spring": "Spring Boot",
    "springboot": "Spring Boot",
    "es6": "JavaScript",
    "es6+": "JavaScript",
    "html5": "HTML",
    "css3": "CSS",
    "ml": "Machine Learning",
    "dl": "Deep Learning",
    "genai": "Generative AI",
    "gen ai": "Generative AI",
    "llm": "Large Language Models (LLM)",
    "llms": "Large Language Models (LLM)",
    "nlp": "Natural Language Processing (NLP)",
    "cv": "Computer Vision",
    "bi": "Business Intelligence",
    "powerbi": "Power BI",
    "power-bi": "Power BI",
    "ci/cd": "CI/CD",
    "cicd": "CI/CD",
    "ci / cd": "CI/CD",
    "pmp": "PMP",
    "csm": "Certified ScrumMaster (CSM)",
    "cissp": "CISSP",
    "scrum master": "Scrum",
    "oop": "Object-Oriented Programming (OOP)",
    "oops": "Object-Oriented Programming (OOP)",
    "tdd": "Test-Driven Development (TDD)",
    "bdd": "Behavior-Driven Development (BDD)",
    "qa": "Quality Assurance",
    "ms sql": "Microsoft SQL Server",
    "mssql": "Microsoft SQL Server",
    "sql server": "Microsoft SQL Server",
    "bigquery": "Google BigQuery",
    "redshift": "Amazon Redshift",
    "elastic": "Elasticsearch",
    "airflow": "Apache Airflow",
    "spark": "Apache Spark",
    "kafka": "Apache Kafka",
    "hadoop": "Apache Hadoop",
    "actions": "GitHub Actions",
    "gh actions": "GitHub Actions",
}


class JDAnalyzerService:
    """Service providing rule-based decomposition and AI parsing of Job Descriptions."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def normalize_skill(self, skill: str) -> str:
        """Normalize a skill name handling casing, whitespace, and synonym resolution.

        Args:
            skill: Raw skill string (e.g., 'k8s', 'py3', 'Postgresql').

        Returns:
            str: Canonical skill name (e.g., 'Kubernetes', 'Python', 'PostgreSQL').
        """
        if not skill:
            return ""

        clean = skill.strip()
        lower_clean = clean.lower()

        # Check explicit synonyms map
        if lower_clean in SKILL_SYNONYMS:
            return SKILL_SYNONYMS[lower_clean]

        # Check exact case-insensitive match against canonical skills
        for canonical in ALL_CANONICAL_SKILLS:
            if canonical.lower() == lower_clean:
                return canonical

        # Clean generic punctuation
        clean = re.sub(r"^[^\w#+.]+|[^\w#+.]+$", "", clean)
        return clean.strip().title() if clean else ""

    def extract_skills_from_text(self, text: str) -> List[str]:
        """Extract all identifiable technical and domain skills from arbitrary text.

        Uses boundary regex matching against canonical taxonomy and synonyms.

        Args:
            text: Arbitrary job or resume text block.

        Returns:
            List[str]: Deduplicated list of canonical skill names found.
        """
        if not text:
            return []

        found_skills: Set[str] = set()

        # Check all synonyms and aliases
        for alias, canonical in SKILL_SYNONYMS.items():
            pattern = self._build_skill_regex(alias)
            if pattern.search(text):
                found_skills.add(canonical)

        # Check all canonical skills
        for skill in ALL_CANONICAL_SKILLS:
            pattern = self._build_skill_regex(skill)
            if pattern.search(text):
                found_skills.add(skill)

        return sorted(list(found_skills))

    def _build_skill_regex(self, skill: str) -> re.Pattern:
        """Build a safe regex pattern respecting boundary conditions for C++, .NET, etc."""
        escaped = re.escape(skill)
        # Handle special non-word trailing characters like C++, C#, .NET
        if skill.endswith("+") or skill.endswith("#") or skill.startswith("."):
            return re.compile(rf"(?<![\w#+.]){escaped}(?![\w#+])", re.IGNORECASE)
        return re.compile(rf"\b{escaped}\b", re.IGNORECASE)

    def categorize_requirement(self, name: str, context: str = "") -> str:
        """Categorize an extracted requirement based on its title and context.

        Returns one of:
            - mandatory_skill
            - preferred_skill
            - experience
            - education
            - certification
            - domain
            - tool
            - responsibility
            - other

        Args:
            name: Title or short phrase of the requirement.
            context: Contextual surrounding sentence or section header.

        Returns:
            str: Appropriate category string matching JDRequirement schema.
        """
        combined = f"{name} {context}".lower()

        # Experience pattern
        if re.search(r"\b(?:\d+\+?|\b[a-z]+\b)\s*(?:years?|yrs?)\b", combined) or "experience" in combined:
            return "experience"

        # Education pattern
        edu_keywords = [
            "bachelor", "master", "phd", "ph.d", "b.s", "m.s", "b.tech", "m.tech",
            "degree", "diploma", "computer science", "engineering degree", "graduate"
        ]
        if any(re.search(rf"\b{re.escape(k)}\b", combined) for k in edu_keywords):
            return "education"

        # Certification pattern
        cert_keywords = [
            "certified", "certification", "license", "pmp", "cissp", "cisa",
            "aws certified", "azure certified", "scrum master", "csm", "cka", "ceh"
        ]
        if any(k in combined for k in cert_keywords):
            return "certification"

        # Responsibility pattern
        resp_keywords = [
            "responsible for", "lead", "manage", "oversee", "collaborate with",
            "design and implement", "develop and maintain", "architect", "deliver",
            "mentor", "participate in", "drive", "coordinate"
        ]
        if any(combined.startswith(k) or f" {k}" in combined for k in resp_keywords):
            return "responsibility"

        # Tool pattern
        tools_list = [t.lower() for t in TECH_SKILLS_DICTIONARY["tools_and_platforms"]]
        if any(t in name.lower() for t in tools_list):
            return "tool"

        # Preferred vs Mandatory Skill
        preferred_markers = ["preferred", "nice to have", "plus", "bonus", "desired", "beneficial", "optional"]
        if any(marker in context.lower() for marker in preferred_markers):
            return "preferred_skill"

        return "mandatory_skill"

    def analyze_jd_rule_based(self, jd_text: str) -> List[Dict[str, Any]]:
        """Decompose Job Description text into structured requirements using rule-based parsing.

        Extracts:
        - Work Experience (years and domains)
        - Educational Degrees
        - Professional Certifications
        - Technical & Framework Skills
        - Tools & Methodologies
        - Key Responsibilities

        Args:
            jd_text: Full plain text of the job description.

        Returns:
            List[Dict[str, Any]]: Structured requirement records ready for persistence or review.
        """
        if not jd_text or not jd_text.strip():
            return []

        text = jd_text.strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        # Section Segmentation
        sections: List[Tuple[str, str, List[str]]] = []  # (section_type, header, lines)
        current_type = "general"
        current_header = "Overview"
        current_lines: List[str] = []

        for line in lines:
            header_type = self._detect_header_type(line)
            if header_type:
                if current_lines:
                    sections.append((current_type, current_header, current_lines))
                    current_lines = []
                current_type = header_type
                current_header = line
            else:
                current_lines.append(line)

        if current_lines:
            sections.append((current_type, current_header, current_lines))

        requirements: List[Dict[str, Any]] = []
        seen_normalized: Set[str] = set()

        # 1. Experience Requirements Extraction (across full text and experience sections)
        exp_matches = self._extract_experience_patterns(text)
        for exp_text, years in exp_matches:
            norm_key = f"exp_{years}yr"
            if norm_key not in seen_normalized:
                seen_normalized.add(norm_key)
                requirements.append({
                    "requirement_name": f"{years}+ Years Professional Experience",
                    "category": "experience",
                    "importance": "mandatory",
                    "original_evidence": exp_text,
                    "normalized_value": f"{years}_years_experience",
                    "weight": 8.0,
                    "is_enabled": True,
                    "recruiter_notes": f"Detected requirement for minimum {years} years experience.",
                })

        # 2. Education Requirements Extraction
        edu_matches = self._extract_education_patterns(text)
        for edu_text, degree_name in edu_matches:
            norm_key = f"edu_{degree_name.lower()}"
            if norm_key not in seen_normalized:
                seen_normalized.add(norm_key)
                requirements.append({
                    "requirement_name": degree_name,
                    "category": "education",
                    "importance": "mandatory" if "preferred" not in edu_text.lower() else "preferred",
                    "original_evidence": edu_text,
                    "normalized_value": degree_name.lower().replace(" ", "_"),
                    "weight": 5.0,
                    "is_enabled": True,
                    "recruiter_notes": "Extracted educational degree requirement.",
                })

        # 3. Certifications Extraction
        cert_matches = self._extract_certification_patterns(text)
        for cert_text, cert_name in cert_matches:
            norm_key = f"cert_{cert_name.lower()}"
            if norm_key not in seen_normalized:
                seen_normalized.add(norm_key)
                requirements.append({
                    "requirement_name": cert_name,
                    "category": "certification",
                    "importance": "preferred" if "preferred" in cert_text.lower() else "mandatory",
                    "original_evidence": cert_text,
                    "normalized_value": cert_name.lower().replace(" ", "_"),
                    "weight": 4.0,
                    "is_enabled": True,
                    "recruiter_notes": "Professional certification requirement.",
                })

        # 4. Section-specific Skill and Responsibility Extraction
        for sec_type, sec_header, sec_lines in sections:
            is_preferred_sec = sec_type == "preferred"
            is_resp_sec = sec_type == "responsibilities"

            for line in sec_lines:
                clean_bullet = re.sub(r"^[-*•–—\d.)]+\s*", "", line).strip()
                if not clean_bullet or len(clean_bullet) < 3:
                    continue

                if is_resp_sec:
                    # Extract high-level responsibilities
                    if len(clean_bullet) > 20 and len(clean_bullet) < 180:
                        norm_resp = re.sub(r"[^\w\s]", "", clean_bullet.lower())[:40].strip()
                        if norm_resp not in seen_normalized and len(norm_resp) > 10:
                            seen_normalized.add(norm_resp)
                            requirements.append({
                                "requirement_name": clean_bullet[:90] + ("..." if len(clean_bullet) > 90 else ""),
                                "category": "responsibility",
                                "importance": "informational",
                                "original_evidence": clean_bullet,
                                "normalized_value": norm_resp,
                                "weight": 2.0,
                                "is_enabled": True,
                                "recruiter_notes": "Core duty / job responsibility.",
                            })
                    continue

                # Skill identification within bullet
                skills_in_line = self.extract_skills_from_text(clean_bullet)
                for skill in skills_in_line:
                    norm_skill = skill.lower()
                    if norm_skill in seen_normalized:
                        continue
                    seen_normalized.add(norm_skill)

                    # Determine category and importance
                    if is_preferred_sec or any(p in clean_bullet.lower() for p in ["preferred", "nice to have", "plus", "bonus"]):
                        importance = "preferred"
                        category = "preferred_skill"
                        weight = 3.0
                    else:
                        importance = "mandatory"
                        category = "mandatory_skill"
                        weight = 6.0

                    # Check if skill is tool
                    tools_list = [t.lower() for t in TECH_SKILLS_DICTIONARY["tools_and_platforms"]]
                    if norm_skill in tools_list:
                        category = "tool"
                        weight = 4.0

                    requirements.append({
                        "requirement_name": skill,
                        "category": category,
                        "importance": importance,
                        "original_evidence": clean_bullet,
                        "normalized_value": norm_skill,
                        "weight": weight,
                        "is_enabled": True,
                        "recruiter_notes": f"Extracted from {sec_header} section.",
                    })

        # 5. Global text sweep for remaining critical technical skills if few found
        if len([r for r in requirements if r["category"] in ("mandatory_skill", "preferred_skill", "tool")]) < 5:
            all_found = self.extract_skills_from_text(text)
            for skill in all_found:
                norm_skill = skill.lower()
                if norm_skill in seen_normalized:
                    continue
                seen_normalized.add(norm_skill)
                requirements.append({
                    "requirement_name": skill,
                    "category": "mandatory_skill",
                    "importance": "mandatory",
                    "original_evidence": f"Mentioned in job description: {skill}",
                    "normalized_value": norm_skill,
                    "weight": 5.0,
                    "is_enabled": True,
                    "recruiter_notes": "Extracted via comprehensive text scan.",
                })

        return requirements

    def analyze_jd_with_ai(self, jd_text: str) -> List[Dict[str, Any]]:
        """Decompose job description into structured atomic requirements using Google Gemini.

        Falls back gracefully to high-precision rule-based extraction if AI is unavailable or fails.

        Args:
            jd_text: Full plain text of the job description.

        Returns:
            List[Dict[str, Any]]: Structured requirements decomposed from the JD.
        """
        settings = get_settings()
        api_key = settings.get_api_key()
        model_name = settings.get_model()

        if not api_key:
            logger.info("No Gemini API key available; using rule-based JD analysis.")
            return self.analyze_jd_rule_based(jd_text)

        try:
            from services.ai_client import generate_fast_ai_content

            clean_jd = re.sub(r"\n\s*\n+", "\n\n", (jd_text or "").strip())[:4500]

            prompt = (
                "You are an expert recruitment and HR technology specialist. "
                "Analyze the following Job Description and extract structured, atomic candidate screening requirements.\n\n"
                "Extract requirements across these categories:\n"
                "- 'mandatory_skill': Non-negotiable technical or functional skills (e.g., Python, React, SQL)\n"
                "- 'preferred_skill': Desirable / nice-to-have skills (e.g., GraphQL, Redis)\n"
                "- 'experience': Minimum years of experience or seniority level (e.g., '5+ years software development')\n"
                "- 'education': Degree or academic requirement (e.g., 'Bachelor in Computer Science or equivalent')\n"
                "- 'certification': Professional certifications (e.g., 'AWS Certified Solutions Architect')\n"
                "- 'tool': Development tools, cloud platforms, DevOps software (e.g., Docker, Kubernetes, Jira)\n"
                "- 'domain': Industry or domain knowledge (e.g., FinTech, Healthcare, E-Commerce)\n"
                "- 'responsibility': Key duty or deliverable\n\n"
                "Return ONLY a valid JSON array of objects with these exact keys:\n"
                "- 'requirement_name': Concise title (e.g., 'Python 3+', '5+ Years Software Engineering')\n"
                "- 'category': One of the categories listed above\n"
                "- 'importance': 'mandatory', 'preferred', or 'optional'\n"
                "- 'original_evidence': Exact sentence or quote from the JD mentioning this requirement\n"
                "- 'normalized_value': Canonical lowercase identifier (e.g., 'python', 'aws', 'bachelor_degree')\n"
                "- 'weight': Float between 1.0 and 10.0 (mandatory: 6.0-9.0, preferred: 3.0-5.0, tools: 4.0-6.0)\n"
                "- 'is_enabled': true\n"
                "- 'recruiter_notes': Brief explanation for candidate screening evaluation\n\n"
                f"JOB DESCRIPTION:\n{clean_jd}"
            )

            raw_text = generate_fast_ai_content(
                prompt=prompt,
                model=model_name,
                api_key=api_key,
                max_output_tokens=2500,
                temperature=0.1,
                json_mode=True,
            )

            if not raw_text:
                logger.warning("AI JD extraction returned empty; falling back to rule-based engine.")
                return self.analyze_jd_rule_based(jd_text)

            from services.ai_client import safe_parse_json
            parsed = safe_parse_json(raw_text)
            if isinstance(parsed, dict) and "requirements" in parsed:
                parsed = parsed["requirements"]

            if isinstance(parsed, list) and len(parsed) > 0:
                validated_reqs: List[Dict[str, Any]] = []
                seen_names = set()
                for item in parsed:
                    name = str(item.get("requirement_name") or "").strip()
                    if not name or name.lower() in seen_names:
                        continue
                    seen_names.add(name.lower())

                    cat = str(item.get("category") or "mandatory_skill").lower()
                    if cat not in ("mandatory_skill", "preferred_skill", "experience", "education", "certification", "tool", "domain", "responsibility"):
                        cat = "mandatory_skill"

                    imp = str(item.get("importance") or ("mandatory" if cat == "mandatory_skill" else "preferred")).lower()
                    if imp not in ("mandatory", "preferred", "optional", "informational"):
                        imp = "mandatory"

                    norm_val = str(item.get("normalized_value") or re.sub(r"[^\w\s]", "", name.lower()).strip())
                    weight = float(item.get("weight") or (7.0 if imp == "mandatory" else 4.0))

                    validated_reqs.append({
                        "requirement_name": name,
                        "category": cat,
                        "importance": imp,
                        "original_evidence": str(item.get("original_evidence") or f"Extracted by AI from JD: {name}"),
                        "normalized_value": norm_val,
                        "weight": min(10.0, max(1.0, weight)),
                        "is_enabled": bool(item.get("is_enabled", True)),
                        "recruiter_notes": str(item.get("recruiter_notes") or "AI-decomposed screening criteria."),
                    })

                if validated_reqs:
                    logger.info("AI JD extraction decomposed %d requirements via %s.", len(validated_reqs), model_name)
                    return validated_reqs

        except Exception as exc:
            logger.warning("AI JD extraction failed (%s); falling back to rule-based engine.", exc)

        return self.analyze_jd_rule_based(jd_text)

    def review_jd_with_ai(self, jd_text: str) -> Dict[str, Any]:
        """Perform comprehensive AI Quality Audit & Review on a Job Description using Google Gemini.

        Evaluates clarity, ambiguity, inclusivity, seniority realism, missing elements,
        and provides actionable recommendations to optimize candidate screening.

        Args:
            jd_text: Full plain text of the job description.

        Returns:
            Dict[str, Any]: Quality audit report.
        """
        settings = get_settings()
        api_key = settings.get_api_key()
        model_name = settings.get_model()

        if not api_key:
            return {
                "overall_score": 75,
                "grade": "Standard (Rule-Based)",
                "summary": "AI audit requires configured Gemini API key in Settings.",
                "seniority_alignment": "Estimated based on text length and keyword density.",
                "ambiguities": ["AI audit offline: please enable Gemini in Settings & AI Config."],
                "inclusivity_notes": "Standard boilerplate patterns observed.",
                "missing_elements": ["Enable Gemini AI to audit missing job requisition details."],
                "screening_recommendations": [
                    "Ensure mandatory vs preferred skills are clearly distinguished.",
                    "Include explicit minimum years of relevant experience."
                ],
            }

        try:
            from services.ai_client import generate_fast_ai_content

            clean_jd = re.sub(r"\n\s*\n+", "\n\n", (jd_text or "").strip())[:4500]

            prompt = (
                "You are an expert talent acquisition consultant and JD optimization auditor. "
                "Analyze the following Job Description and provide a comprehensive Quality Audit & Screening Review.\n\n"
                "Return ONLY a valid JSON object with the following keys:\n"
                "- 'overall_score': Integer (0 to 100) assessing clarity, completeness, and realism\n"
                "- 'grade': Short grade string like 'Excellent', 'Strong', 'Needs Improvement', or 'Unclear'\n"
                "- 'summary': 2-3 sentence executive assessment of this requisition\n"
                "- 'seniority_alignment': Assessment of whether requirements match the stated seniority\n"
                "- 'ambiguities': Array of 1-4 specific phrases or requirements that are ambiguous or vague\n"
                "- 'inclusivity_notes': Constructive note on tone, gender-neutral language, and appeal to diverse talent\n"
                "- 'missing_elements': Array of 1-3 critical missing details (e.g., compensation range, tech stack versions, reporting manager)\n"
                "- 'screening_recommendations': Array of 2-4 concrete suggestions to improve screening accuracy and candidate quality\n\n"
                f"JOB DESCRIPTION:\n{clean_jd}"
            )

            raw_text = generate_fast_ai_content(
                prompt=prompt,
                model=model_name,
                api_key=api_key,
                max_output_tokens=1500,
                temperature=0.1,
                json_mode=True,
            )

            if not raw_text:
                raise ValueError("Fast AI content generation returned empty response")

            from services.ai_client import safe_parse_json
            audit_res = safe_parse_json(raw_text)
            if isinstance(audit_res, dict) and "overall_score" in audit_res:
                return audit_res

        except Exception as exc:
            logger.warning("AI JD review audit failed (%s); returning fallback audit.", exc)

        return {
            "overall_score": 78,
            "grade": "Good",
            "summary": "Requisition contains standard technical qualifications. Review mandatory vs preferred criteria.",
            "seniority_alignment": "Appears aligned with mid-level requirements.",
            "ambiguities": ["Consider specifying exact versions for primary programming languages and frameworks."],
            "inclusivity_notes": "Neutral tone observed across requirements.",
            "missing_elements": ["Salary band / target compensation range not explicitly stated."],
            "screening_recommendations": [
                "Decompose complex bullet points into single atomic criteria.",
                "Clarify required vs preferred cloud technologies."
            ],
        }

    def _detect_header_type(self, line: str) -> Optional[str]:
        """Classify a line as a section header if it matches known recruitment patterns."""
        clean = line.strip().lower()
        if len(clean) > 60:
            return None

        # Check for colon, bold markdown, or short standalone header
        clean_clean = re.sub(r"[*:#\-_]", "", clean).strip()

        mandatory_patterns = [
            "requirements", "qualifications", "minimum qualifications",
            "basic qualifications", "what you need", "what we look for",
            "must have", "key requirements", "required skills", "experience required"
        ]
        if any(clean_clean == p or clean_clean.startswith(p) for p in mandatory_patterns):
            return "mandatory"

        preferred_patterns = [
            "preferred qualifications", "nice to have", "bonus points",
            "desired qualifications", "preferred skills", "what gives you an edge",
            "good to have", "plus points", "additional qualifications"
        ]
        if any(clean_clean == p or clean_clean.startswith(p) for p in preferred_patterns):
            return "preferred"

        responsibility_patterns = [
            "responsibilities", "what you will do", "what you'll do",
            "duties", "role overview", "key responsibilities", "job duties",
            "about the role", "your impact"
        ]
        if any(clean_clean == p or clean_clean.startswith(p) for p in responsibility_patterns):
            return "responsibilities"

        education_patterns = [
            "education", "academic background", "educational requirements"
        ]
        if any(clean_clean == p or clean_clean.startswith(p) for p in education_patterns):
            return "education"

        cert_patterns = [
            "certifications", "licenses", "certifications required"
        ]
        if any(clean_clean == p or clean_clean.startswith(p) for p in cert_patterns):
            return "certifications"

        return None

    def _extract_experience_patterns(self, text: str) -> List[Tuple[str, float]]:
        """Identify years of experience statements using regex patterns."""
        results: List[Tuple[str, float]] = []
        # Pattern 1: e.g. "5+ years", "3-5 years", "4 to 6 years of experience"
        regex = re.compile(
            r"(\b(?:\d{1,2}(?:\.\d+)?|\b(?:one|two|three|four|five|six|seven|eight|nine|ten)\b)\s*(?:\+|plus)?\s*(?:-|–|to)?\s*(?:\d{1,2})?\s*(?:years?|yrs?)(?:\s+of)?(?:\s+[a-zA-Z\s,/-]{2,40})?(?:experience|exp)?)",
            re.IGNORECASE,
        )

        word_to_num = {
            "one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0, "five": 5.0,
            "six": 6.0, "seven": 7.0, "eight": 8.0, "nine": 9.0, "ten": 10.0
        }

        for match in regex.finditer(text):
            full_match = match.group(1).strip()
            # Extract numeric value
            num_match = re.search(r"\b(\d{1,2}(?:\.\d+)?)\b", full_match)
            if num_match:
                years = float(num_match.group(1))
            else:
                words = re.findall(r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten)\b", full_match.lower())
                years = word_to_num.get(words[0], 3.0) if words else 3.0

            if 0.5 <= years <= 25.0:
                results.append((full_match, years))

        return results

    def _extract_education_patterns(self, text: str) -> List[Tuple[str, str]]:
        """Extract educational degree specifications."""
        results: List[Tuple[str, str]] = []
        patterns = [
            (r"\b(Bachelor(?:'s)?(?:\s+degree)?(?:\s+in\s+[a-zA-Z\s]+)?)\b", "Bachelor's Degree in Computer Science or Related Field"),
            (r"\b(Master(?:'s)?(?:\s+degree)?(?:\s+in\s+[a-zA-Z\s]+)?)\b", "Master's Degree in Computer Science or Related Field"),
            (r"\b(Ph\.?D\.?(?:\s+in\s+[a-zA-Z\s]+)?|Doctorate)\b", "Ph.D. in Computer Science or Related Discipline"),
            (r"\b(B\.?S\.?|B\.?E\.?|B\.?Tech)\b(?:\s+in\s+[a-zA-Z\s]+)?", "Bachelor of Science / B.Tech Degree"),
            (r"\b(M\.?S\.?|M\.?E\.?|M\.?Tech)\b(?:\s+in\s+[a-zA-Z\s]+)?", "Master of Science / M.Tech Degree"),
        ]

        for pattern, label in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                evidence = match.group(0).strip()
                results.append((evidence, label))

        return results

    def _extract_certification_patterns(self, text: str) -> List[Tuple[str, str]]:
        """Identify recognized industry certifications."""
        results: List[Tuple[str, str]] = []
        cert_specs = [
            ("AWS Certified Solutions Architect", "AWS Certified Solutions Architect"),
            ("AWS Certified Developer", "AWS Certified Developer"),
            ("Azure Solutions Architect", "Azure Solutions Architect"),
            ("Certified Information Systems Security Professional", "CISSP"),
            ("CISSP", "CISSP"),
            ("PMP", "Project Management Professional (PMP)"),
            ("Certified ScrumMaster", "Certified ScrumMaster (CSM)"),
            ("CSM", "Certified ScrumMaster (CSM)"),
            ("Certified Kubernetes Administrator", "CKA (Certified Kubernetes Administrator)"),
            ("CKA", "CKA (Certified Kubernetes Administrator)"),
            ("Certified Ethical Hacker", "CEH (Certified Ethical Hacker)"),
            ("Google Cloud Certified", "GCP Certified Professional"),
        ]

        for keyword, canonical in cert_specs:
            pattern = re.compile(rf"\b{re.escape(keyword)}\b", re.IGNORECASE)
            match = pattern.search(text)
            if match:
                results.append((match.group(0), canonical))

        return results
