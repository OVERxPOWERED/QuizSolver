from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class QuestionType(str, Enum):
    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"
    TRUE_FALSE = "TRUE_FALSE"
    CODING = "CODING"
    SHORT_ANSWER = "SHORT_ANSWER"


class SessionStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class LMSPlatform(str, Enum):
    CANVAS = "CANVAS"
    BLACKBOARD = "BLACKBOARD"
    MOODLE = "MOODLE"
    CUSTOM = "CUSTOM"


class Option(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    text: str = Field(..., min_length=1, max_length=5000)
    is_correct: bool = False
    explanation: Optional[str] = Field(default=None, max_length=2000)
    order: int = Field(default=0, ge=0)

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Option text cannot be empty or whitespace only")
        return v.strip()


class Question(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    quiz_id: UUID
    type: QuestionType
    prompt: str = Field(..., min_length=1, max_length=10000)
    options: list[Option] = Field(default_factory=list)
    correct_answer: Optional[str] = Field(default=None, max_length=5000)
    explanation: Optional[str] = Field(default=None, max_length=3000)
    points: float = Field(default=1.0, gt=0)
    order: int = Field(default=0, ge=0)
    tags: list[str] = Field(default_factory=list)
    difficulty: Optional[Literal["easy", "medium", "hard"]] = None
    time_limit_seconds: Optional[int] = Field(default=None, gt=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("prompt")
    @classmethod
    def prompt_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Question prompt cannot be empty or whitespace only")
        return v.strip()

    @field_validator("options")
    @classmethod
    def validate_options_for_type(cls, v: list[Option], info: Any) -> list[Option]:
        question_type = info.data.get("type")
        if question_type in (QuestionType.MULTIPLE_CHOICE, QuestionType.TRUE_FALSE):
            if not v:
                raise ValueError(f"{question_type.value} questions must have at least one option")
            correct_count = sum(1 for opt in v if opt.is_correct)
            if question_type == QuestionType.TRUE_FALSE:
                if len(v) != 2:
                    raise ValueError("TRUE_FALSE questions must have exactly 2 options")
                if correct_count != 1:
                    raise ValueError("TRUE_FALSE questions must have exactly one correct option")
            elif question_type == QuestionType.MULTIPLE_CHOICE:
                if correct_count < 1:
                    raise ValueError("MULTIPLE_CHOICE questions must have at least one correct option")
        return v

    @model_validator(mode="after")
    def validate_coding_short_answer(self) -> Question:
        if self.type in (QuestionType.CODING, QuestionType.SHORT_ANSWER):
            if not self.correct_answer or not self.correct_answer.strip():
                raise ValueError(f"{self.type.value} questions must have a correct_answer")
            if self.options:
                raise ValueError(f"{self.type.value} questions should not have options")
        return self