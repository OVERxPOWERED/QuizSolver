```python
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, EmailStr, Field, HttpUrl, field_validator, model_validator, computed_field
from pydantic.config import ConfigDict


class QuestionType(str, Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    CODING = "coding"
    SHORT_ANSWER = "short_answer"


class SessionStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    FAILED = "failed"


class DifficultyLevel(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    EXPERT = "expert"


class Quiz(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "title": "Two Sum Problem",
                "description": "Find two numbers that add up to target",
                "platform": "leetcode",
                "url": "https://leetcode.com/problems/two-sum/",
                "metadata": {"difficulty": "easy", "tags": ["array", "hash-table"]},
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-15T10:30:00Z",
            }
        },
        populate_by_name=True,
        use_enum_values=True,
    )

    id: UUID = Field(default_factory=uuid4, description="Unique identifier for the quiz")
    title: str = Field(..., min_length=1, max_length=255, description="Title of the quiz")
    description: Optional[str] = Field(None, max_length=2000, description="Detailed description of the quiz")
    platform: str = Field(..., min_length=1, max_length=100, description="Platform hosting the quiz (e.g., leetcode, hackerrank)")
    url: HttpUrl = Field(..., description="URL to the quiz on the platform")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional platform-specific metadata")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Timestamp when the quiz was created")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Timestamp when the quiz was last updated")

    @field_validator("updated_at", mode="before")
    @classmethod
    def set_updated_at(cls, v: Any, info: Any) -> datetime:
        return datetime.utcnow()


class Question(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440001",
                "quiz_id": "550e8400-e29b-41d4-a716-446655440000",
                "type": "multiple_choice",
                "stem": "What is the time complexity of binary search?",
                "options": ["O(n)", "O(log n)", "O(n^2)", "O(1)"],
                "correct_answer": 1,
                "explanation": "Binary search divides the search space in half each iteration",
                "difficulty": "easy",
                "tags": ["algorithms", "binary-search"],
                "points": 1,
                "time_limit_seconds": 60,
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-15T10:30:00Z",
            }
        },
        populate_by_name=True,
        use_enum_values=True,
    )

    id: UUID = Field(default_factory=uuid4, description="Unique identifier for the question")
    quiz_id: UUID = Field(..., description="Reference to the parent quiz")
    type: QuestionType = Field(..., description="Type of question")
    stem: str = Field(..., min_length=1, description="The question text/prompt")
    options: List[str] = Field(default_factory=list, description="List of answer options (for multiple choice)")
    correct_answer: Any = Field(..., description="The correct answer (index for MC, boolean for T/F, code for coding, text for short answer)")
    explanation: Optional[str] = Field(None, description="Explanation of the correct answer")
    difficulty: DifficultyLevel = Field(default=DifficultyLevel.MEDIUM, description="Difficulty level of the question")
    tags: List[str] = Field(default_factory=list, description="Tags/categories for the question")
    points: int = Field(default=1, ge=0, description="Points awarded for correct answer")
    time_limit_seconds: Optional[int] = Field(None, ge=0, description="Time limit in seconds (optional)")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Timestamp when the question was created")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Timestamp when the question was last updated")

    @field_validator("options")
    @classmethod
    def validate_options_for_multiple_choice(cls, v: List[str], info: Any) -> List[str]:
        if info.data.get("type") == QuestionType.MULTIPLE_CHOICE and len(v) < 2:
            raise ValueError("Multiple choice questions must have at least 2 options")
        return v

    @field_validator("correct_answer")
    @classmethod
    def validate_correct_answer(cls, v: Any, info: Any) -> Any:
        q_type = info.data.get("type")
        options = info.data.get("options", [])

        if q_type == QuestionType.MULTIPLE_CHOICE:
            if not isinstance(v, int) or v < 0 or v >= len(options):
                raise ValueError(f"Correct answer must be a valid option index (0-{len(options)-1})")
        elif q_type == QuestionType.TRUE_FALSE:
            if not isinstance(v, bool):
                raise ValueError("True/False questions must have a boolean correct answer")
        elif q_type == QuestionType.CODING:
            if not isinstance(v, str) or not v.strip():
                raise ValueError("Coding questions must have a non-empty string as correct answer")
        elif q_type == QuestionType.SHORT_ANSWER:
            if not isinstance(v, str) or not v.strip():
                raise ValueError("Short answer questions must have a non-empty string as correct answer")
        return v

    @field_validator("updated_at", mode="before")
    @classmethod
    def set_updated_at(cls, v: Any, info: Any) -> datetime:
        return datetime.utcnow()

    @computed_field
    @property
    def is_multiple_choice(self) -> bool:
        return self.type == QuestionType.MULTIPLE_CHOICE

    @computed_field
    @property
    def option_count(self) -> int:
        return len(self.options)


class Answer(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "question_id": "550e8400-e29