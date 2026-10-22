```python
"""Local SQLite Question-Answer Bank for caching and instant accurate retrieval."""

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional
from config import config
from utils.helpers import compute_question_hash, normalize_text
from utils.logger import log


@contextmanager
def profile_db_query(query_name: str, sql: str = ""):
    """Context manager to profile database query execution time."""
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        log.debug(f"DB Query [{query_name}]: {elapsed_ms:.2f}ms - {sql[:100]}")


class QuestionBankDB:
    """Manages SQLite storage for questions, AI solutions, and verified quiz answers."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or config.DATABASE_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection_pool_size = getattr(config, "DB_CONNECTION_POOL_SIZE", 5)
        self._init_db()
        self._create_performance_indexes()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a new database connection with optimized settings."""
        conn = sqlite3.connect(
            self.db_path,
            timeout=30.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrency
        conn.execute("PRAGMA journal_mode=WAL;")
        # Optimize for read-heavy workload
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA cache_size=-32768;")  # 32MB cache
        conn.execute("PRAGMA temp_store=MEMORY;")
        conn.execute("PRAGMA mmap_size=268435456;")  # 256MB mmap
        return conn

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS questions (
                    question_hash TEXT PRIMARY KEY,
                    course_name TEXT,
                    quiz_name TEXT,
                    question_text TEXT,
                    options_json TEXT,
                    selected_answer TEXT,
                    selected_index INTEGER,
                    explanation TEXT,
                    verified BOOLEAN DEFAULT 0,
                    confidence REAL DEFAULT 1.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS quiz_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    quiz_id TEXT,
                    status TEXT DEFAULT 'active',
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    score REAL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS submissions (
                    submission_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    question_id TEXT,
                    selected_answer TEXT,
                    is_correct BOOLEAN,
                    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES quiz_sessions(session_id)
                );
            """)
            # Base indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_course ON questions(course_name);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_quiz ON questions(quiz_name);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_verified ON questions(verified);")
            conn.commit()

    def _create_performance_indexes(self) -> None:
        """Create performance indexes on high-cardinality columns idempotently."""
        indexes = [
            # Composite index for quiz-specific question lookups
            ("idx_questions_quiz_type", "questions", "(quiz_id, question_type)"),
            # Composite index for user session queries
            ("idx_sessions_user_status", "quiz_sessions", "(user_id, status)"),
            # Composite index for submission lookups
            ("idx_submissions_session_question", "submissions", "(session_id, question_id)"),
            # Additional helpful indexes
            ("idx_questions_course_quiz", "questions", "(course_name, quiz_name)"),
            ("idx_sessions_quiz_status", "quiz_sessions", "(quiz_id, status)"),
            ("idx_submissions_question", "submissions", "(question_id)"),
        ]

        with self._get_connection() as conn:
            for index_name, table, columns in indexes:
                try:
                    conn.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} {columns};")
                    log.debug(f"Created/verified index: {index_name}")
                except sqlite3.Error as e:
                    log.warning(f"Failed to create index {index_name}: {e}")
            conn.commit()

    def analyze_query_plan(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """
        Analyze query execution plan using EXPLAIN QUERY PLAN.
        Returns list of plan steps with details.
        """
        with self._get_connection() as conn:
            with profile_db_query("EXPLAIN QUERY PLAN", sql):
                cursor = conn.cursor()
                cursor.execute(f"EXPLAIN QUERY PLAN {sql}", params)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]

    def get_answer(self, question_text: str) -> Optional[dict[str, Any]]:
        """
        Lookup answer for a question by its normalized text hash.
        Returns dict with selected_answer, selected_index, verified status, etc.
        """
        q_hash = compute_question_hash(question_text)
        sql = "SELECT * FROM questions WHERE question_hash = ?"
        with self._get_connection() as conn:
            with profile_db_query("get_answer", sql):
                cursor = conn.cursor()
                cursor.execute(sql, (q_hash,))
                row = cursor.fetchone()
                if row:
                    return {
                        "question_hash": row["question_hash"],
                        "course_name": row["course_name"],
                        "quiz_name": row["quiz_name"],
                        "question_text": row["question_text"],
                        "options": json.loads(row["options_json"]) if row["options_json"] else [],
                        "selected_answer": row["selected_answer"],
                        "selected_index": row["selected_index"],
                        "explanation": row["explanation"],
                        "verified": bool(row["verified"]),
                        "confidence": row["confidence"],
                    }
        return None

    def save_answer(
        self,
        question_text: str,
        options: list[str],
        selected_answer: str,
        selected_index: int,
        course_name: str = "",
        quiz_name: str = "",
        explanation: str = "",
        verified: bool = False,
        confidence: float = 1.0,
    ) -> None:
        """Store or update question and its selected answer in database."""
        q_hash = compute_question_hash(question_text)
        options_json = json.dumps(options, ensure_ascii=False)

        sql = """
            INSERT INTO questions (
                question_hash, course_name, quiz_name, question_text,
                options_json, selected_answer, selected_index, explanation,
                verified, confidence