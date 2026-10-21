```python
import pytest
import asyncio
import json
from typing import AsyncGenerator, List, Dict, Any
from httpx import AsyncClient, Response
from uuid import uuid4

from src.api.schemas import (
    QuizCreate,
    QuizResponse,
    QuestionCreate,
    QuestionResponse,
    AnswerCreate,
    AnswerResponse,
    QuizSubmitRequest,
    QuizSubmitResponse,
    PaginatedQuizResponse,
)
from src.models.quiz import Quiz, Question, Answer
from src.models.user import User
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select


class TestQuizCreationBoundaryCases:
    """Boundary and edge case tests for POST /api/quizzes endpoint."""

    @pytest.fixture(autouse=True)
    async def setup(self, async_client: AsyncClient, db_session: AsyncSession):
        self.client = async_client
        self.db = db_session

    async def test_create_quiz_missing_required_fields(self):
        """Test quiz creation with missing required fields."""
        payload = {
            "description": "A quiz without title"
        }
        response = await self.client.post("/api/quizzes", json=payload)
        assert response.status_code == 422
        errors = response.json()["detail"]
        assert any("title" in str(e).lower() for e in errors)

    async def test_create_quiz_empty_title(self):
        """Test quiz creation with empty string title."""
        payload = {
            "title": "",
            "description": "Valid description"
        }
        response = await self.client.post("/api/quizzes", json=payload)
        assert response.status_code == 422

    async def test_create_quiz_title_whitespace_only(self):
        """Test quiz creation with whitespace-only title."""
        payload = {
            "title": "   ",
            "description": "Valid description"
        }
        response = await self.client.post("/api/quizzes", json=payload)
        assert response.status_code == 422

    async def test_create_quiz_invalid_type_for_title(self):
        """Test quiz creation with non-string title."""
        payload = {
            "title": 123,
            "description": "Valid description"
        }
        response = await self.client.post("/api/quizzes", json=payload)
        assert response.status_code == 422

    async def test_create_quiz_invalid_type_for_description(self):
        """Test quiz creation with non-string description."""
        payload = {
            "title": "Valid Title",
            "description": ["not", "a", "string"]
        }
        response = await self.client.post("/api/quizzes", json=payload)
        assert response.status_code == 422

    async def test_create_quiz_oversized_payload(self):
        """Test quiz creation with payload exceeding 1MB."""
        large_description = "x" * (1024 * 1024 + 100)
        payload = {
            "title": "Large Quiz",
            "description": large_description
        }
        response = await self.client.post("/api/quizzes", json=payload)
        assert response.status_code in (413, 422, 400)

    async def test_create_quiz_duplicate_title(self):
        """Test quiz creation with duplicate title."""
        payload = {
            "title": "Unique Quiz Title",
            "description": "First quiz"
        }
        response1 = await self.client.post("/api/quizzes", json=payload)
        assert response1.status_code == 201

        response2 = await self.client.post("/api/quizzes", json=payload)
        assert response2.status_code == 409

    async def test_create_quiz_with_invalid_questions_structure(self):
        """Test quiz creation with malformed questions array."""
        payload = {
            "title": "Quiz with bad questions",
            "description": "Test",
            "questions": "not an array"
        }
        response = await self.client.post("/api/quizzes", json=payload)
        assert response.status_code == 422

    async def test_create_quiz_with_empty_questions_array(self):
        """Test quiz creation with empty questions array."""
        payload = {
            "title": "Quiz with no questions",
            "description": "Test",
            "questions": []
        }
        response = await self.client.post("/api/quizzes", json=payload)
        assert response.status_code == 422

    async def test_create_quiz_question_missing_required_fields(self):
        """Test quiz creation with question missing required fields."""
        payload = {
            "title": "Quiz with incomplete question",
            "description": "Test",
            "questions": [
                {
                    "text": "Question without answers"
                }
            ]
        }
        response = await self.client.post("/api/quizzes", json=payload)
        assert response.status_code == 422

    async def test_create_quiz_question_invalid_answer_indices(self):
        """Test quiz creation with answer index out of bounds."""
        payload = {
            "title": "Quiz with bad answer index",
            "description": "Test",
            "questions": [
                {
                    "text": "What is 2+2?",
                    "answers": [
                        {"text": "3", "is_correct": False},
                        {"text": "4", "is_correct": True}
                    ],
                    "correct_answer_index": 5
                }
            ]
        }
        response = await self.client.post("/api/quizzes", json=payload)
        assert response.status_code == 422

    async def test_create_quiz_question_no_correct_answer(self):
        """Test quiz creation with question having no correct answer."""
        payload = {
            "title": "Quiz with no correct answer",
            "description": "Test",
            "questions": [
                {
                    "text": "What is 2+2?",
                    "answers": [
                        {"text": "3", "is_correct": False},
                        {"text": "5", "is_correct": False}
                    ],
                    "correct_answer_index": 0
                }
            ]
        }
        response = await self.client.post("/api/quizzes", json=payload)
        assert response.status_code == 422

    async def test_create_quiz_question_multiple_correct_answers_not_allowed(self):
        """Test quiz creation with multiple correct answers when not allowed."""
        payload = {
            "title": "Quiz with multiple correct",
            "description": "Test",
            "questions": [
                {
                    "text": "Select all that apply",
                    "answers": [
                        {"text": "Option A", "is_correct": True},
                        {"text": "Option B", "is_correct": True}
                    ],
                    "correct_answer_index": 0
                }
            ]
        }
        response = await self.client.post("/api/quizzes", json=payload)
        assert response.status_code == 422


class TestQuizListPaginationBoundaryCases:
    """Boundary and edge case tests for GET /api/quizzes pagination."""

    @pytest.fixture(autouse=True)
    async def setup(self, async_client: AsyncClient, db_session: AsyncSession):
        self.client = async_client
        self.db = db_session
        await self._create_test_quizzes(15)

    async def _create_test_quizzes(self, count: int):
        for i in range(count):
            quiz = Quiz(title=f"Quiz {i}", description=f"Description {i}")
            self.db.add(quiz