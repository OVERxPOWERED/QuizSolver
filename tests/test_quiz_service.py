```python
import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime
from typing import List, Optional

# Import the service and exceptions
from src.services.quiz_service import QuizService
from src.models.quiz import Quiz, Question, AnswerOption
from src.models.session import QuizSession, SessionStatus, AnswerAttempt
from src.exceptions import QuizNotFoundError, SessionNotFoundError, DuplicateAttemptError
from src.database.manager import DatabaseManager


@pytest.fixture
def mock_db_manager():
    """Create a mock DatabaseManager."""
    return Mock(spec=DatabaseManager)


@pytest.fixture
def quiz_service(mock_db_manager):
    """Create a QuizService instance with mocked database."""
    return QuizService(db_manager=mock_db_manager)


@pytest.fixture
def sample_quiz():
    """Create a sample quiz for testing."""
    return Quiz(
        id=1,
        title="Python Basics",
        description="Test your Python knowledge",
        questions=[
            Question(
                id=1,
                quiz_id=1,
                text="What is Python?",
                options=[
                    AnswerOption(id=1, question_id=1, text="A snake", is_correct=False),
                    AnswerOption(id=2, question_id=1, text="A programming language", is_correct=True),
                    AnswerOption(id=3, question_id=1, text="A fruit", is_correct=False),
                ],
                order=1
            ),
            Question(
                id=2,
                quiz_id=1,
                text="What is 2 + 2?",
                options=[
                    AnswerOption(id=4, question_id=2, text="3", is_correct=False),
                    AnswerOption(id=5, question_id=2, text="4", is_correct=True),
                    AnswerOption(id=6, question_id=2, text="5", is_correct=False),
                ],
                order=2
            ),
            Question(
                id=3,
                quiz_id=1,
                text="Which keyword defines a function?",
                options=[
                    AnswerOption(id=7, question_id=3, text="func", is_correct=False),
                    AnswerOption(id=8, question_id=3, text="def", is_correct=True),
                    AnswerOption(id=9, question_id=3, text="function", is_correct=False),
                ],
                order=3
            ),
        ],
        created_at=datetime(2024, 1, 1, 12, 0, 0)
    )


@pytest.fixture
def sample_session():
    """Create a sample quiz session."""
    return QuizSession(
        id=1,
        quiz_id=1,
        user_id="user123",
        status=SessionStatus.IN_PROGRESS,
        current_question_index=0,
        score=0,
        started_at=datetime(2024, 1, 1, 12, 0, 0),
        completed_at=None,
        attempts=[]
    )


class TestStartQuiz:
    """Tests for start_quiz method."""

    def test_start_quiz_success(self, quiz_service, mock_db_manager, sample_quiz):
        """Test successful quiz session creation."""
        mock_db_manager.get_quiz.return_value = sample_quiz
        mock_db_manager.create_session.return_value = QuizSession(
            id=1,
            quiz_id=1,
            user_id="user123",
            status=SessionStatus.IN_PROGRESS,
            current_question_index=0,
            score=0,
            started_at=datetime(2024, 1, 1, 12, 0, 0),
            completed_at=None,
            attempts=[]
        )

        session = quiz_service.start_quiz(quiz_id=1, user_id="user123")

        assert session is not None
        assert session.quiz_id == 1
        assert session.user_id == "user123"
        assert session.status == SessionStatus.IN_PROGRESS
        assert session.current_question_index == 0
        assert session.score == 0
        assert session.completed_at is None
        assert len(session.attempts) == 0
        mock_db_manager.get_quiz.assert_called_once_with(1)
        mock_db_manager.create_session.assert_called_once()

    def test_start_quiz_not_found_raises_error(self, quiz_service, mock_db_manager):
        """Test QuizNotFoundError when quiz doesn't exist."""
        mock_db_manager.get_quiz.return_value = None

        with pytest.raises(QuizNotFoundError) as exc_info:
            quiz_service.start_quiz(quiz_id=999, user_id="user123")

        assert exc_info.value.quiz_id == 999
        mock_db_manager.get_quiz.assert_called_once_with(999)
        mock_db_manager.create_session.assert_not_called()

    def test_start_quiz_empty_quiz_raises_error(self, quiz_service, mock_db_manager):
        """Test error when quiz has no questions."""
        empty_quiz = Quiz(
            id=1,
            title="Empty Quiz",
            description="No questions",
            questions=[],
            created_at=datetime(2024, 1, 1, 12, 0, 0)
        )
        mock_db_manager.get_quiz.return_value = empty_quiz

        with pytest.raises(ValueError) as exc_info:
            quiz_service.start_quiz(quiz_id=1, user_id="user123")

        assert "no questions" in str(exc_info.value).lower()
        mock_db_manager.create_session.assert_not_called()


class TestGetNextQuestion:
    """Tests for get_next_question method."""

    def test_get_next_question_first_question(self, quiz_service, mock_db_manager, sample_quiz, sample_session):
        """Test getting the first question."""
        mock_db_manager.get_session.return_value = sample_session
        mock_db_manager.get_quiz.return_value = sample_quiz

        question = quiz_service.get_next_question(session_id=1)

        assert question is not None
        assert question.id == 1
        assert question.text == "What is Python?"
        assert len(question.options) == 3
        mock_db_manager.get_session.assert_called_once_with(1)
        mock_db_manager.get_quiz.assert_called_once_with(1)

    def test_get_next_question_second_question(self, quiz_service, mock_db_manager, sample_quiz):
        """Test getting the second question after answering first."""
        session = QuizSession(
            id=1,
            quiz_id=1,
            user_id="user123",
            status=SessionStatus.IN_PROGRESS,
            current_question_index=1,
            score=1,
            started_at=datetime(2024, 1, 1, 12, 0, 0),
            completed_at=None,
            attempts=[
                AnswerAttempt(question_id=1, selected_option_id=2, is_correct=True, answered_at=datetime.now())
            ]
        )
        mock_db_manager.get_session.return_value = session
        mock_db_manager.get_quiz.return_value = sample_quiz

        question = quiz_service.get_next_question(session_id=1)

        assert question is not None
        assert question.id == 2
        assert question.text == "What is 2 + 2?"

    def test_get_next_question_last_question(self, quiz_service, mock_db_manager, sample_quiz):
        """Test getting the last question."""
        session = QuizSession(
            id=1,
            quiz_id=1,
            user_id="user123",
            status=SessionStatus.IN_PROGRESS,
            current_question_index=2,
            score=2,
            started_at=datetime(2024, 1, 1, 12, 0,