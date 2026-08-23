"""Local SQLite Question-Answer Bank for caching and instant accurate retrieval."""

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional
from config import config
from utils.helpers import compute_question_hash, normalize_text
from utils.logger import log


class QuestionBankDB:
    """Manages SQLite storage for questions, AI solutions, and verified quiz answers."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or config.DATABASE_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
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
                CREATE INDEX IF NOT EXISTS idx_course ON questions(course_name);
            """)
            conn.commit()

    def get_answer(self, question_text: str) -> Optional[dict[str, Any]]:
        """
        Lookup answer for a question by its normalized text hash.
        Returns dict with selected_answer, selected_index, verified status, etc.
        """
        q_hash = compute_question_hash(question_text)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM questions WHERE question_hash = ?
                """,
                (q_hash,),
            )
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

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO questions (
                    question_hash, course_name, quiz_name, question_text,
                    options_json, selected_answer, selected_index, explanation,
                    verified, confidence, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(question_hash) DO UPDATE SET
                    options_json = excluded.options_json,
                    selected_answer = CASE WHEN excluded.verified = 1 THEN excluded.selected_answer ELSE questions.selected_answer END,
                    selected_index = CASE WHEN excluded.verified = 1 THEN excluded.selected_index ELSE questions.selected_index END,
                    explanation = excluded.explanation,
                    verified = MAX(questions.verified, excluded.verified),
                    confidence = excluded.confidence,
                    updated_at = CURRENT_TIMESTAMP;
                """,
                (
                    q_hash,
                    course_name,
                    quiz_name,
                    normalize_text(question_text),
                    options_json,
                    selected_answer,
                    selected_index,
                    explanation,
                    int(verified),
                    confidence,
                ),
            )
            conn.commit()
            log.debug(f"Saved/Updated question in DB: '{question_text[:50]}...' -> '{selected_answer}'")

    def count_questions(self, course_name: Optional[str] = None) -> int:
        """Return total saved questions, optionally filtered by course."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if course_name:
                cursor.execute("SELECT COUNT(*) FROM questions WHERE course_name = ?", (course_name,))
            else:
                cursor.execute("SELECT COUNT(*) FROM questions")
            return cursor.fetchone()[0]
