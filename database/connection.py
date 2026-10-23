"""Database connection and session lifecycle management for TalentMatch AI.

Provides engine creation, session context management, database initialization,
and default application configuration seeding.
"""

from contextlib import contextmanager
import logging
from typing import Generator, Optional

from sqlalchemy import Engine, create_engine, delete, event, select
from sqlalchemy.orm import Session, sessionmaker

from config.settings import get_settings
from database.models import (
    ApplicationSetting,
    AuditLog,
    Base,
    Candidate,
    CandidateMatch,
    JDRequirement,
    JDVersion,
    JobDescription,
    MatchEvidence,
    RecruiterReview,
    ResumeDocument,
    ScreeningBatch,
    ScreeningRun,
    Shortlist,
    ShortlistCandidate,
)

logger = logging.getLogger(__name__)

# Module-level singletons
_ENGINE: Optional[Engine] = None
_SESSION_FACTORY: Optional[sessionmaker[Session]] = None


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    """Enable foreign key constraints, WAL mode, and busy timeout for SQLite connections."""
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.close()
    except Exception:
        # Ignore if the backend is not SQLite or does not support PRAGMA
        pass


def get_engine(database_url: Optional[str] = None, echo: Optional[bool] = None) -> Engine:
    """Create or return the cached SQLAlchemy Engine.

    Args:
        database_url: Optional database connection string. Defaults to settings.DATABASE_URL.
        echo: Optional flag for SQL query logging. Defaults to settings.DEBUG_MODE.

    Returns:
        Engine: SQLAlchemy Engine instance.
    """
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE

    settings = get_settings()
    url = database_url or settings.DATABASE_URL
    is_echo = echo if echo is not None else settings.DEBUG_MODE

    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    _ENGINE = create_engine(
        url,
        echo=is_echo,
        connect_args=connect_args,
        pool_pre_ping=True,
    )
    logger.debug("Database engine created for URL: %s", url)
    return _ENGINE


def get_session_factory(engine: Optional[Engine] = None) -> sessionmaker[Session]:
    """Create or return the cached sessionmaker factory.

    Args:
        engine: Optional Engine instance. Defaults to get_engine().

    Returns:
        sessionmaker[Session]: Configured session factory.
    """
    global _SESSION_FACTORY
    if _SESSION_FACTORY is not None:
        return _SESSION_FACTORY

    eng = engine or get_engine()
    _SESSION_FACTORY = sessionmaker(
        bind=eng,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    return _SESSION_FACTORY


@contextmanager
def get_session(session_factory: Optional[sessionmaker[Session]] = None) -> Generator[Session, None, None]:
    """Context manager providing a transactional SQLAlchemy Session.

    Yields:
        Session: Active SQLAlchemy Session.

    Handles commit on success and automatic rollback on exception.
    """
    factory = session_factory or get_session_factory()
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.error("Session transaction rolled back due to error: %s", exc, exc_info=True)
        raise
    finally:
        session.close()


def _seed_default_settings(session: Session) -> None:
    """Seed initial application settings if they do not exist."""
    settings = get_settings()
    default_settings = [
        ("ai_enabled", str(settings.AI_ENABLED).lower(), "Enable or disable AI analysis capabilities"),
        ("ai_model", settings.AI_MODEL, "Default Gemini model for screening and analysis"),
        ("max_file_size_mb", str(settings.MAX_FILE_SIZE_MB), "Maximum upload size in megabytes per file"),
        ("max_batch_size", str(settings.MAX_BATCH_SIZE), "Maximum number of resumes processed in a single batch"),
        ("resume_retention_days", str(settings.RESUME_RETENTION_DAYS), "Days before raw resume files are eligible for purge"),
        ("default_matching_threshold", "70.0", "Minimum match score threshold to qualify as strong match"),
    ]

    for key, value, description in default_settings:
        existing = session.scalar(select(ApplicationSetting).where(ApplicationSetting.key == key))
        if not existing:
            setting = ApplicationSetting(key=key, value=value, description=description)
            session.add(setting)
            logger.info("Seeded default setting: %s = %s", key, value)


def init_db(engine: Optional[Engine] = None) -> None:
    """Initialize the database schema and populate initial settings.

    Args:
        engine: Optional Engine instance. Defaults to get_engine().
    """
    eng = engine or get_engine()
    logger.info("Initializing database tables...")
    Base.metadata.create_all(bind=eng)

    # Safe lightweight schema migrations for existing databases
    with eng.connect() as conn:
        try:
            # Check if job_category column exists in candidates table
            result = conn.exec_driver_sql("PRAGMA table_info(candidates)").fetchall()
            col_names = [row[1] for row in result]
            if "job_category" not in col_names:
                conn.exec_driver_sql("ALTER TABLE candidates ADD COLUMN job_category VARCHAR(150)")
                logger.info("Migrated candidates table: added job_category column.")
        except Exception as mig_err:
            logger.warning("Auto-migration check for candidates failed: %s", mig_err)

    # Seed default configurations
    factory = get_session_factory(eng)
    with get_session(factory) as session:
        _seed_default_settings(session)

    logger.info("Database initialization completed successfully.")


class DatabaseManager:
    """High-level database management facade for TalentMatch AI."""

    def __init__(self, database_url: Optional[str] = None, echo: Optional[bool] = None) -> None:
        self.engine = get_engine(database_url, echo)
        self.session_factory = get_session_factory(self.engine)

    def init_database(self) -> None:
        """Create all tables and seed default settings."""
        init_db(self.engine)

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """Provide a scoped transactional session."""
        with get_session(self.session_factory) as session:
            yield session

    def reset_database(self) -> None:
        """Drop all tables and recreate schema (for testing/development only)."""
        logger.warning("Resetting database: dropping all tables.")
        with self.engine.connect() as conn:
            try:
                conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            except Exception:
                pass
        Base.metadata.drop_all(bind=self.engine)
        self.init_database()

    def clear_candidate_and_screening_data(self) -> dict:
        """Delete all candidates, resumes, matches, evidence, screening batches, and shortlists.

        Keeps Job Descriptions and system settings intact.
        """
        logger.warning("Purging all candidate, screening, and shortlist data...")
        with get_session(self.session_factory) as session:
            ev_count = session.execute(delete(MatchEvidence)).rowcount or 0
            rr_count = session.execute(delete(RecruiterReview)).rowcount or 0
            m_count = session.execute(delete(CandidateMatch)).rowcount or 0
            sc_count = session.execute(delete(ShortlistCandidate)).rowcount or 0
            sl_count = session.execute(delete(Shortlist)).rowcount or 0
            sr_count = session.execute(delete(ScreeningRun)).rowcount or 0
            sb_count = session.execute(delete(ScreeningBatch)).rowcount or 0
            rd_count = session.execute(delete(ResumeDocument)).rowcount or 0
            c_count = session.execute(delete(Candidate)).rowcount or 0
            session.commit()
            return {
                "candidates_deleted": c_count,
                "resumes_deleted": rd_count,
                "matches_deleted": m_count,
                "shortlists_deleted": sl_count,
                "batches_deleted": sb_count,
            }
