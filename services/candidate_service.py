"""Candidate management service for TalentMatch AI.

Coordinates candidate ingestion, file deduplication, structured extraction,
database persistence, search, manual corrections, retry pipelines, and document lifecycle.
"""

from datetime import datetime
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from config.settings import get_settings
from database.connection import get_session
from database.models import Candidate, CandidateMatch, JobDescription, ResumeDocument
from database.repository import CandidateRepository
from services.resume_parser import ResumeParserService

logger = logging.getLogger(__name__)


class CandidateService:
    """High-level domain service orchestrating candidate and resume document workflows."""

    def __init__(self, parser_service: Optional[ResumeParserService] = None) -> None:
        """Initialize candidate service with parser and application configuration.

        Args:
            parser_service: Optional ResumeParserService instance.
        """
        self.parser = parser_service or ResumeParserService()
        self.settings = get_settings()

    def process_uploaded_file(
        self,
        file_bytes: bytes,
        filename: str,
        batch_id: Optional[str] = None,
        job_category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process a single uploaded resume through the full ingestion pipeline.

        Pipeline stages:
            1. Validate file (size, format, integrity)
            2. Compute SHA-256 hash and check for duplicates
            3. Extract text from document (PDF / DOCX / TXT)
            4. Extract structured entities (contact, skills, experience, education)
            5. Store resume file artifact in upload directory
            6. Persist Candidate and ResumeDocument entities in database

        Args:
            file_bytes: Raw binary content of the file.
            filename: Original name of the uploaded file.
            batch_id: Optional batch correlation identifier.

        Returns:
            dict containing:
                - success (bool): True if successfully processed and stored
                - candidate_id (int or None): Generated candidate ID
                - candidate_name (str or None): Candidate name
                - status (str): 'new', 'duplicate', 'failed', or 'warning'
                - message (str): Human-readable status message
                - warnings (list[str]): List of warnings encountered
        """
        batch_id = batch_id or f"batch_{uuid.uuid4().hex[:8]}"

        # Step 1: Validate file
        val = self.parser.validate_file(
            file_bytes, filename, max_size_mb=self.settings.MAX_FILE_SIZE_MB
        )
        if not val["valid"]:
            logger.warning("File validation failed for '%s': %s", filename, val["error"])
            return {
                "success": False,
                "candidate_id": None,
                "candidate_name": None,
                "status": "failed",
                "message": val["error"],
                "warnings": [val["error"]],
            }

        file_type = val["file_type"]

        # Step 2: Compute SHA-256 hash and check for duplicates
        file_hash = self.parser.compute_file_hash(file_bytes)
        dup_info = self.get_duplicate_warnings(file_hash)
        if dup_info:
            first_dup = dup_info[0]
            msg = (
                f"Duplicate resume detected: identical to existing candidate "
                f"#{first_dup['candidate_id']} ('{first_dup['candidate_name']}') "
                f"uploaded as '{first_dup['original_filename']}'."
            )
            logger.info("Duplicate file hash detected for '%s' -> %s", filename, file_hash)
            return {
                "success": False,
                "candidate_id": first_dup["candidate_id"],
                "candidate_name": first_dup["candidate_name"],
                "status": "duplicate",
                "message": msg,
                "warnings": [msg],
            }

        # Step 3: Parse document text
        parse_result = self.parser.parse_file(file_bytes, filename)
        warnings: List[str] = list(parse_result.get("warnings", []))
        text = parse_result.get("text", "").strip()
        is_scanned = parse_result.get("is_scanned", False)

        # Step 4: Extract candidate profile info
        if text:
            extracted_info = self.parser.extract_candidate_info(text)
        else:
            extracted_info = {
                "name": Path(filename).stem.replace("_", " ").title(),
                "email": None,
                "phone": None,
                "skills": [],
                "experience": [],
                "education": [],
                "certifications": [],
                "summary": "",
            }
            warnings.append(
                f"Could not extract readable text from '{filename}'. Candidate saved with pending/failed parse state."
            )

        # Determine parsing status
        if not text:
            candidate_status = "failed"
        elif is_scanned or warnings:
            candidate_status = "warning"
        else:
            candidate_status = "parsed"

        # Step 5: Save file to disk storage
        saved_file_path: Optional[str] = None
        try:
            storage_dir = self.settings.UPLOADS_DIR
            storage_dir.mkdir(parents=True, exist_ok=True)
            safe_filename = f"{file_hash[:12]}_{Path(filename).name}"
            dest_file = storage_dir / safe_filename
            with open(dest_file, "wb") as f:
                f.write(file_bytes)
            saved_file_path = str(dest_file)
        except Exception as file_exc:
            logger.error("Failed to write resume artifact to disk for '%s': %s", filename, file_exc)
            warnings.append(f"Storage warning: Failed to persist raw file artifact: {file_exc}")

        # Step 6: Persist in database
        try:
            with get_session() as session:
                candidate = Candidate(
                    name=extracted_info.get("name") or Path(filename).stem,
                    email=extracted_info.get("email"),
                    phone=extracted_info.get("phone"),
                    resume_summary=extracted_info.get("summary"),
                    skills_json=json.dumps(extracted_info.get("skills", [])),
                    experience_json=json.dumps(extracted_info.get("experience", [])),
                    education_json=json.dumps(extracted_info.get("education", [])),
                    certifications_json=json.dumps(extracted_info.get("certifications", [])),
                    parsing_status=candidate_status,
                    parsing_warnings=json.dumps(warnings) if warnings else None,
                    job_category=job_category.strip() if job_category and job_category.strip() else None,
                    upload_batch_id=batch_id,
                )
                session.add(candidate)
                session.flush()

                resume_doc = ResumeDocument(
                    candidate_id=candidate.id,
                    original_filename=filename,
                    file_hash=file_hash,
                    file_path=saved_file_path,
                    resume_text=text,
                    file_size=len(file_bytes),
                    file_type=file_type,
                )
                session.add(resume_doc)
                session.flush()

                candidate_id = candidate.id
                candidate_name = candidate.name

            logger.info(
                "Ingested candidate #%d ('%s') from '%s' [Status: %s]",
                candidate_id,
                candidate_name,
                filename,
                candidate_status,
            )

            return {
                "success": candidate_status != "failed",
                "candidate_id": candidate_id,
                "candidate_name": candidate_name,
                "status": "new" if candidate_status != "failed" else "failed",
                "message": (
                    f"Successfully parsed '{filename}'"
                    if candidate_status != "failed"
                    else f"Parsed with extraction failures: '{filename}'"
                ),
                "warnings": warnings,
            }

        except Exception as db_exc:
            logger.error("Failed to save candidate for '%s': %s", filename, db_exc, exc_info=True)
            return {
                "success": False,
                "candidate_id": None,
                "candidate_name": None,
                "status": "failed",
                "message": f"Database persistence error: {str(db_exc)}",
                "warnings": warnings + [str(db_exc)],
            }

    def process_pasted_text(
        self,
        text: str,
        batch_id: Optional[str] = None,
        job_category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process pasted resume text, supporting multiple resumes separated by delimiter lines.

        Supports standard separators like '---', '====', '***', or '________________'.

        Args:
            text: Raw pasted resume text.
            batch_id: Optional batch correlation identifier.
            job_category: Optional job category/target role.

        Returns:
            dict containing:
                - total (int): Number of resumes identified
                - success_count (int): Successfully processed
                - duplicate_count (int): Duplicates ignored
                - failed_count (int): Failed processing
                - results (list[dict]): Per-resume outcome records
        """
        if not text or not text.strip():
            return {
                "total": 0,
                "success_count": 0,
                "duplicate_count": 0,
                "failed_count": 0,
                "results": [],
            }

        batch_id = batch_id or f"pasted_{uuid.uuid4().hex[:8]}"

        # Split on markdown / separator bars (e.g. ---, ===, ___, ***)
        separator_pattern = re.compile(r"^(?:[-=_*]{3,}|~{3,})\s*$", re.MULTILINE)
        raw_chunks = separator_pattern.split(text)
        chunks = [c.strip() for c in raw_chunks if c.strip()]

        if not chunks:
            chunks = [text.strip()]

        total = len(chunks)
        success_count = 0
        duplicate_count = 0
        failed_count = 0
        results: List[Dict[str, Any]] = []

        for idx, chunk in enumerate(chunks, start=1):
            chunk_bytes = chunk.encode("utf-8")
            chunk_filename = f"pasted_resume_{idx}.txt"

            res = self.process_uploaded_file(
                file_bytes=chunk_bytes,
                filename=chunk_filename,
                batch_id=batch_id,
                job_category=job_category,
            )
            res["filename"] = chunk_filename
            results.append(res)

            if res["status"] == "duplicate":
                duplicate_count += 1
            elif res["success"]:
                success_count += 1
            else:
                failed_count += 1

        return {
            "total": total,
            "success_count": success_count,
            "duplicate_count": duplicate_count,
            "failed_count": failed_count,
            "results": results,
        }

    def process_batch(
        self,
        files: List[Any],
        batch_id: Optional[str] = None,
        job_category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process a collection of uploaded files.

        Accepts Streamlit UploadedFile objects, tuples of (bytes, filename), or dicts.

        Args:
            files: List of file instances.
            batch_id: Optional batch correlation identifier.
            job_category: Optional job category/target role.

        Returns:
            dict with batch aggregate metrics and per-file records.
        """
        batch_id = batch_id or f"batch_{uuid.uuid4().hex[:8]}"
        total = len(files)
        success_count = 0
        duplicate_count = 0
        failed_count = 0
        results: List[Dict[str, Any]] = []

        for item in files:
            file_bytes: bytes
            filename: str

            # Handle Streamlit UploadedFile or file-like object
            if hasattr(item, "read") and hasattr(item, "name"):
                try:
                    file_bytes = item.read()
                    filename = item.name
                    # Reset stream if possible for downstream consumers
                    if hasattr(item, "seek"):
                        item.seek(0)
                except Exception as read_exc:
                    results.append({
                        "filename": getattr(item, "name", "unknown"),
                        "success": False,
                        "candidate_id": None,
                        "candidate_name": None,
                        "status": "failed",
                        "message": f"Could not read upload buffer: {read_exc}",
                        "warnings": [str(read_exc)],
                    })
                    failed_count += 1
                    continue
            elif isinstance(item, tuple) and len(item) == 2:
                file_bytes, filename = item
            elif isinstance(item, dict) and "bytes" in item and "filename" in item:
                file_bytes = item["bytes"]
                filename = item["filename"]
            else:
                results.append({
                    "filename": "unknown_file",
                    "success": False,
                    "candidate_id": None,
                    "candidate_name": None,
                    "status": "failed",
                    "message": "Unsupported file item input structure",
                    "warnings": ["Unsupported input item"],
                })
                failed_count += 1
                continue

            outcome = self.process_uploaded_file(
                file_bytes, filename, batch_id=batch_id, job_category=job_category
            )
            outcome["filename"] = filename
            results.append(outcome)

            if outcome["status"] == "duplicate":
                duplicate_count += 1
            elif outcome["success"]:
                success_count += 1
            else:
                failed_count += 1

        return {
            "total": total,
            "success_count": success_count,
            "duplicate_count": duplicate_count,
            "failed_count": failed_count,
            "results": results,
            "batch_id": batch_id,
        }

    def process_zip_upload(
        self,
        zip_bytes: bytes,
        zip_filename: str = "resumes.zip",
        batch_id: Optional[str] = None,
        job_category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process a bulk ZIP archive containing multiple candidate resumes.

        Extracts supported files (PDF, DOCX, TXT) and parses each candidate profile individually.

        Args:
            zip_bytes: Raw binary content of the ZIP archive.
            zip_filename: Name of the ZIP file.
            batch_id: Optional batch correlation identifier.
            job_category: Optional target job role/category tag.

        Returns:
            dict containing:
                - total (int): Number of resume files extracted
                - success_count (int): Successfully parsed profiles
                - duplicate_count (int): Duplicates ignored
                - failed_count (int): Failures
                - archive_warnings (list[str]): Warnings from archive extraction
                - results (list[dict]): Per-file outcome details
                - batch_id (str): Associated batch ID
        """
        batch_id = batch_id or f"zip_{uuid.uuid4().hex[:8]}"

        extracted_files, archive_warnings = self.parser.extract_from_zip(zip_bytes, zip_filename)

        if not extracted_files:
            return {
                "total": 0,
                "success_count": 0,
                "duplicate_count": 0,
                "failed_count": 0,
                "archive_warnings": archive_warnings,
                "results": [],
                "batch_id": batch_id,
            }

        total = len(extracted_files)
        success_count = 0
        duplicate_count = 0
        failed_count = 0
        results: List[Dict[str, Any]] = []

        for item in extracted_files:
            outcome = self.process_uploaded_file(
                file_bytes=item["bytes"],
                filename=item["filename"],
                batch_id=batch_id,
                job_category=job_category,
            )
            outcome["filename"] = item["filename"]
            outcome["inner_path"] = item.get("inner_path", item["filename"])
            results.append(outcome)

            if outcome["status"] == "duplicate":
                duplicate_count += 1
            elif outcome["success"]:
                success_count += 1
            else:
                failed_count += 1

        return {
            "total": total,
            "success_count": success_count,
            "duplicate_count": duplicate_count,
            "failed_count": failed_count,
            "archive_warnings": archive_warnings,
            "results": results,
            "batch_id": batch_id,
        }

    def get_candidate(self, candidate_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve full candidate profile, attached resume documents, and match history.

        Args:
            candidate_id: Primary key of Candidate.

        Returns:
            dict containing candidate data or None if not found.
        """
        with get_session() as session:
            stmt = (
                select(Candidate)
                .where(Candidate.id == candidate_id)
                .options(
                    joinedload(Candidate.resumes),
                    joinedload(Candidate.matches).joinedload(CandidateMatch.job_description),
                )
            )
            candidate = session.scalars(stmt).unique().first()
            if not candidate:
                return None

            return self._serialize_candidate(candidate)

    def get_candidates(
        self,
        search: Optional[str] = None,
        skills: Optional[List[str]] = None,
        status: Optional[str] = None,
        job_category: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Search and retrieve paginated candidates with total matching count.

        Args:
            search: Free text query against name, email, and resume text.
            skills: List of required skill keywords.
            status: Filter by parsing status (parsed, warning, failed, pending).
            job_category: Filter by candidate job role / category.
            offset: SQL query offset.
            limit: Page size limit.

        Returns:
            tuple of (list of serialized candidate dicts, total matching count)
        """
        with get_session() as session:
            clauses = []

            if status and status.lower() != "all":
                clauses.append(Candidate.parsing_status == status.strip().lower())

            if job_category and job_category.strip() and job_category.lower() != "all":
                clauses.append(Candidate.job_category.ilike(f"%{job_category.strip()}%"))

            if search and search.strip():
                term = f"%{search.strip()}%"
                clauses.append(
                    or_(
                        Candidate.name.ilike(term),
                        Candidate.email.ilike(term),
                        Candidate.resume_summary.ilike(term),
                        Candidate.skills_json.ilike(term),
                    )
                )

            if skills:
                for skill in skills:
                    if skill.strip():
                        clauses.append(Candidate.skills_json.ilike(f"%{skill.strip()}%"))

            # Total count query
            count_stmt = select(func.count()).select_from(Candidate)
            if clauses:
                count_stmt = count_stmt.where(*clauses)
            total_count = session.scalar(count_stmt) or 0

            # Records query
            stmt = (
                select(Candidate)
                .options(joinedload(Candidate.resumes))
            )
            if clauses:
                stmt = stmt.where(*clauses)

            stmt = stmt.order_by(Candidate.created_at.desc()).offset(offset).limit(limit)
            candidates = session.scalars(stmt).unique().all()

            results = [self._serialize_candidate(c) for c in candidates]
            return results, total_count

    def update_candidate(self, candidate_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update candidate profile attributes for manual correction.

        Args:
            candidate_id: ID of candidate to update.
            data: Dictionary of fields to modify.

        Returns:
            dict of updated candidate profile or None.
        """
        with get_session() as session:
            candidate = session.get(Candidate, candidate_id)
            if not candidate:
                logger.warning("Attempted to update non-existent candidate #%d", candidate_id)
                return None

            if "name" in data and data["name"]:
                candidate.name = data["name"].strip()
            if "email" in data:
                candidate.email = data["email"].strip().lower() if data["email"] else None
            if "phone" in data:
                candidate.phone = data["phone"].strip() if data["phone"] else None
            if "resume_summary" in data:
                candidate.resume_summary = data["resume_summary"]
            if "job_category" in data:
                candidate.job_category = data["job_category"].strip() if data["job_category"] else None
            if "parsing_status" in data and data["parsing_status"]:
                candidate.parsing_status = data["parsing_status"]

            # Serialize list fields to JSON strings if passed as Python lists
            if "skills" in data:
                candidate.skills_json = (
                    json.dumps(data["skills"]) if isinstance(data["skills"], list) else data["skills"]
                )
            if "experience" in data:
                candidate.experience_json = (
                    json.dumps(data["experience"])
                    if isinstance(data["experience"], list)
                    else data["experience"]
                )
            if "education" in data:
                candidate.education_json = (
                    json.dumps(data["education"])
                    if isinstance(data["education"], list)
                    else data["education"]
                )
            if "certifications" in data:
                candidate.certifications_json = (
                    json.dumps(data["certifications"])
                    if isinstance(data["certifications"], list)
                    else data["certifications"]
                )

            session.flush()
            logger.info("Updated candidate profile #%d ('%s')", candidate_id, candidate.name)
            return self._serialize_candidate(candidate)

    def delete_candidate(self, candidate_id: int) -> bool:
        """Delete candidate, attached documents, and cleanup filesystem artifacts.

        Args:
            candidate_id: Primary key of Candidate.

        Returns:
            bool: True if candidate was found and deleted, False otherwise.
        """
        with get_session() as session:
            stmt = (
                select(Candidate)
                .where(Candidate.id == candidate_id)
                .options(joinedload(Candidate.resumes))
            )
            candidate = session.scalars(stmt).unique().first()
            if not candidate:
                return False

            # Delete physical files from disk
            for resume in candidate.resumes:
                if resume.file_path:
                    try:
                        p = Path(resume.file_path)
                        if p.exists() and p.is_file():
                            p.unlink()
                            logger.debug("Deleted disk artifact: %s", resume.file_path)
                    except Exception as exc:
                        logger.warning("Could not delete file %s from disk: %s", resume.file_path, exc)

            session.delete(candidate)
            session.flush()
            logger.info("Deleted candidate #%d and associated records.", candidate_id)
            return True

    def get_duplicate_warnings(self, file_hash: str) -> List[Dict[str, Any]]:
        """Query existing resume documents sharing the same SHA-256 hash.

        Args:
            file_hash: SHA-256 digest string.

        Returns:
            list of dicts containing existing candidate metadata if matched.
        """
        with get_session() as session:
            stmt = (
                select(ResumeDocument)
                .where(ResumeDocument.file_hash == file_hash)
                .options(joinedload(ResumeDocument.candidate))
            )
            matches = session.scalars(stmt).all()
            duplicates = []
            for doc in matches:
                duplicates.append({
                    "resume_doc_id": doc.id,
                    "candidate_id": doc.candidate_id,
                    "candidate_name": doc.candidate.name if doc.candidate else "Unknown",
                    "original_filename": doc.original_filename,
                    "file_hash": doc.file_hash,
                    "upload_timestamp": doc.upload_timestamp.isoformat() if doc.upload_timestamp else None,
                })
            return duplicates

    def retry_failed(self, candidate_id: int) -> Dict[str, Any]:
        """Re-parse and extract profile data for a failed or warned candidate resume.

        Args:
            candidate_id: Candidate identifier.

        Returns:
            dict indicating retry outcome.
        """
        with get_session() as session:
            stmt = (
                select(Candidate)
                .where(Candidate.id == candidate_id)
                .options(joinedload(Candidate.resumes))
            )
            candidate = session.scalars(stmt).unique().first()
            if not candidate:
                return {
                    "success": False,
                    "message": f"Candidate #{candidate_id} not found.",
                }

            if not candidate.resumes:
                return {
                    "success": False,
                    "message": f"No resume documents associated with candidate #{candidate_id}.",
                }

            resume = candidate.resumes[0]
            text = resume.resume_text or ""

            # If text was empty but physical file exists, re-read and parse file
            if not text and resume.file_path:
                try:
                    p = Path(resume.file_path)
                    if p.exists():
                        file_bytes = p.read_bytes()
                        parse_res = self.parser.parse_file(file_bytes, resume.original_filename)
                        text = parse_res.get("text", "")
                        resume.resume_text = text
                except Exception as read_exc:
                    logger.error("Retry re-read failed for #%d: %s", candidate_id, read_exc)

            if not text:
                return {
                    "success": False,
                    "message": f"Cannot retry: no text content or file available for candidate #{candidate_id}.",
                }

            extracted = self.parser.extract_candidate_info(text)

            candidate.name = extracted.get("name") or candidate.name
            if extracted.get("email"):
                candidate.email = extracted.get("email")
            if extracted.get("phone"):
                candidate.phone = extracted.get("phone")
            candidate.resume_summary = extracted.get("summary") or candidate.resume_summary
            candidate.skills_json = json.dumps(extracted.get("skills", []))
            candidate.experience_json = json.dumps(extracted.get("experience", []))
            candidate.education_json = json.dumps(extracted.get("education", []))
            candidate.certifications_json = json.dumps(extracted.get("certifications", []))
            candidate.parsing_status = "parsed"
            candidate.parsing_warnings = None

            session.flush()
            logger.info("Successfully re-parsed candidate #%d ('%s')", candidate_id, candidate.name)

            return {
                "success": True,
                "candidate_id": candidate_id,
                "candidate_name": candidate.name,
                "message": f"Successfully re-extracted profile for {candidate.name}",
            }

    def _serialize_candidate(self, candidate: Candidate) -> Dict[str, Any]:
        """Convert Candidate ORM model into a JSON-serializable dictionary."""
        skills = []
        if candidate.skills_json:
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

        warnings = []
        if candidate.parsing_warnings:
            try:
                warnings = json.loads(candidate.parsing_warnings)
                if not isinstance(warnings, list):
                    warnings = [str(candidate.parsing_warnings)]
            except Exception:
                warnings = [str(candidate.parsing_warnings)]

        resumes = []
        for r in candidate.resumes:
            resumes.append({
                "id": r.id,
                "original_filename": r.original_filename,
                "file_hash": r.file_hash,
                "file_path": r.file_path,
                "file_size": r.file_size,
                "file_type": r.file_type,
                "upload_timestamp": r.upload_timestamp.strftime("%Y-%m-%d %H:%M:%S") if r.upload_timestamp else None,
                "resume_text": r.resume_text,
            })

        matches = []
        for m in getattr(candidate, "matches", []):
            matches.append({
                "id": m.id,
                "jd_id": m.jd_id,
                "jd_title": m.job_description.title if m.job_description else f"Job #{m.jd_id}",
                "match_score": m.match_score,
                "match_category": m.match_category,
                "human_review_status": m.human_review_status,
                "last_screened_at": m.last_screened_at.strftime("%Y-%m-%d %H:%M") if m.last_screened_at else None,
            })

        return {
            "id": candidate.id,
            "name": candidate.name,
            "email": candidate.email,
            "phone": candidate.phone,
            "resume_summary": candidate.resume_summary,
            "skills": skills,
            "experience": experience,
            "education": education,
            "certifications": certifications,
            "job_category": candidate.job_category,
            "parsing_status": candidate.parsing_status,
            "parsing_warnings": warnings,
            "upload_batch_id": candidate.upload_batch_id,
            "created_at": candidate.created_at.strftime("%Y-%m-%d %H:%M:%S") if candidate.created_at else None,
            "updated_at": candidate.updated_at.strftime("%Y-%m-%d %H:%M:%S") if candidate.updated_at else None,
            "resumes": resumes,
            "matches": matches,
        }
