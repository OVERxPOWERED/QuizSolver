import re
import html
import uuid
from typing import Any, Optional, Dict, Union
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

    value = value.replace('\x00', '').replace('\r', '')

    if not allow_html:
        value = html.escape(value, quote=True)
        value = re.sub(r'(?i)<script[^>]*>.*?</script>', '', value)
        value = re.sub(r'(?i)javascript:', '', value)
        value = re.sub(r'(?i)on\w+\s*=', '', value)
    else:
        allowed_tags = ['b', 'i', 'u', 'em', 'strong', 'p', 'br', 'ul', 'ol', 'li']
        value = html.escape(value, quote=True)
        for tag in allowed_tags:
            value = value.replace(f'&lt;{tag}&gt;', f'<{tag}>').replace(f'&lt;/{tag}&gt;', f'</{tag}>')

    value = re.sub(r'\s+', ' ', value).strip()

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
    except ValueError as e:
        raise ValidationError(
            f"Invalid quiz ID format: {quiz_id}",
            code="INVALID_QUIZ_ID_FORMAT",
            details={"input": quiz_id, "error": str(e)}
        )