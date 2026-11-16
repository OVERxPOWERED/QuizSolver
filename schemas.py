from typing import List, Optional
from pydantic import BaseModel, Field, validator, conlist
from enum import Enum


class QuestionType(str, Enum):
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"


class QuestionCreateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)
    type: QuestionType
    options: conlist(str, min_items=2, max_items=6)
    correct_answer: List[int]
    points: int = Field(default=1, ge=1, le=100)

    @validator("correct_answer")
    def validate_indices(cls, v, values):
        if "options" in values:
            max_index = len(values["options"]) - 1
            for idx in v:
                if idx < 0 or idx > max_index:
                    raise ValueError(
                        f"correct_answer index {idx} out of range for {len(values['options'])} options"
                    )
        return v

    @validator("correct_answer")
    def validate_count_matches_type(cls, v, values):
        if "type" in values:
            q_type = values["type"]
            if q_type == QuestionType.SINGLE_CHOICE and len(v) != 1:
                raise ValueError("Single choice questions must have exactly one correct answer")
            if q_type == QuestionType.TRUE_FALSE and len(v) != 1:
                raise ValueError("True/False questions must have exactly one correct answer")
            if q_type == QuestionType.MULTIPLE_CHOICE and len(v) < 1:
                raise ValueError("Multiple choice questions must have at least one correct answer")
        return v


class QuizCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    questions: conlist(QuestionCreateRequest, min_items=1, max_items=50)
    time_limit_seconds: Optional[int] = Field(default=None, ge=30, le=7200)
    passing_score: int = Field(default=60, ge=0, le=100)
    is_published: bool = False


class AnswerRequest(BaseModel):
    question_id: int = Field(..., gt=0)
    selected_option_indices: conlist(int, min_items=1)


class QuizSubmitRequest(BaseModel):
    quiz_id: int = Field(..., gt=0)
    answers: conlist(AnswerRequest, min_items=1)