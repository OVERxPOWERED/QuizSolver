import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, MagicMock
from core.models import Quiz, Question, Attempt, AttemptCreate, QuizCreate, QuestionCreate
from main import app
from core.telemetry import record_event

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def mock_quiz_service():
    with patch("main.QuizService") as mock_service_class:
        mock_service = Mock()
        mock_service_class.return_value = mock_service
        yield mock_service

@pytest.fixture
def mock_telemetry():
    with patch("main.record_event") as mock_record:
        yield mock_record

def test_create_quiz_success(client, mock_quiz_service, mock_telemetry):
    quiz_data = {"title": "Test Quiz", "description": "A test quiz"}
    created_quiz = Quiz(id=1, title="Test Quiz", description="A test quiz", questions=[])
    mock_quiz_service.create_quiz.return_value = created_quiz

    response = client.post("/quizzes", json=quiz_data)

    assert response.status_code == 201
    assert response.json() == created_quiz.model_dump()
    mock_quiz_service.create_quiz.assert_called_once_with(QuizCreate(**quiz_data))
    mock_telemetry.assert_called_once_with("quiz_created", {"quiz_id": 1, "title": "Test Quiz"})

def test_create_quiz_validation_error(client, mock_quiz_service, mock_telemetry):
    invalid_data = {"description": "Missing title"}

    response = client.post("/quizzes", json=invalid_data)

    assert response.status_code == 422
    mock_quiz_service.create_quiz.assert_not_called()
    mock_telemetry.assert_not_called()

def test_get_quiz_not_found(client, mock_quiz_service, mock_telemetry):
    mock_quiz_service.get_quiz.return_value = None

    response = client.get("/quizzes/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Quiz not found"}
    mock_quiz_service.get_quiz.assert_called_once_with(999)
    mock_telemetry.assert_called_once_with("quiz_not_found", {"quiz_id": 999})

def test_add_question_success(client, mock_quiz_service, mock_telemetry):
    question_data = {"text": "What is 2+2?", "options": ["3", "4", "5"], "correct_answer": 1}
    quiz = Quiz(id=1, title="Test Quiz", description="A test quiz", questions=[])
    created_question = Question(id=1, text="What is 2+2?", options=["3", "4", "5"], correct_answer=1)
    mock_quiz_service.add_question.return_value = (quiz, created_question)

    response = client.post("/quizzes/1/questions", json=question_data)

    assert response.status_code == 201
    assert response.json() == created_question.model_dump()
    mock_quiz_service.add_question.assert_called_once_with(1, QuestionCreate(**question_data))
    mock_telemetry.assert_called_once_with("question_added", {"quiz_id": 1, "question_id": 1})

def test_submit_attempt_success(client, mock_quiz_service, mock_telemetry):
    attempt_data = {"quiz_id": 1, "answers": {1: 1}}
    attempt = Attempt(id=1, quiz_id=1, answers={1: 1}, score=100, passed=True)
    mock_quiz_service.submit_attempt.return_value = attempt

    response = client.post("/attempts", json=attempt_data)

    assert response.status_code == 201
    assert response.json() == attempt.model_dump()
    mock_quiz_service.submit_attempt.assert_called_once_with(AttemptCreate(**attempt_data))
    mock_telemetry.assert_called_once_with("attempt_submitted", {"attempt_id": 1, "quiz_id": 1, "score": 100})

def test_submit_attempt_validation_error(client, mock_quiz_service, mock_telemetry):
    invalid_data = {"quiz_id": 1}

    response = client.post("/attempts", json=invalid_data)

    assert response.status_code == 422
    mock_quiz_service.submit_attempt.assert_not_called()
    mock_telemetry.assert_not_called()