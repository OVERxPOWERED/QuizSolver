```python
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
            elif correct_count == 0:
                raise ValueError("MULTIPLE_CHOICE questions must have at least one correct option")
        return v

    @field_validator("correct_answer")
    @classmethod
    def validate_correct_answer_for_type(cls, v: Optional[str], info: Any) -> Optional[str]:
        question_type = info.data.get("type")
        if question_type in (QuestionType.CODING, QuestionType.SHORT_ANSWER):
            if v is None or not v.strip():
                raise ValueError(f"{question_type.value} questions require a correct_answer")
        return v.strip() if v else v

    @model_validator(mode="after")
    def validate_question_consistency(self) -> Question:
        if self.type == QuestionType.TRUE_FALSE:
            option_texts = {opt.text.strip().lower() for opt in self.options}
            expected = {"true", "false"}
            if option_texts != expected:
                raise ValueError("TRUE_FALSE questions must have options 'True' and 'False'")
        return self


class Quiz(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    questions: list[Question] = Field(default_factory=list)
    time_limit_minutes: Optional[int] = Field(default=None, gt=0)
    passing_score: float = Field(default=0.7, ge=0.0, le=1.0)
    max_attempts: int = Field(default=1, ge=1)
    shuffle_questions: bool = False
    shuffle_options: bool = False
    show_correct_answers: bool = True
    show_explanations: bool = True
    is_published: bool = False
    created_by: Optional[UUID] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    published_at: Optional[datetime] = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Quiz title cannot be empty or whitespace only")
        return v.strip()

    @field_validator("questions")
    @classmethod
    def validate_unique_question_ids(cls, v: list[Question]) -> list[Question]:
        ids = [q.id for q in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate question IDs found in quiz")
        return v

    @property
    def total_points(self) -> float:
        return sum(q.points for q in self.questions)

    @property
    def question_count(self) -> int:
        return len(self.questions)


class LMSConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    platform: LMSPlatform
    base_url: str = Field(..., min_length=1)
    client_id: str = Field(..., min_length=1)
    client_secret: str = Field(..., min_length=1)
    redirect_uri: Optional[str] = None
    scopes: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=30, gt=0)
    verify_ssl: bool = True
    custom_headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not v.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return v


class Attempt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="