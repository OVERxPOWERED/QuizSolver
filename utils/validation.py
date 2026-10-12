```python
import os
import re
import html
import jwt
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

import bleach
from pydantic import BaseModel, field_validator, ValidationError as PydanticValidationError
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


def sanitize_html_input(html_content: str, max_length: int = 10000) -> str:
    """
    Sanitize HTML input using bleach to prevent XSS attacks.
    
    Args:
        html_content: Raw HTML string to sanitize
        max_length: Maximum allowed length after sanitization
        
    Returns:
        Sanitized HTML string safe for rendering
    """
    if not html_content:
        return ""
    
    allowed_tags = [
        'p', 'br', 'strong', 'em', 'u', 's', 'sub', 'sup',
        'ul', 'ol', 'li', 'blockquote', 'code', 'pre',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'a', 'img', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
        'div', 'span', 'hr'
    ]
    
    allowed_attributes = {
        'a': ['href', 'title', 'target', 'rel'],
        'img': ['src', 'alt', 'title', 'width', 'height'],
        'code': ['class'],
        'pre': ['class'],
        'div': ['class'],
        'span': ['class'],
        'th': ['scope'],
        'td': ['colspan', 'rowspan'],
    }
    
    allowed_protocols = ['http', 'https', 'mailto']
    
    sanitized = bleach.clean(
        html_content,
        tags=allowed_tags,
        attributes=allowed_attributes,
        protocols=allowed_protocols,
        strip=True,
        strip_comments=True
    )
    
    sanitized = bleach.linkify(sanitized, parse_email=True)
    
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]
        logger.warning(f"HTML content truncated to {max_length} characters")
    
    return sanitized


def sanitize_plain_text(text: str, max_length: int = 5000) -> str:
    """
    Sanitize plain text input by escaping HTML and limiting length.
    
    Args:
        text: Raw text string to sanitize
        max_length: Maximum allowed length
        
    Returns:
        Sanitized plain text string
    """
    if not text:
        return ""
    
    sanitized = html.escape(text.strip())
    
    sanitized = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', sanitized)
    
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]
        logger.warning(f"Plain text truncated to {max_length} characters")
    
    return sanitized


def validate_quiz_id(quiz_id: str) -> bool:
    """
    Validate quiz ID format (UUID v4 or alphanumeric with hyphens).
    
    Args:
        quiz_id: Quiz identifier string
        
    Returns:
        True if valid format
        
    Raises:
        ValidationError: If format is invalid
    """
    if not quiz_id:
        raise ValidationError("Quiz ID cannot be empty", field="quiz_id", value=quiz_id)
    
    uuid_pattern = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
        re.IGNORECASE
    )
    
    alphanumeric_pattern = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')
    
    if not (uuid_pattern.match(quiz_id) or alphanumeric_pattern.match(quiz_id)):
        raise ValidationError(
            "Invalid quiz ID format. Must be UUID v4 or alphanumeric (max 64 chars)",
            field="quiz_id",
            value=quiz_id
        )
    
    return True


def validate_session_token(token: str, secret_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Validate JWT session token format and signature.
    
    Args:
        token: JWT token string
        secret_key: Secret key for signature verification (optional, uses settings if not provided)
        
    Returns:
        Decoded token payload
        
    Raises:
        ValidationError: If token is invalid, expired, or malformed
    """
    if not token:
        raise ValidationError("Session token cannot be empty", field="session_token", value=token)
    
    if not secret_key:
        settings = get_settings()
        secret_key = settings.jwt_secret_key
    
    try:
        parts = token.split('.')
        if len(parts) != 3:
            raise ValidationError("Invalid JWT format: must have 3 parts", field="session_token", value=token)
        
        payload = jwt.decode(
            token,
            secret_key,
            algorithms=["HS256"],
            options={"verify_exp": True, "verify_iat": True}
        )
        
        required_claims = ['sub', 'iat', 'exp', 'type']
        for claim in required_claims:
            if claim not in payload:
                raise ValidationError(f"Missing required claim: {claim}", field="session_token", value=token)
        
        if payload.get('type') not in ('access', 'refresh'):
            raise ValidationError("Invalid token type", field="session_token", value=token)
        
        return payload
        
    except jwt.ExpiredSignatureError:
        raise ValidationError("Session token has expired", field="session_token", value=token)
    except jwt.InvalidTokenError as e:
        raise ValidationError(f"Invalid session token: {str(e)}", field="session_token", value=token)


def validate_url(url: str, allowed_schemes: Optional[List[str]] = None) -> bool:
    """
    Validate URL format and scheme.