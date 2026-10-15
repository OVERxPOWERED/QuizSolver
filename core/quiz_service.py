```python
"""
QuizService: Business logic for quiz lifecycle management, question retrieval, and attempt recording.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List
from uuid import uuid4

from core.database import DatabaseManager
from core.models import Quiz, Question, Session, Attempt, Option
from utils.logger import get_logger

logger = get_logger(__name__)


class QuizService:
    """Service layer for quiz operations."""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self.session_ttl = timedelta(hours=2)  # Session expiration time

    def start_quiz(self, quiz_id: str) -> Session:
        """
        Start a new quiz session.

        Args:
            quiz_id: Unique identifier of the quiz.

        Returns:
            Session: Newly created session object.

        Raises:
            ValueError: If quiz not found.
        """
        quiz = self.db.get_quiz(quiz_id)
        if not quiz:
            logger.error("Quiz not found", extra={"quiz_id": quiz_id})
            raise ValueError(f"Quiz {quiz_id} not found")

        session = Session(
            id=str(uuid4()),
            quiz_id=quiz_id,
            user_id=None,  # Anonymous for now; can be extended
            started_at=datetime.utcnow(),
            current_question_index=0,
            score=0,
            status="in_progress",
        )
        self.db.create_session(session)
        logger.info("Quiz session started", extra={"session_id": session.id, "quiz_id": quiz_id})
        return session

    def get_next_question(self, session_id: str) -> Optional[Question]:
        """
        Retrieve the next question for the session.

        Args:
            session_id: Unique identifier of the session.

        Returns:
            Question: Next question, or None if quiz is complete.

        Raises:
            ValueError: If session not found or expired.
        """
        session = self.db.get_session(session_id)
        if not session:
            logger.error("Session not found", extra={"session_id": session_id})
            raise ValueError(f"Session {session_id} not found")

        if session.status != "in_progress":
            logger.warning("Session not in progress", extra={"session_id": session_id, "status": session.status})
            raise ValueError(f"Session {session_id} is not active")

        if datetime.utcnow() - session.started_at > self.session_ttl:
            session.status = "expired"
            self.db.update_session(session)
            logger.warning("Session expired", extra={"session_id": session_id})
            raise ValueError(f"Session {session_id} has expired")

        quiz = self.db.get_quiz(session.quiz_id)
        if not quiz:
            logger.error("Quiz not found for session", extra={"session_id": session_id, "quiz_id": session.quiz_id})
            raise ValueError(f"Quiz {session.quiz_id} not found")

        questions = self.db.get_questions_for_quiz(quiz.id)
        if session.current_question_index >= len(questions):
            logger.info("No more questions", extra={"session_id": session_id})
            return None

        question = questions[session.current_question_index]
        logger.debug("Next question retrieved", extra={"session_id": session_id, "question_id": question.id})
        return question

    def submit_answer(
        self,
        session_id: str,
        question_id: str,
        selected_option: str,
        confidence: int
    ) -> Attempt:
        """
        Record an answer attempt.

        Args:
            session_id: Session identifier.
            question_id: Question identifier.
            selected_option: Option key selected by user (e.g., 'A', 'B').
            confidence: Confidence level (1-5).

        Returns:
            Attempt: Recorded attempt with correctness.

        Raises:
            ValueError: If session/question not found, duplicate submission, or invalid confidence.
        """
        if not 1 <= confidence <= 5:
            raise ValueError("Confidence must be between 1 and 5")

        session = self.db.get_session(session_id)
        if not session:
            logger.error("Session not found", extra={"session_id": session_id})
            raise ValueError(f"Session {session_id} not found")

        if session.status != "in_progress":
            logger.warning("Session not active", extra={"session_id": session_id, "status": session.status})
            raise ValueError(f"Session {session_id} is not active")

        # Verify question matches current question
        quiz = self.db.get_quiz(session.quiz_id)
        questions = self.db.get_questions_for_quiz(quiz.id)
        if session.current_question_index >= len(questions):
            raise ValueError("Quiz already completed")

        current_question = questions[session.current_question_index]
        if current_question.id != question_id:
            logger.warning("Question mismatch", extra={"session_id": session_id, "expected": current_question.id, "got": question_id})
            raise ValueError("Question does not match current question")

        # Check for duplicate attempt
        existing_attempt = self.db.get_attempt(session_id, question_id)
        if existing_attempt:
            logger.warning("Duplicate submission", extra={"session_id": session_id, "question_id": question_id})
            raise ValueError("Answer already submitted for this question")

        # Determine correctness
        correct_option = next((opt for opt in current_question.options if opt.is_correct), None)
        is_correct = correct_option and correct_option.key == selected_option

        attempt = Attempt(
            id=str(uuid4()),
            session_id=session_id,
            question_id=question_id,
            selected_option=selected_option,
            confidence=confidence,
            is_correct=is_correct,
            timestamp=datetime.utcnow(),
        )
        self.db.create_attempt(attempt)

        # Update session score and advance index
        if is_correct:
            session.score += 1
        session.current_question_index += 1
        self.db.update_session(session)

        logger.info("Answer submitted", extra={
            "