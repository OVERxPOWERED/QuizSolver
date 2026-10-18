```python
import re
import html
import uuid
from typing import Any, Optional, List, Dict, Union
from pydantic import BaseModel, field_validator, model_validator, ValidationError as PydanticValidationError
from pydantic_core import PydanticCustomError


class ValidationError(Exception):
    """Custom validation error for quiz service."""
    
    def __init__(self, message: str, code: str = "VALIDATION_ERROR", details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(message)


def sanitize_string(value: str, max_length: Optional[int] = None, allow_html: bool = False) -> str:
    """
    Sanitize input string by stripping HTML/JS and normalizing whitespace.
    
    Args:
        value: Input string to sanitize
        max_length: Optional maximum length to truncate to
        allow_html: If True, allows safe HTML tags (default: False)
    
    Returns:
        Sanitized string
    """
    if not isinstance(value, str):
        value = str(value)
    
    # Strip null bytes and control characters
    value = value.replace('\x00', '').replace('\r', '')
    
    if not allow_html:
        # Escape HTML entities to prevent XSS
        value = html.escape(value, quote=True)
        
        # Additional protection against script injection attempts
        value = re.sub(r'(?i)<script[^>]*>.*?</script>', '', value)
        value = re.sub(r'(?i)javascript:', '', value)
        value = re.sub(r'(?i)on\w+\s*=', '', value)
    else:
        # Allow only safe HTML tags
        allowed_tags = ['b', 'i', 'u', 'em', 'strong', 'p', 'br', 'ul', 'ol', 'li']
        # This is a simple approach; in production consider using bleach library
        value = html.escape(value, quote=True)
        for tag in allowed_tags:
            value = value.replace(f'&lt;{tag}&gt;', f'<{tag}>').replace(f'&lt;/{tag}&gt;', f'</{tag}>')
    
    # Normalize whitespace
    value = re.sub(r'\s+', ' ', value).strip()
    
    # Truncate if max_length specified
    if max_length and len(value) > max_length:
        value = value[:max_length].rstrip()
    
    return value


def validate_quiz_id(quiz_id: Union[str, uuid.UUID]) -> uuid.UUID:
    """
    Validate and parse quiz ID as UUID.
    
    Args:
        quiz_id: Quiz ID as string or UUID
        
    Returns:
        Validated UUID object
        
    Raises:
        ValidationError: If quiz_id is not a valid UUID
    """
    if isinstance(quiz_id, uuid.UUID):
        return quiz_id
    
    if not isinstance(quiz_id, str):
        raise ValidationError(
            "Quiz ID must be a string or UUID",
            code="INVALID_QUIZ_ID_TYPE",
            details={"received_type": type(quiz_id).__name__}
        )
    
    quiz_id = quiz_id.strip()
    
    if not quiz_id:
        raise ValidationError(
            "Quiz ID cannot be empty",
            code="EMPTY_QUIZ_ID"
        )
    
    try:
        return uuid.UUID(quiz_id)
    except ValueError:
        raise ValidationError(
            f"Invalid quiz ID format: {quiz_id}",
            code="INVALID_QUIZ_ID_FORMAT",
            details={"quiz_id": quiz_id}
        )


class QuizPayload(BaseModel):
    """Payload for quiz creation/update."""
    
    title: str
    description: Optional[str] = None
    time_limit_seconds: Optional[int] = None
    max_attempts: Optional[int] = 1
    is_published: bool = False
    passing_score: Optional[float] = None
    shuffle_questions: bool = False
    shuffle_options: bool = False
    
    @field_validator('title')
    @classmethod
    def validate_title(cls, v: str) -> str:
        sanitized = sanitize_string(v, max_length=255)
        if not sanitized:
            raise PydanticCustomError(
                'empty_title',
                'Quiz title cannot be empty',
                {'field': 'title'}
            )
        if len(sanitized) < 3:
            raise PydanticCustomError(
                'title_too_short',
                'Quiz title must be at least 3 characters',
                {'field': 'title', 'min_length': 3}
            )
        return sanitized
    
    @field_validator('description')
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        sanitized = sanitize_string(v, max_length=5000, allow_html=True)
        return sanitized if sanitized else None
    
    @field_validator('time_limit_seconds')
    @classmethod
    def validate_time_limit(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return None
        if v < 0:
            raise PydanticCustomError(
                'negative_time_limit',
                'Time limit cannot be negative',
                {'field': 'time_limit_seconds'}
            )
        if v > 86400:  # 24 hours max
            raise PydanticCustomError(
                'time_limit_too_long',
                'Time limit cannot exceed 24 hours (86400 seconds)',
                {'field': 'time_limit_seconds', 'max': 86400}
            )
        return v
    
    @field_validator('max_attempts')
    @classmethod
    def validate_max_attempts(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return 1
        if v < 1:
            raise PydanticCustomError(
                'invalid_max_attempts',
                'Max attempts must be at least 1',
                {'field': 'max_attempts', 'min': 1}
            )
        if v > 100:
            raise PydanticCustomError(
                'max_attempts_too_high',
                'Max attempts cannot exceed 100',
                {'field': 'max_attempts', 'max': 100}
            )
        return v
    
    @field_validator('passing_score')
    @classmethod
    def validate_passing_score(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        if v < 0 or v > 100:
            raise PydanticCustomError(
                'invalid_passing_score',
                'Passing score must be between 0 and 100',
                {'field': 'passing_score', 'min': 0, 'max': 100}
            )
        return round(v, 2)


class QuestionPayload(BaseModel):
    """Payload for question creation/update."""
    
    text: str
    type: str  # 'single_choice', 'multiple_choice', 'true_false', 'short_answer', 'essay'
    options: Optional[List[str]] = None
    correct_answer: Union