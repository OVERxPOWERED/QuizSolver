```python
import asyncio
import pytest
import pytest_asyncio
from pathlib import Path
from typing import AsyncGenerator, Callable, List, Optional
from unittest.mock import AsyncMock, MagicMock

import httpx
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from main import app
from app.core.config import settings
from app.db.base import Base
from app.models.quiz import Quiz, Question, Option
from app.models.attempt import Attempt, Answer
from app.schemas.ai import AISolution, AIReasoningStep
from app.services.browser.manager import BrowserManager
from app.services.ai.solver import AISolver
from app.services.lms.client import LMSClient


TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    poolclass=NullPool,
    connect_args={"check_same_thread": False},
)

TestingSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


@pytest.fixture(scope="session")
def event_loop() -> asyncio.AbstractEventLoop:
    """Create session-scoped event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a fresh database session with transaction rollback per test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestingSessionLocal() as session:
        async with session.begin():
            yield session
            await session.rollback()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def async_client(db_session: AsyncSession) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Create async HTTP client for testing FastAPI app with dependency override."""
    from app.db.session import get_db

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def mock_browser() -> AsyncMock:
    """Create mocked BrowserManager with deterministic responses."""
    mock = AsyncMock(spec=BrowserManager)
    mock.initialize = AsyncMock(return_value=None)
    mock.close = AsyncMock(return_value=None)
    mock.navigate = AsyncMock(return_value=None)
    mock.get_page_content = AsyncMock(return_value="<html><body>Mocked content</body></html>")
    mock.screenshot = AsyncMock(return_value=b"fake_screenshot_bytes")
    mock.click = AsyncMock(return_value=None)
    mock.fill = AsyncMock(return_value=None)
    mock.select_option = AsyncMock(return_value=None)
    mock.wait_for_selector = AsyncMock(return_value=None)
    mock.evaluate = AsyncMock(return_value={})
    mock.get_cookies = AsyncMock(return_value=[])
    mock.set_cookies = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def mock_ai_solver() -> AsyncMock:
    """Create mocked AISolver returning deterministic AISolution."""
    mock = AsyncMock(spec=AISolver)

    deterministic_solution = AISolution(
        question_id="q1",
        selected_option_ids=["opt_1"],
        confidence=0.95,
        reasoning=[
            AIReasoningStep(
                step=1,
                description="Analyzed question keywords",
                evidence="Question contains 'capital of France'",
            ),
            AIReasoningStep(
                step=2,
                description="Evaluated options",
                evidence="Option A: Paris matches known fact",
            ),
            AIReasoningStep(
                step=3,
                description="Selected best answer",
                evidence="Paris is the capital of France",
            ),
        ],
        metadata={"model": "gpt-4-test", "tokens_used": 150},
    )

    mock.solve_question = AsyncMock(return_value=deterministic_solution)
    mock.solve_quiz = AsyncMock(return_value=[deterministic_solution])
    mock.analyze_question = AsyncMock(return_value={"type": "multiple_choice", "difficulty": "easy"})
    return mock


@pytest.fixture
def mock_lms_client() -> AsyncMock:
    """Create mocked LMSClient with deterministic responses."""
    mock = AsyncMock(spec=LMSClient)
    mock.authenticate = AsyncMock(return_value={"access_token": "test_token", "expires_in": 3600})
    mock.get_course_quizzes = AsyncMock(return_value=[
        {"id": "quiz_1", "title": "Test Quiz 1", "course_id": "course_1"},
        {"id": "quiz_2", "title": "Test Quiz 2", "course_id": "course_1"},
    ])
    mock.get_quiz_details = AsyncMock(return_value={
        "id": "quiz_1",
        "title": "Test Quiz",
        "questions": [
            {"id": "q1", "text": "What is 2+2?", "type": "multiple_choice", "options": [
                {"id": "opt_1", "text": "3"},
                {"id": "opt_2", "text": "4"},
                {"id": "opt_3", "text": "5"},
            ]},
        ],
    })
    mock.submit_quiz = AsyncMock(return_value={"attempt_id": "attempt_1", "score": 100})
    mock.get_attempt_result = AsyncMock(return_value={
        "attempt_id": "attempt_1",
        "score": 100,
        "answers": [{"question_id": "q1", "selected_option_id": "opt_2", "correct": True}],
    })
    return mock


def quiz_factory(
    title: str = "Test Quiz",
    description: str = "A test quiz",
    course_id: str = "course_1",
    questions: Optional[List[dict]] = None,
    time_limit: Optional[int] = None,
    max_attempts: int = 3,
    is_published: bool = True,
) -> Quiz:
    """Factory function to create Quiz model instances with questions."""
    if questions is None:
        questions = [
            {
                "text": "What is the capital of France?",
                "type": "multiple_choice",
                "points": 10,
                "order": 1,
                "options": [
                    {"text": "London", "is_correct": False, "order": 1},
                    {"text