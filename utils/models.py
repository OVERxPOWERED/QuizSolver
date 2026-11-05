from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QuestionType(str, Enum):
    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"
    TRUE_FALSE = "TRUE_FALSE"
    CODING = "CODING"
    SHORT_ANSWER = "SHORT_ANSWER"


class SessionStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Quiz(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    title: str = Field(..., min_length=1, max_length=255)
    platform: str = Field(..., min_length=1, max_length=100)
    url: str = Field(..., min_length=1, max_length=2048)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v

    @field_validator("updated_at", mode="before")
    @classmethod
    def set_updated_at(cls, v: Any) -> datetime:
        return datetime.utcnow()


class Question(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
        use_enum_values=True,
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    quiz_id: uuid.UUID
    type: QuestionType
    prompt: str = Field(..., min_length=1)
    options: list[str] = Field(default_factory=list)
    correct_answer: str = Field(..., min_length=1)
    explanation: Optional[str] = Field(default=None, max_length=5000)
    difficulty: Optional[str] = Field(default=None, max_length=50)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("options")
    @classmethod
    def validate_options(cls, v: list[str], info: Any) -> list[str]:
        question_type = info.data.get("type")
        if question_type == QuestionType.MULTIPLE_CHOICE and len(v) < 2:
            raise ValueError("MULTIPLE_CHOICE questions must have at least 2 options")
        if question_type == QuestionType.TRUE_FALSE and set(v) != {"True", "False"}:
            raise ValueError("TRUE_FALSE questions must have options ['True', 'False']")
        return v

    @field_validator("correct_answer")
    @classmethod
    def validate_correct_answer(cls, v: str, info: Any) -> str:
        options = info.data.get("options", [])
        question_type = info.data.get("type")
        if question_type == QuestionType.MULTIPLE_CHOICE and options and v not in options:
            raise ValueError("correct_answer must be one of the provided options")
        if question_type == QuestionType.TRUE_FALSE and v not in ("True", "False"):
            raise ValueError("correct_answer for TRUE_FALSE must be 'True' or 'False'")
        return v


class Attempt(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    question_id: uuid.UUID
    selected_option: str = Field(..., min_length=1)
    is_correct: bool
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    confidence: Optional[int] = Field(default=None, ge=0, le=100)
    time_spent_seconds: Optional[int] = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Session(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
        use_enum_values=True,
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    quiz_id: uuid.UUID
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    score: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    status: SessionStatus = SessionStatus.IN_PROGRESS
    total_questions: int = Field(default=0, ge=0)
    correct_answers: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("completed_at")
    @classmethod
    def validate_completed_at(cls, v: Optional[datetime], info: Any) -> Optional[datetime]:
        if v is not None:
            started_at = info.data.get("started_at")
            if started_at and v < started_at:
                raise ValueError("completed_at cannot be before started_at")
        return v

    @field_validator("status")
    @classmethod
    def validate_status_transition(cls, v: SessionStatus, info: Any) -> SessionStatus:
        current_status = info.data.get("status")
        if current_status == SessionStatus.COMPLETED and v != SessionStatus.COMPLETED:
            raise ValueError("Cannot transition from COMPLETED to another status")
        if current_status == SessionStatus.FAILED and v != SessionStatus.FAILED:
            raise ValueError("Cannot transition from FAILED to another status")
        return v

    def calculate_score(self) -> float:
        if self.total_questions == 0:
            return 0.0
        return round((self.correct_answers / self.total_questions) * 100, 2)

    def mark_completed(self) -> None:
        self.completed_at = datetime.utcnow()
        self.status = SessionStatus.COMPLETED
        self.score = self.calculate_score()

    def mark_failed(self) -> None:
        self.completed_at = datetime.utcnow()
        self.status = SessionStatus.FAILED
        self.score = self.calculate_score()


__all__ = [
    "QuestionType",
    "SessionStatus",
    "Quiz",
    "Question",
    "Attempt",
    "Session",
]