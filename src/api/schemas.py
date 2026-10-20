from typing import List, Optional
from pydantic import BaseModel, Field, validator, conlist
from enum import Enum


class QuestionType(str, Enum):
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"


class QuestionCreateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000, description="Question text")
    type: QuestionType = Field(..., description="Question type")
    options: conlist(str, min_items=2, max_items=6) = Field(
        ..., description="Answer options (2-6 items)"
    )
    correct_answer: List[int] = Field(
        ..., description="Indices of correct options (0-based)"
    )
    points: int = Field(default=1, ge=1, le=100, description="Points for this question")

    @validator("correct_answer")
    def validate_correct_answer_indices(cls, v, values):
        if "options" in values:
            max_index = len(values["options"]) - 1
            for idx in v:
                if idx < 0 or idx > max_index:
                    raise ValueError(
                        f"correct_answer index {idx} out of range for {len(values['options'])} options"
                    )
        return v

    @validator("correct_answer")
    def validate_correct_answer_matches_type(cls, v, values):
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
    title: str = Field(..., min_length=1, max_length=200, description="Quiz title")
    description: Optional[str] = Field(
        default=None, max_length=2000, description="Quiz description"
    )
    questions: conlist(QuestionCreateRequest, min_items=1, max_items=50) = Field(
        ..., description="List of questions (1-50)"
    )
    time_limit_seconds: Optional[int] = Field(
        default=None, ge=30, le=7200, description="Time limit in seconds (30-7200)"
    )
    passing_score: int = Field(
        default=60, ge=0, le=100, description="Passing score percentage"
    )
    is_published: bool = Field(default=False, description="Whether quiz is published")


class AnswerRequest(BaseModel):
    question_id: int = Field(..., gt=0, description="Question ID")
    selected_option_indices: conlist(int, min_items=1) = Field(
        ..., description="Selected option indices (0-based)"
    )


class QuizSubmitRequest(BaseModel):
    quiz_id: int = Field(..., gt=0, description="Quiz ID")
    answers: conlist(AnswerRequest, min_items=1) = Field(
        ..., description="List of answers"
    )


class QuestionResponse(BaseModel):
    id: int
    text: str
    type: QuestionType
    options: List[str]
    points: int
    order: int

    class Config:
        from_attributes = True


class QuizResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    time_limit_seconds: Optional[int]
    passing_score: int
    is_published: bool
    created_at: str
    updated_at: str
    questions: List[QuestionResponse] = []

    class Config:
        from_attributes = True


class QuizListResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    question_count: int
    time_limit_seconds: Optional[int]
    passing_score: int
    is_published: bool
    created_at: str

    class Config:
        from_attributes = True


class QuestionResultResponse(BaseModel):
    question_id: int
    question_text: str
    question_type: QuestionType
    options: List[str]
    correct_indices: List[int]
    selected_indices: List[int]
    is_correct: bool
    points_earned: int
    points_possible: int


class QuizResultResponse(BaseModel):
    quiz_id: int
    quiz_title: str
    total_points: int
    earned_points: int
    score_percentage: float
    passed: bool
    time_taken_seconds: Optional[int]
    question_results: List[QuestionResultResponse]
    completed_at: str

    class Config:
        from_attributes = True


class ErrorResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None
    field_errors: Optional[dict] = None


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str