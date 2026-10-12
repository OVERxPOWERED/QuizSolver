```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from uuid import uuid4

# Assuming the services are in a module named 'services'
from services import QuizService, SessionService, ResultService
from models import Quiz, Question, Option, Session, Answer, User


@pytest.fixture
def sample_user():
    return User(id=uuid4(), username="testuser", email="test@example.com")


@pytest.fixture
def sample_quiz(sample_user):
    quiz = Quiz(
        id=uuid4(),
        title="Sample Quiz",
        description="A test quiz",
        created_by=sample_user.id,
        created_at=datetime.utcnow(),
        is_active=True
    )
    quiz.questions = [
        Question(
            id=uuid4(),
            quiz_id=quiz.id,
            text="What is 2+2?",
            order=1,
            options=[
                Option(id=uuid4(), question_id=uuid4(), text="3", is_correct=False),
                Option(id=uuid4(), question_id=uuid4(), text="4", is_correct=True),
                Option(id=uuid4(), question_id=uuid4(), text="5", is_correct=False),
            ]
        ),
        Question(
            id=uuid4(),
            quiz_id=quiz.id,
            text="What is the capital of France?",
            order=2,
            options=[
                Option(id=uuid4(), question_id=uuid4(), text="London", is_correct=False),
                Option(id=uuid4(), question_id=uuid4(), text="Paris", is_correct=True),
                Option(id=uuid4(), question_id=uuid4(), text="Berlin", is_correct=False),
            ]
        )
    ]
    return quiz


@pytest.fixture
def sample_session(sample_quiz, sample_user):
    return Session(
        id=uuid4(),
        quiz_id=sample_quiz.id,
        user_id=sample_user.id,
        started_at=datetime.utcnow(),
        completed_at=None,
        is_active=True,
        current_question_index=0
    )


@pytest.fixture
def sample_answers(sample_session, sample_quiz):
    answers = []
    for i, question in enumerate(sample_quiz.questions):
        correct_option = next(opt for opt in question.options if opt.is_correct)
        answers.append(Answer(
            id=uuid4(),
            session_id=sample_session.id,
            question_id=question.id,
            selected_option_id=correct_option.id,
            is_correct=True,
            answered_at=datetime.utcnow()
        ))
    return answers


class TestQuizService:
    @pytest.mark.asyncio
    async def test_create_quiz_valid(self, mocker, sample_user):
        mock_db = AsyncMock()
        quiz_data = {
            "title": "New Quiz",
            "description": "A new quiz",
            "questions": [
                {"text": "Q1", "options": [{"text": "A", "is_correct": True}, {"text": "B", "is_correct": False}]}
            ]
        }
        
        # Mock the database commit and refresh
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        
        service = QuizService(mock_db)
        quiz = await service.create_quiz(quiz_data, sample_user.id)
        
        assert quiz.title == "New Quiz"
        assert quiz.created_by == sample_user.id
        assert len(quiz.questions) == 1
        assert len(quiz.questions[0].options) == 2
        mock_db.add.assert_called()
        mock_db.commit.assert_awaited_once()
        mock_db.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_quiz_not_found(self, mocker):
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=None))
        
        service = QuizService(mock_db)
        quiz = await service.get_quiz(uuid4())
        
        assert quiz is None
        mock_db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_quizzes_pagination(self, mocker, sample_quiz):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_quiz]
        mock_result.scalar.return_value = 1  # total count
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        service = QuizService(mock_db)
        quizzes, total = await service.list_quizzes(page=1, per_page=10)
        
        assert len(quizzes) == 1
        assert total == 1
        assert quizzes[0].id == sample_quiz.id
        assert mock_db.execute.call_count == 2  # one for count, one for data


class TestSessionService:
    @pytest.mark.asyncio
    async def test_start_session_creates_active(self, mocker, sample_quiz, sample_user):
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=sample_quiz))
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        
        service = SessionService(mock_db)
        session = await service.start_session(sample_quiz.id, sample_user.id)
        
        assert session.quiz_id == sample_quiz.id
        assert session.user_id == sample_user.id
        assert session.is_active is True
        assert session.current_question_index == 0
        mock_db.add.assert_called()
        mock_db.commit.assert_awaited_once()
        mock_db.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_submit_answer_validates_option(self, mocker, sample_session, sample_quiz):
        mock_db = AsyncMock()
        # Mock session retrieval
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=sample_session))
        # Mock question and option retrieval
        question = sample_quiz.questions[0]
        correct_option = next(opt for opt in question.options if opt.is_correct)
        mock_db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=sample_session),  # session
                MagicMock(scalar_one_or_none=question),        # question
                MagicMock(scalar_one_or_none=correct_option)   # option
            ]
        )
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        
        service = SessionService(mock_db)
        answer = await service.submit_answer(sample_session.id, question.id, correct_option.id)
        
        assert answer.session_id == sample_session.id
        assert answer.question_id == question.id
        assert answer.selected_option_id == correct_option.id
        assert answer.is_correct is True