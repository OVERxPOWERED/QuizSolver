```python
import os
import re
import html
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

from pydantic import BaseModel, validator, ValidationError as PydanticValidationError
from pydantic.types import constr

from config import get_settings
from utils.logger import get_logger

logger = get_logger(__name__)


class ValidationError(Exception):
    """Custom exception for validation failures with detailed context."""
    
    def __init__(self, message: str, field: Optional[str] = None, value: Any = None, errors: Optional[List[str]] = None):
        self.message = message
        self.field = field
        self.value = value
        self.errors = errors or []
        super().__init__(self._format_message())
    
    def _format_message(self) -> str:
        parts = [self.message]
        if self.field:
            parts.append(f"Field: {self.field}")
        if self.value is not None:
            parts.append(f"Value: {repr(self.value)}")
        if self.errors:
            parts.append(f"Details: {'; '.join(self.errors)}")
        return " | ".join(parts)


class QuizConfigModel(BaseModel):
    """Pydantic model for quiz configuration validation."""
    
    title: constr(min_length=1, max_length=200, strip_whitespace=True)
    description: Optional[constr(max_length=2000, strip_whitespace=True)] = None
    time_limit_minutes: Optional[int] = None
    max_attempts: int = 1
    passing_score: float = 70.0
    shuffle_questions: bool = False
    shuffle_options: bool = False
    show_correct_answers: bool = True
    show_explanations: bool = True
    allow_review: bool = True
    
    @validator('time_limit_minutes')
    def validate_time_limit(cls, v):
        if v is not None and (v < 1 or v > 480):
            raise ValueError('Time limit must be between 1 and 480 minutes')
        return v
    
    @validator('max_attempts')
    def validate_max_attempts(cls, v):
        if v < 1 or v > 10:
            raise ValueError('Max attempts must be between 1 and 10')
        return v
    
    @validator('passing_score')
    def validate_passing_score(cls, v):
        if v < 0 or v > 100:
            raise ValueError('Passing score must be between 0 and 100')
        return v


class QuestionDataModel(BaseModel):
    """Pydantic model for question data validation."""
    
    question_text: constr(min_length=1, max_length=5000, strip_whitespace=True)
    question_type: constr(regex=r'^(multiple_choice|true_false|short_answer|essay|matching|fill_blank)$')
    options: Optional[List[constr(min_length=1, max_length=500, strip_whitespace=True)]] = None
    correct_answer: Union[str, List[str], Dict[str, str]]
    explanation: Optional[constr(max_length=2000, strip_whitespace=True)] = None
    points: float = 1.0
    difficulty: constr(regex=r'^(easy|medium|hard)$') = 'medium'
    tags: List[constr(min_length=1, max_length=50, strip_whitespace=True)] = []
    
    @validator('options')
    def validate_options_for_type(cls, v, values):
        q_type = values.get('question_type')
        if q_type in ('multiple_choice', 'matching') and not v:
            raise ValueError(f'Options required for {q_type} questions')
        if q_type == 'multiple_choice' and v and len(v) < 2:
            raise ValueError('Multiple choice questions need at least 2 options')
        if q_type == 'multiple_choice' and v and len(v) > 10:
            raise ValueError('Multiple choice questions cannot have more than 10 options')
        return v
    
    @validator('correct_answer')
    def validate_correct_answer(cls, v, values):
        q_type = values.get('question_type')
        options = values.get('options') or []
        
        if q_type == 'multiple_choice':
            if isinstance(v, str):
                if v not in options:
                    raise ValueError('Correct answer must be one of the provided options')
            elif isinstance(v, list):
                for ans in v:
                    if ans not in options:
                        raise ValueError(f'Correct answer "{ans}" not in provided options')
            else:
                raise ValueError('Correct answer for multiple choice must be string or list of strings')
        
        elif q_type == 'true_false':
            if v not in ('true', 'false', True, False, 'True', 'False'):
                raise ValueError('True/False answer must be true or false')
        
        elif q_type == 'short_answer':
            if not isinstance(v, str) or not v.strip():
                raise ValueError('Short answer must be a non-empty string')
        
        elif q_type == 'essay':
            if not isinstance(v, str):
                raise ValueError('Essay answer key must be a string')
        
        elif q_type == 'matching':
            if not isinstance(v, dict):
                raise ValueError('Matching answer must be a dictionary mapping left to right')
            if options:
                left_items = [opt for opt in options if opt.startswith('LEFT:')]
                right_items = [opt for opt in options if opt.startswith('RIGHT:')]
                for left, right in v.items():
                    if left not in left_items:
                        raise ValueError(f'Left item "{left}" not in options')
                    if right not in right_items:
                        raise ValueError(f'Right item "{right}" not in options')
        
        elif q_type == 'fill_blank':
            if not isinstance(v, (str, list)):
                raise ValueError('Fill blank answer must be string or list of acceptable answers')
        
        return v
    
    @validator('points')
    def validate_points(cls, v):
        if v <= 0 or v > 100:
            raise ValueError('Points must be between 0.1 and 100')
        return v


class LMSCredentialsModel(BaseModel):
    """Pydantic model for LMS credentials validation."""
    
    lms_type: constr(regex=r'^(canvas|moodle|blackboard|d2l|google_classroom)$')
    base_url: constr(min_length=1, max_length=500, strip_whitespace=True)
    client_id: Optional[constr(min_length=1, max_length=200, strip_whitespace=True)] = None
    client_secret: Optional[constr(min_length=1, max_length=500, strip_whitespace=True)] = None
    access_token: Optional[constr(min_length=1, max_length=1000, strip_whitespace=True)] = None
    refresh_token: Optional[constr(min_length=1, max_length=1000, strip_whitespace=True)] = None
    api_key: Optional[constr(min_length=1, max_length=500, strip_whitespace=True)] = None
    username: Optional[constr(min