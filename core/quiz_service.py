```python
"""
QuizService: Business logic for quiz lifecycle management, question retrieval, and attempt recording.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from uuid import uuid4
from contextlib import contextmanager

from core.database import DatabaseManager
from core.cache import CacheManager
from core.models import Quiz, Question, Session, Attempt, Option
from utils.logger import get_logger

# OpenTelemetry imports for telemetry
from opentelemetry import trace
from opentelemetry.trace import SpanKind

logger = get_logger(__name__)
tracer = trace.get_tracer(__name__)


class NotFoundError(Exception):
    """Raised when a requested resource is not found."""
    pass


class ValidationError(Exception):
    """Raised when input validation fails."""
    pass


# Pydantic-like request/response models (simplified for this service)
# In a real project, these would be in a separate schemas module using Pydantic.
class QuizCreateRequest:
    def __init__(self, title: str, description: str, questions: List[Dict[str, Any]]):
        self.title = title
        self.description = description
        self.questions = questions  # Each question dict contains text, options, correct_answer, etc.


class QuizResponse:
    def __init__(self, quiz: Quiz, questions: List[Question] = None):
        self.id = quiz.id
        self.title = quiz.title
        self.description = quiz.description
        self.created_at = quiz.created_at
        self.updated_at = quiz.updated_at
        self.questions = questions or []


class QuizListResponse:
    def __init__(self, quizzes: List[QuizResponse], total: int, page: int, page_size: int):
        self.quizzes = quizzes
        self.total = total
        self.page = page
        self.page_size = page_size
        self.total_pages = (total + page_size - 1) // page_size


class QuizSubmitRequest:
    def __init__(self, answers: List[Dict[str, Any]]):