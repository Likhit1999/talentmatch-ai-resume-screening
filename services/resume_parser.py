"""Resume parser service for TalentMatch AI.

Provides multi-format document text extraction (PDF, DOCX, TXT),
validation, deduplication hashing, and heuristic entity extraction for
candidate profiles (name, email, phone, skills, experience, education, certifications).
"""

import hashlib
import io
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import zipfile

import docx
import pypdf

logger = logging.getLogger(__name__)

# Comprehensive technology and domain skills dictionary (350+ skills)
COMMON_SKILLS: Set[str] = {
    # Programming Languages
    "Python", "Java", "C", "C++", "C#", "JavaScript", "TypeScript", "Go", "Golang",
    "Rust", "Ruby", "PHP", "Swift", "Kotlin", "Scala", "R", "MATLAB", "Dart",
    "Julia", "Perl", "Shell Scripting", "Bash", "PowerShell", "Groovy", "Lua",
    "Haskell", "Elixir", "Clojure", "Solidity", "Assembly", "SQL", "HTML", "HTML5",
    "CSS", "CSS3", "Sass", "SCSS", "Less",

    # Web & Frontend Frameworks / Libraries
    "React", "React.js", "Next.js", "Angular", "AngularJS", "Vue.js", "Vue", "Nuxt.js",
    "Svelte", "SvelteKit", "Remix", "Gatsby", "jQuery", "Redux", "Redux Toolkit",
    "MobX", "Zustand", "Tailwind CSS", "Bootstrap", "Material UI", "Chakra UI",
    "Ant Design", "Webpack", "Vite", "Rollup", "Babel", "Three.js", "D3.js",
    "WebSockets", "Progressive Web Apps", "PWA", "Responsive Web Design",

    # Backend Frameworks & Runtimes
    "Node.js", "Express.js", "NestJS", "FastAPI", "Django", "Django REST Framework",
    "Flask", "Tornado", "Celery", "Spring", "Spring Boot", "Hibernate", "Micronaut",
    "Quarkus", "ASP.NET", "ASP.NET Core", ".NET Core", ".NET", "Ruby on Rails",
    "Laravel", "Symfony", "Gin", "Echo", "Fiber", "Actix Web", "Rocket", "Phoenix",

    # Databases & Caching
    "PostgreSQL", "MySQL", "SQLite", "MongoDB", "Redis", "Cassandra", "Elasticsearch",
    "OpenSearch", "DynamoDB", "Oracle Database", "Microsoft SQL Server", "MS SQL",
    "MariaDB", "Neo4j", "Couchbase", "Firebase Realtime Database", "Firestore",
    "Supabase", "Snowflake", "Google BigQuery", "Amazon Redshift", "ClickHouse",
    "Memcached", "RocksDB", "CockroachDB", "Vector Database", "Pinecone", "ChromaDB",
    "Weaviate", "Milvus", "Qdrant", "FAISS",

    # Cloud Computing & Infrastructure
    "AWS", "Amazon Web Services", "Microsoft Azure", "Google Cloud Platform", "GCP",
    "DigitalOcean", "Heroku", "Cloudflare", "OpenStack", "IBM Cloud", "Alibaba Cloud",
    "Vercel", "Netlify", "AWS Lambda", "Azure Functions", "Google Cloud Functions",
    "Amazon S3", "Amazon EC2", "Amazon RDS", "Amazon ECS", "Amazon EKS", "Amazon SQS",
    "Amazon SNS", "Serverless Architecture", "CloudFormation",

    # DevOps, CI/CD & Orchestration
    "Docker", "Kubernetes", "K8s", "Helm", "Terraform", "Ansible", "Jenkins",
    "GitHub Actions", "GitLab CI/CD", "CircleCI", "Travis CI", "ArgoCD", "Vagrant",
    "Puppet", "Chef", "Nginx", "Apache HTTP Server", "Traefik", "HAProxy", "Envoy",
    "Istio", "Prometheus", "Grafana", "Datadog", "Splunk", "ELK Stack", "Logstash",
    "Kibana", "New Relic", "Sentry",

    # Data Engineering & Distributed Systems
    "Apache Spark", "PySpark", "Apache Kafka", "Apache Hadoop", "Apache Flink",
    "Apache Airflow", "Apache Hive", "Apache Beam", "RabbitMQ", "dbt", "Databricks",
    "Presto", "Trino", "ETL Pipelines", "Data Warehousing", "Data Lakes",
    "Delta Lake", "Apache Parquet", "Kafka Streams",

    # Machine Learning, AI & Data Science
    "Machine Learning", "Deep Learning", "Artificial Intelligence", "Natural Language Processing",
    "NLP", "Computer Vision", "Generative AI", "Large Language Models", "LLMs",
    "PyTorch", "TensorFlow", "Keras", "Scikit-Learn", "XGBoost", "LightGBM", "CatBoost",
    "OpenCV", "Pandas", "NumPy", "SciPy", "Matplotlib", "Seaborn", "NLTK", "Spacy",
    "Hugging Face", "Transformers", "LangChain", "LlamaIndex", "OpenAI API",
    "Gemini API", "Claude API", "Ollama", "Fine-Tuning", "RAG", "MLflow",
    "Kubeflow", "Weights & Biases", "Prompt Engineering", "Reinforcement Learning",
    "Data Analysis", "Predictive Modeling", "Statistics", "A/B Testing",

    # Architecture, Protocols & API Design
    "Microservices", "RESTful APIs", "REST API", "GraphQL", "gRPC", "SOAP",
    "Event-Driven Architecture", "Service-Oriented Architecture", "Domain-Driven Design",
    "Message Queues", "Design Patterns", "System Design", "Distributed Systems",
    "Object-Oriented Programming", "Functional Programming",

    # Testing & Code Quality
    "Unit Testing", "Integration Testing", "End-to-End Testing", "TDD", "BDD",
    "pytest", "unittest", "JUnit", "Jest", "Mocha", "Chai", "Cypress", "Selenium",
    "Playwright", "Postman", "JMeter", "SonarQube", "Code Review", "Static Analysis",

    # Tools, Version Control & Methodologies
    "Git", "GitHub", "GitLab", "Bitbucket", "SVN", "Jira", "Confluence", "Trello",
    "Asana", "Agile", "Scrum", "Kanban", "Sprint Planning", "CI/CD", "DevOps",
    "MLOps", "Linux", "Unix", "Windows Server",

    # Security & Identity
    "Cybersecurity", "OAuth 2.0", "OAuth", "OpenID Connect", "JWT", "JSON Web Tokens",
    "SAML", "SSL/TLS", "Penetration Testing", "OWASP", "Vulnerability Assessment",
    "Cryptography", "IAM", "Identity and Access Management", "Zero Trust",
    "Network Security", "Firewalls", "VPN",

    # Mobile & Cross-Platform Development
    "Android Development", "iOS Development", "React Native", "Flutter",
    "Ionic", "Xamarin", "Mobile App Development",

    # Soft Skills & Leadership
    "Leadership", "Team Leadership", "Mentoring", "Project Management",
    "Stakeholder Management", "Problem Solving", "Critical Thinking",
    "Cross-Functional Collaboration", "Effective Communication", "Time Management",
    "Agile Coaching", "Technical Writing", "Documentation"
}


class ResumeParserService:
    """Service providing document text extraction, sanitization, and structured entity extraction."""

    # Section header patterns
    SECTION_PATTERNS = {
        "experience": re.compile(
            r"^(?:work\s+experience|professional\s+experience|employment\s+history|experience|career\s+history|work\s+history|professional\s+background)\b",
            re.IGNORECASE | re.MULTILINE,
        ),
        "education": re.compile(
            r"^(?:education|academic\s+background|academic\s+qualifications|educational\s+qualifications|academics|degrees|qualifications)\b",
            re.IGNORECASE | re.MULTILINE,
        ),
        "skills": re.compile(
            r"^(?:technical\s+skills|skills\s+&\s+technologies|skills\s+and\s+tools|core\s+competencies|key\s+skills|skills|technologies|proficiencies|technical\s+proficiencies)\b",
            re.IGNORECASE | re.MULTILINE,
        ),
        "certifications": re.compile(
            r"^(?:certifications?|licenses(?:\s*&\s*certifications)?|professional\s+certifications|certificates|credentials|courses\s*&\s*certifications)\b",
            re.IGNORECASE | re.MULTILINE,
        ),
        "summary": re.compile(
            r"^(?:professional\s+summary|executive\s+summary|summary\s+of\s+qualifications|career\s+summary|profile|about\s+me|career\s+objective|objective|summary)\b",
            re.IGNORECASE | re.MULTILINE,
        ),
        "projects": re.compile(
            r"^(?:projects|key\s+projects|personal\s+projects|academic\s+projects|technical\s+projects)\b",
            re.IGNORECASE | re.MULTILINE,
        ),
    }

    # Email pattern
    EMAIL_PATTERN = re.compile(
        r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
        re.IGNORECASE,
    )

    # Phone pattern (supports US, India, and general international with separators)
    PHONE_PATTERN = re.compile(
        r"(?:(?:\+|00)\d{1,3}[-.\s]?)?(?:\(?\d{2,5}\)?[-.\s]?)?\d{3,5}[-.\s]?\d{4,5}\b"
    )

    # Degree matching patterns
    DEGREE_PATTERNS = [
        re.compile(r"\b(?:b\.?tech|b\.?e|bachelor\s+of\s+engineering|bachelor\s+of\s+technology)\b", re.IGNORECASE),
        re.compile(r"\b(?:b\.?s\.?c|b\.?s|bachelor\s+of\s+science)\b", re.IGNORECASE),
        re.compile(r"\b(?:b\.?a|bachelor\s+of\s+arts)\b", re.IGNORECASE),
        re.compile(r"\b(?:bba|bca|b\.?com|bachelor\s+of\s+commerce)\b", re.IGNORECASE),
        re.compile(r"\b(?:m\.?tech|m\.?e|master\s+of\s+engineering|master\s+of\s+technology)\b", re.IGNORECASE),
        re.compile(r"\b(?:m\.?s\.?c|m\.?s|master\s+of\s+science)\b", re.IGNORECASE),
        re.compile(r"\b(?:mba|master\s+of\s+business\s+administration)\b", re.IGNORECASE),
        re.compile(r"\b(?:mca|m\.?com|master\s+of\s+arts|m\.?a)\b", re.IGNORECASE),
        re.compile(r"\b(?:ph\.?d|doctorate|doctor\s+of\s+philosophy)\b", re.IGNORECASE),
        re.compile(r"\b(?:diploma|associate\s+degree|high\s+school)\b", re.IGNORECASE),
    ]

    # Year / Duration patterns
    DURATION_PATTERN = re.compile(
        r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+)?\b(?:19|20)\d{2}\b\s*(?:[-–—to]+\s*(?:(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+)?\b(?:19|20)\d{2}\b|present|current|now|ongoing))?",
        re.IGNORECASE,
    )

    YEAR_PATTERN = re.compile(r"\b(19\d{2}|20\d{2})\b")

    def __init__(self, common_skills: Optional[Set[str]] = None) -> None:
        """Initialize parser service with skills vocabulary.

        Args:
            common_skills: Optional customized set of skill keywords.
        """
        self.skills_pool: Set[str] = common_skills or COMMON_SKILLS
        # Precompile skill regexes for efficient and accurate boundary matching
        self._compiled_skill_patterns: List[Tuple[str, re.Pattern]] = self._build_skill_regexes(self.skills_pool)

    def _build_skill_regexes(self, skills: Set[str]) -> List[Tuple[str, re.Pattern]]:
        """Compile regex patterns with boundary handling for skill matching."""
        compiled = []
        for skill in skills:
            # Handle special symbols like C++, C#, .NET
            escaped = re.escape(skill)
            if re.match(r"^\w", skill) and re.search(r"\w$", skill):
                pattern = re.compile(rf"\b{escaped}\b", re.IGNORECASE)
            elif re.match(r"^\w", skill):
                pattern = re.compile(rf"\b{escaped}(?=[\s.,;!?/\\]|$)", re.IGNORECASE)
            elif re.search(r"\w$", skill):
                pattern = re.compile(rf"(?:^|[\s.,;!?/\\]){escaped}\b", re.IGNORECASE)
            else:
                pattern = re.compile(rf"(?:^|\s){escaped}(?=\s|$)", re.IGNORECASE)
            compiled.append((skill, pattern))
        return compiled

    @staticmethod
    def compute_file_hash(file_bytes: bytes) -> str:
        """Compute SHA-256 hexadecimal hash digest of file bytes.

        Args:
            file_bytes: Raw file byte stream.

        Returns:
            str: 64-character hexadecimal SHA-256 hash.
        """
        return hashlib.sha256(file_bytes).hexdigest()

    @staticmethod
    def extract_from_zip(zip_bytes: bytes, zip_filename: str = "resumes.zip") -> Tuple[List[Dict[str, Any]], List[str]]:
        """Extract individual resume files from a ZIP archive.

        Filters for supported formats (PDF, DOCX, TXT) and skips system / hidden files.

        Args:
            zip_bytes: Raw binary content of the ZIP archive.
            zip_filename: Name of the ZIP archive for reporting.

        Returns:
            Tuple of:
                - List of dicts: [{"filename": name, "bytes": file_bytes, "size": size}, ...]
                - List of warnings / skipped file messages
        """
        extracted_files: List[Dict[str, Any]] = []
        warnings: List[str] = []

        if not zip_bytes:
            warnings.append(f"Archive '{zip_filename}' is empty (0 bytes).")
            return extracted_files, warnings

        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
                names = z.namelist()
                for member_name in names:
                    # Skip directory entries
                    if member_name.endswith("/") or member_name.endswith("\\"):
                        continue

                    # Skip macOS resource fork or hidden files
                    pure_name = Path(member_name).name
                    if pure_name.startswith(".") or "__MACOSX" in member_name:
                        continue

                    ext = Path(member_name).suffix.lower().lstrip(".")
                    if ext not in ("pdf", "docx", "txt"):
                        warnings.append(f"Skipped non-resume file '{member_name}' (unsupported format .{ext})")
                        continue

                    try:
                        file_data = z.read(member_name)
                        extracted_files.append({
                            "filename": pure_name,
                            "bytes": file_data,
                            "size": len(file_data),
                            "inner_path": member_name,
                        })
                    except Exception as read_err:
                        warnings.append(f"Could not read '{member_name}' from archive: {read_err}")

        except zipfile.BadZipFile:
            warnings.append(f"File '{zip_filename}' is not a valid or readable ZIP archive.")
        except Exception as zip_err:
            warnings.append(f"Error extracting ZIP archive '{zip_filename}': {zip_err}")

        return extracted_files, warnings

    @staticmethod
    def validate_file(file_bytes: bytes, filename: str, max_size_mb: int = 10) -> Dict[str, Any]:
        """Validate file size, extension, and content structure.

        Args:
            file_bytes: Raw file content bytes.
            filename: Original file name.
            max_size_mb: Maximum permitted size in megabytes.

        Returns:
            dict with:
                - valid (bool)
                - file_type (str or None)
                - file_size (int)
                - error (str or None)
        """
        file_size = len(file_bytes) if file_bytes else 0

        # Check empty file
        if not file_bytes or file_size == 0:
            return {
                "valid": False,
                "file_type": None,
                "file_size": 0,
                "error": "File is empty (0 bytes). Please upload a valid document.",
            }

        # Check maximum size
        max_bytes = max_size_mb * 1024 * 1024
        if file_size > max_bytes:
            return {
                "valid": False,
                "file_type": None,
                "file_size": file_size,
                "error": (
                    f"File size ({file_size / (1024 * 1024):.1f} MB) exceeds maximum "
                    f"allowed limit ({max_size_mb} MB)."
                ),
            }

        # Check extension
        ext = Path(filename).suffix.lower().lstrip(".")
        if ext not in ("pdf", "docx", "txt"):
            return {
                "valid": False,
                "file_type": ext,
                "file_size": file_size,
                "error": f"Unsupported file format '.{ext}'. Supported formats: PDF, DOCX, TXT.",
            }

        # Basic magic number / signature verification
        if ext == "pdf":
            if not file_bytes.startswith(b"%PDF-"):
                return {
                    "valid": False,
                    "file_type": "pdf",
                    "file_size": file_size,
                    "error": "File has .pdf extension but does not contain a valid PDF header (%PDF-).",
                }
        elif ext == "docx":
            # DOCX is a zip archive, starting with PK\x03\x04
            if not file_bytes.startswith(b"PK\x03\x04"):
                return {
                    "valid": False,
                    "file_type": "docx",
                    "file_size": file_size,
                    "error": "File has .docx extension but is not a valid Microsoft Word OpenXML archive.",
                }
        elif ext == "txt":
            # Check for excessive binary null bytes
            if b"\x00" in file_bytes[:1024]:
                return {
                    "valid": False,
                    "file_type": "txt",
                    "file_size": file_size,
                    "error": "File contains binary null bytes and does not appear to be plain text.",
                }

        return {
            "valid": True,
            "file_type": ext,
            "file_size": file_size,
            "error": None,
        }

    def parse_pdf(self, file_bytes: bytes, filename: str) -> Dict[str, Any]:
        """Extract text and metadata from a PDF file using pypdf.

        Args:
            file_bytes: PDF file binary data.
            filename: Original PDF filename.

        Returns:
            dict containing:
                - text: Extracted text string
                - page_count: Total pages
                - is_scanned: True if minimal extractable text detected
                - warnings: List of warning strings
        """
        warnings: List[str] = []
        extracted_pages: List[str] = []
        page_count = 0
        is_scanned = False

        try:
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            page_count = len(reader.pages)

            if reader.is_encrypted:
                try:
                    # Attempt decryption with empty password
                    reader.decrypt("")
                except Exception:
                    warnings.append(f"PDF '{filename}' is password protected or encrypted.")

            for page_idx, page in enumerate(reader.pages):
                try:
                    page_text = page.extract_text() or ""
                    extracted_pages.append(page_text)
                except Exception as page_exc:
                    warnings.append(f"Could not extract text from page {page_idx + 1}: {page_exc}")

        except Exception as exc:
            logger.error("Failed to parse PDF '%s': %s", filename, exc, exc_info=True)
            warnings.append(f"Error parsing PDF file: {str(exc)}")
            return {
                "text": "",
                "page_count": page_count,
                "is_scanned": False,
                "warnings": warnings,
            }

        full_text = "\n".join(extracted_pages).strip()

        # Scanned document detection heuristic
        # If there are pages but very few characters per page on average
        if page_count > 0:
            avg_chars = len(full_text) / page_count
            if avg_chars < 60 or len(full_text) < 100:
                is_scanned = True
                warnings.append(
                    f"PDF appears to be scanned or image-based ({len(full_text)} characters extracted across {page_count} pages). "
                    "Text extraction may be incomplete."
                )

        return {
            "text": full_text,
            "page_count": page_count,
            "is_scanned": is_scanned,
            "warnings": warnings,
        }

    def parse_docx(self, file_bytes: bytes, filename: str) -> Dict[str, Any]:
        """Extract text from DOCX paragraphs and tables using python-docx.

        Args:
            file_bytes: DOCX file binary data.
            filename: Original DOCX filename.

        Returns:
            dict containing:
                - text: Extracted text string
                - warnings: List of warning strings
        """
        warnings: List[str] = []
        text_chunks: List[str] = []

        try:
            doc = docx.Document(io.BytesIO(file_bytes))

            # Extract paragraphs
            for p in doc.paragraphs:
                cleaned = p.text.strip()
                if cleaned:
                    text_chunks.append(cleaned)

            # Extract table contents (useful for resume layouts using tables)
            for table in doc.tables:
                for row in table.rows:
                    row_cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                    if row_cells:
                        text_chunks.append(" | ".join(row_cells))

        except Exception as exc:
            logger.error("Failed to parse DOCX '%s': %s", filename, exc, exc_info=True)
            warnings.append(f"Error parsing DOCX file: {str(exc)}")
            return {
                "text": "",
                "warnings": warnings,
            }

        full_text = "\n".join(text_chunks).strip()
        if not full_text:
            warnings.append(f"DOCX '{filename}' contained no extractable paragraph or table text.")

        return {
            "text": full_text,
            "warnings": warnings,
        }

    def parse_txt(self, file_bytes: bytes, filename: str) -> Dict[str, Any]:
        """Decode plain text file with fallback encoding handling.

        Args:
            file_bytes: Plain text binary data.
            filename: Original filename.

        Returns:
            dict containing:
                - text: Extracted decoded text
                - warnings: List of warning strings
        """
        warnings: List[str] = []
        text = ""

        # Try UTF-8 first
        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            # Fallback to Latin-1
            try:
                text = file_bytes.decode("latin-1")
                warnings.append("Decoded using Latin-1 encoding fallback.")
            except UnicodeDecodeError:
                # Fallback to CP1252 / replace
                text = file_bytes.decode("cp1252", errors="replace")
                warnings.append("Decoded with replacement character fallback due to encoding conflicts.")

        return {
            "text": text.strip(),
            "warnings": warnings,
        }

    def parse_file(self, file_bytes: bytes, filename: str) -> Dict[str, Any]:
        """Orchestrate validation and format-specific parsing.

        Args:
            file_bytes: Raw file content bytes.
            filename: Original filename.

        Returns:
            dict with:
                - valid: bool
                - text: str
                - file_type: str
                - page_count: int
                - is_scanned: bool
                - warnings: list[str]
                - error: str or None
        """
        val = self.validate_file(file_bytes, filename)
        if not val["valid"]:
            return {
                "valid": False,
                "text": "",
                "file_type": val["file_type"],
                "page_count": 0,
                "is_scanned": False,
                "warnings": [],
                "error": val["error"],
            }

        ext = val["file_type"]
        warnings = []
        is_scanned = False
        page_count = 1

        if ext == "pdf":
            parsed = self.parse_pdf(file_bytes, filename)
            text = parsed["text"]
            page_count = parsed["page_count"]
            is_scanned = parsed["is_scanned"]
            warnings.extend(parsed["warnings"])
        elif ext == "docx":
            parsed = self.parse_docx(file_bytes, filename)
            text = parsed["text"]
            warnings.extend(parsed["warnings"])
        elif ext == "txt":
            parsed = self.parse_txt(file_bytes, filename)
            text = parsed["text"]
            warnings.extend(parsed["warnings"])
        else:
            return {
                "valid": False,
                "text": "",
                "file_type": ext,
                "page_count": 0,
                "is_scanned": False,
                "warnings": [],
                "error": f"Unsupported file type: {ext}",
            }

        return {
            "valid": True,
            "text": text,
            "file_type": ext,
            "page_count": page_count,
            "is_scanned": is_scanned,
            "warnings": warnings,
            "error": None,
        }

    def extract_candidate_info(self, text: str) -> Dict[str, Any]:
        """Extract structured candidate profile information from raw resume text.

        Args:
            text: Raw resume plain text.

        Returns:
            dict containing:
                - name: Extracted candidate full name
                - email: Extracted email address or None
                - phone: Extracted contact phone or None
                - skills: List of identified technology skills
                - experience: List of dicts {title, company, duration, description}
                - education: List of dicts {degree, institution, year}
                - certifications: List of certification strings
                - summary: Resume summary or top profile excerpt
        """
        if not text or not text.strip():
            return {
                "name": "Unknown Candidate",
                "email": None,
                "phone": None,
                "skills": [],
                "experience": [],
                "education": [],
                "certifications": [],
                "summary": "",
            }

        cleaned_text = self._clean_text(text)
        sections = self._split_into_sections(cleaned_text)

        # 1. Contact Information
        email = self._extract_email(cleaned_text)
        phone = self._extract_phone(cleaned_text)

        # 2. Candidate Name
        name = self._extract_name(cleaned_text, email)

        # 3. Skills Extraction
        skills = self._extract_skills(cleaned_text, sections.get("skills", ""))

        # 4. Work Experience & Education (with section disentanglement for multi-column resumes)
        raw_edu = sections.get("education", "")
        raw_exp = sections.get("experience", "")
        clean_edu, misplaced_exp = self._separate_education_and_experience(raw_edu)
        if misplaced_exp:
            raw_exp = f"{raw_exp}\n\n{misplaced_exp}" if raw_exp else misplaced_exp

        experience = self._extract_experience(raw_exp)
        education = self._extract_education(clean_edu)

        # 6. Certifications
        certifications = self._extract_certifications(sections.get("certifications", ""))

        # 7. Summary
        summary = self._extract_summary(sections.get("summary", ""), cleaned_text)

        return {
            "name": name,
            "email": email,
            "phone": phone,
            "skills": skills,
            "experience": experience,
            "education": education,
            "certifications": certifications,
            "summary": summary,
        }

    def _clean_text(self, text: str) -> str:
        """Normalize line breaks and sanitize whitespace."""
        # Replace Windows carriage returns and form feeds
        text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n")
        # Replace non-breaking spaces
        text = text.replace("\xa0", " ")
        return text

    def _extract_email(self, text: str) -> Optional[str]:
        """Find the first valid email address."""
        match = self.EMAIL_PATTERN.search(text)
        if match:
            # Strip trailing punctuation if accidentally captured
            return match.group(0).rstrip(".,;").lower()
        return None

    def _extract_phone(self, text: str) -> Optional[str]:
        """Find the candidate contact phone number."""
        matches = self.PHONE_PATTERN.finditer(text)
        for match in matches:
            raw_phone = match.group(0).strip()
            # Clean digits count
            digits = re.sub(r"\D", "", raw_phone)
            # Valid international or domestic phone numbers typically have 10-15 digits
            # Filter out false positives like years (4 digits) or postal codes
            if 10 <= len(digits) <= 15:
                return raw_phone
        return None

    def _extract_name(self, text: str, email: Optional[str] = None) -> str:
        """Extract candidate name using top-line heuristics and title filters."""
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if not lines:
            return "Unknown Candidate"

        ignore_terms = {
            "resume", "curriculum vitae", "cv", "profile", "contact",
            "phone", "email", "address", "page", "portfolio", "summary",
            "linkedin", "github", "personal details", "experience",
            "education", "skills", "declaration", "objective",
        }

        # Check the first 8 lines
        for line in lines[:8]:
            lower_line = line.lower()

            # Skip lines matching ignore keywords or headers
            if any(term in lower_line for term in ignore_terms):
                continue

            # Skip lines with email or URL symbols
            if "@" in line or "http" in lower_line or "www." in lower_line:
                continue

            # Skip lines that are just numbers or phone digits
            digits = re.sub(r"\D", "", line)
            if len(digits) > 4:
                continue

            # Clean prefixes like Mr., Ms., Dr.
            cleaned_line = re.sub(r"^(?:mr\.|ms\.|mrs\.|dr\.|prof\.)\s*", "", line, flags=re.IGNORECASE).strip()

            # Candidate name should have 2 to 4 words, primarily alphabetic characters
            words = [w for w in cleaned_line.split() if w.isalpha()]
            if 2 <= len(words) <= 4 and len(cleaned_line) <= 60:
                # Name should have title casing or uppercase
                if all(w[0].isupper() for w in words):
                    return " ".join(words)
                elif cleaned_line.isupper():
                    return " ".join(w.capitalize() for w in words)

        # Fallback heuristic: Try to infer name from email prefix (e.g. john.doe@email.com)
        if email:
            prefix = email.split("@")[0]
            parts = re.split(r"[._-]", prefix)
            alpha_parts = [p.capitalize() for p in parts if p.isalpha() and len(p) > 1]
            if 2 <= len(alpha_parts) <= 3:
                return " ".join(alpha_parts)

        # If top line is short and has no punctuation
        first_line = lines[0]
        if len(first_line) < 40 and not any(ch in first_line for ch in "@:;,/\\"):
            return first_line

        return "Unknown Candidate"

    def _split_into_sections(self, text: str) -> Dict[str, str]:
        """Segment resume into major semantic sections based on recognized headers."""
        lines = text.split("\n")
        header_positions: List[Tuple[int, str]] = []

        for idx, line in enumerate(lines):
            line_str = line.strip()
            if not line_str or len(line_str) > 60:
                continue

            # Check if line matches any section pattern
            for section_name, pattern in self.SECTION_PATTERNS.items():
                if pattern.match(line_str):
                    header_positions.append((idx, section_name))
                    break

        if not header_positions:
            return {"body": text}

        sections: Dict[str, str] = {}
        for i, (start_idx, sec_name) in enumerate(header_positions):
            end_idx = header_positions[i + 1][0] if (i + 1 < len(header_positions)) else len(lines)
            content = "\n".join(lines[start_idx + 1:end_idx]).strip()
            # If section repeated, append
            if sec_name in sections:
                sections[sec_name] += "\n" + content
            else:
                sections[sec_name] = content

        return sections

    def _extract_skills(self, full_text: str, skills_section: str) -> List[str]:
        """Detect skills using dictionary lookup with exact boundary matching."""
        found_skills: Set[str] = set()

        # Prioritize matching in the dedicated skills section
        search_corpus = f"{skills_section}\n{full_text}" if skills_section else full_text

        for skill, pattern in self._compiled_skill_patterns:
            if pattern.search(search_corpus):
                found_skills.add(skill)

        # Sort alphabetically
        return sorted(list(found_skills), key=lambda s: s.lower())

    def _separate_education_and_experience(self, edu_text: str) -> Tuple[str, str]:
        """Separate academic education lines from misplaced work experience lines."""
        if not edu_text or not edu_text.strip():
            return "", ""

        lines = edu_text.splitlines()
        clean_edu: List[str] = []
        misplaced_exp: List[str] = []
        is_in_work_exp = False

        job_title_pattern = re.compile(
            r"\b(?:engineer|developer|tester|lead|manager|sdet|architect|analyst|specialist|consultant|officer)\b",
            re.IGNORECASE,
        )

        for line in lines:
            line_str = line.strip()
            if not is_in_work_exp:
                has_degree = any(p.search(line_str) for p in self.DEGREE_PATTERNS)
                if (
                    not has_degree
                    and job_title_pattern.search(line_str)
                    and not any(
                        k in line_str.lower()
                        for k in ["degree", "diploma", "university", "college", "school", "polytechnic"]
                    )
                ):
                    is_in_work_exp = True
            if is_in_work_exp:
                misplaced_exp.append(line_str)
            else:
                clean_edu.append(line_str)

        return "\n".join(clean_edu).strip(), "\n".join(misplaced_exp).strip()

    @staticmethod
    def _is_likely_title_or_company(line: str) -> bool:
        """Check if line looks like a job title or employer rather than a bullet point or description."""
        line_s = line.strip()
        if not line_s or len(line_s) > 85:
            return False
        if line_s.endswith("."):
            return False
        if line_s.startswith(("-", "*", "•", "–", "—", "▪", "▸")):
            return False
        action_verbs = (
            "led ", "managed ", "developed ", "built ", "designed ", "diagnosed ",
            "reduced ", "executed ", "supported ", "worked ", "responsible ", "assisted ",
            "created ", "maintained ", "collaborated ", "implemented ", "tested ",
        )
        if line_s.lower().startswith(action_verbs):
            return False
        return True

    def _extract_experience(self, exp_text: str) -> List[Dict[str, str]]:
        """Parse work history entries from experience section."""
        if not exp_text.strip():
            return []

        # Split into blocks: first try \n\s*\n, and if that results in blocks containing multiple date ranges,
        # split further based on date / role boundaries
        raw_blocks = [b.strip() for b in re.split(r"\n\s*\n", exp_text) if b.strip()]
        blocks: List[str] = []

        for b in raw_blocks:
            lines = [l.strip() for l in b.split("\n") if l.strip()]
            date_indices = [i for i, l in enumerate(lines) if self.DURATION_PATTERN.search(l)]
            if len(date_indices) <= 1:
                blocks.append(b)
            else:
                entry_starts = []
                for i, d_idx in enumerate(date_indices):
                    if i == 0:
                        s = d_idx
                        while s > 0 and self._is_likely_title_or_company(lines[s - 1]):
                            s -= 1
                        entry_starts.append(s)
                    else:
                        prev_d = date_indices[i - 1]
                        s = d_idx
                        while s > prev_d + 1 and (d_idx - s) < 2 and self._is_likely_title_or_company(lines[s - 1]):
                            s -= 1
                        if s == d_idx and d_idx > prev_d + 1:
                            s = d_idx - 1
                        entry_starts.append(s)

                for i, s_idx in enumerate(entry_starts):
                    e_idx = entry_starts[i + 1] if i + 1 < len(entry_starts) else len(lines)
                    sub_b = "\n".join(lines[s_idx:e_idx]).strip()
                    if sub_b:
                        blocks.append(sub_b)

        entries: List[Dict[str, str]] = []
        for block in blocks:
            lines = [l.strip() for l in block.split("\n") if l.strip()]
            if not lines:
                continue

            title = ""
            company = ""
            duration = ""
            description_lines = []

            # First line often contains job title and/or company
            first_line = lines[0]
            duration_match = self.DURATION_PATTERN.search(block)
            if duration_match:
                duration = duration_match.group(0).strip()

            # Attempt to separate Title and Company (e.g. "Software Engineer at Google" or "Google - Senior Developer")
            if " at " in first_line:
                parts = first_line.split(" at ", 1)
                title, company = parts[0].strip(), parts[1].strip()
            elif " - " in first_line:
                parts = first_line.split(" - ", 1)
                title, company = parts[0].strip(), parts[1].strip()
            elif " | " in first_line:
                parts = first_line.split(" | ", 1)
                title, company = parts[0].strip(), parts[1].strip()
            elif len(lines) > 1 and not self.DURATION_PATTERN.search(lines[1]):
                title = first_line
                company = lines[1]
                description_lines = lines[2:]
            else:
                title = first_line
                description_lines = lines[1:]

            if not description_lines and len(lines) > 1:
                description_lines = lines[1:]

            description = " ".join(description_lines)
            if title or company or duration:
                entries.append({
                    "title": title[:100] if title else "Role",
                    "company": company[:100] if company else "Organization",
                    "duration": duration[:60] if duration else "Not Specified",
                    "description": description[:500] if description else "",
                })

        return entries[:15]  # Return up to 15 relevant entries

    def _extract_education(self, edu_text: str) -> List[Dict[str, str]]:
        """Parse academic degrees, institutions, and graduation years."""
        if not edu_text.strip():
            return []

        education_list: List[Dict[str, str]] = []
        blocks = [b.strip() for b in re.split(r"\n\s*\n", edu_text) if b.strip()]

        for block in blocks:
            lines = [l.strip() for l in block.split("\n") if l.strip()]
            if not lines:
                continue

            degree = ""
            institution = ""
            year = ""

            # Check for recognized degree names
            for deg_pat in self.DEGREE_PATTERNS:
                match = deg_pat.search(block)
                if match:
                    degree = match.group(0).strip()
                    break

            # Find year
            year_match = self.YEAR_PATTERN.search(block)
            if year_match:
                year = year_match.group(0)

            # Heuristic for institution name (words containing University, College, Institute, School, Academy)
            inst_pat = re.compile(
                r"([^,\n]+(?:university|college|institute|academy|school|polytechnic)[^,\n]*)",
                re.IGNORECASE,
            )
            inst_match = inst_pat.search(block)
            if inst_match:
                institution = inst_match.group(0).strip()
            elif lines:
                # If no keyword, take first line that isn't the degree
                for line in lines:
                    if degree.lower() not in line.lower() and not self.YEAR_PATTERN.search(line):
                        institution = line
                        break

            if degree or institution or year:
                education_list.append({
                    "degree": degree[:100] if degree else "Degree / Qualification",
                    "institution": institution[:150] if institution else "Educational Institution",
                    "year": year if year else "N/A",
                })

        return education_list[:5]

    def _extract_certifications(self, cert_text: str) -> List[str]:
        """Extract certification names from certifications section."""
        if not cert_text.strip():
            return []

        cert_list: List[str] = []
        lines = [l.strip() for l in cert_text.split("\n") if l.strip()]

        for line in lines:
            # Remove leading bullet symbols (-, *, •, o, numbers)
            cleaned = re.sub(r"^[\s*•\-–—\d\.)]+", "", line).strip()
            if 3 <= len(cleaned) <= 120:
                cert_list.append(cleaned)

        return cert_list[:15]

    def _extract_summary(self, summary_section: str, full_text: str) -> str:
        """Extract profile summary or fallback to first 500 characters of text."""
        if summary_section and summary_section.strip():
            return summary_section.strip()[:1000]

        # Clean top of resume text for fallback
        lines = [l.strip() for l in full_text.split("\n") if l.strip()]
        # Skip candidate header lines
        filtered_lines = []
        for line in lines[:10]:
            if "@" in line or self.PHONE_PATTERN.search(line):
                continue
            filtered_lines.append(line)

        preview = " ".join(filtered_lines)
        return preview[:500] if preview else full_text[:500]
