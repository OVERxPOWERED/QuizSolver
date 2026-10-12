```python
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Generic, TypeVar, Protocol
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
import logging
import uuid
import asyncio
from contextlib import asynccontextmanager

# Import existing models
from models import Question, Option, QuizEntity
from core.ai_solver import AICodeSolution, AISolution

# Import validation utilities
from utils.validation import (
    validate_quiz_data,
    validate_session_data,
    validate_answer_submission,
    ValidationError
)

T = TypeVar('T')
R = TypeVar('R')

logger = logging.getLogger(__name__)


class SessionState(str, Enum):
    """Quiz session state machine states."""
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    EXPIRED = "expired"


class ServiceRequest(BaseModel):
    """Base model for all service requests."""
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique identifier for the request")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ServiceResponse(BaseModel, Generic[T]):
    """Base model for all service responses."""
    request_id: str
    success: bool
    data: Optional[T] = None
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    processing_time_ms: float = 0.0


class QuizSessionRequest(ServiceRequest):
    """Request model for quiz session operations."""
    quiz_id: str
    user_id: str
    session_config: Dict[str, Any] = Field(default_factory=dict)
    lms_context: Optional[Dict[str, Any]] = None


class QuestionSolveRequest(ServiceRequest):
    """Request model for question solving operations."""
    question: Question
    session_id: str
    solver_config: Dict[str, Any] = Field(default_factory=dict)
    context: Optional[Dict[str, Any]] = None


class LMSSubmissionRequest(ServiceRequest):
    """Request model for LMS submission operations."""
    session_id: str
    answers: Dict[str, Any]  # question_id -> answer
    submission_type: str = "final"  # "draft", "final", "practice"
    lms_payload: Optional[Dict[str, Any]] = None


class DatabaseProtocol(Protocol):
    """Protocol for database operations - enables dependency injection."""
    
    async def create_quiz(self, quiz: QuizEntity) -> QuizEntity:
        ...
    
    async def get_quiz(self, quiz_id: str) -> Optional[QuizEntity]:
        ...
    
    async def list_quizzes(self, filters: Optional[Dict[str, Any]] = None, limit: int = 100, offset: int = 0) -> List[QuizEntity]:
        ...
    
    async def delete_quiz(self, quiz_id: str) -> bool:
        ...
    
    async def create_session(self, session: QuizEntity) -> QuizEntity:
        ...
    
    async def get_session(self, session_id: str) -> Optional[QuizEntity]:
        ...
    
    async def update_session(self, session_id: str, updates: Dict[str, Any]) -> Optional[QuizEntity]:
        ...
    
    async def list_sessions(self, user_id: Optional[str] = None, quiz_id: Optional[str] = None, state: Optional[SessionState] = None) -> List[QuizEntity]:
        ...
    
    async def save_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        ...
    
    async def get_result(self, session_id: str) -> Optional[Dict[str, Any]]:
        ...
    
    async def health_check(self) -> Dict[str, Any]:
        ...


class BaseService(ABC, Generic[T, R]):
    """Abstract base class for all services with lifecycle management."""
    
    def __init__(self, service_name: str, config: Optional[Dict[str, Any]] = None, db: Optional[DatabaseProtocol] = None):
        self.service_name = service_name
        self.config = config or {}
        self._db = db
        self._started = False
        self._health_status = "unknown"
        self._lock = asyncio.Lock()
    
    @property
    def db(self) -> DatabaseProtocol:
        if self._db is None:
            raise RuntimeError(f"{self.service_name}: Database not injected. Call set_database() first.")
        return self._db
    
    def set_database(self, db: DatabaseProtocol) -> None:
        """Inject database dependency."""
        self._db = db
    
    @abstractmethod
    async def start(self) -> bool:
        """Initialize service resources and connections."""
        pass
    
    @abstractmethod
    async def stop(self) -> bool:
        """Clean up service resources and connections."""
        pass
    
    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """Return service health status and metrics."""
        pass
    
    @abstractmethod
    async def process(self, request: T) -> ServiceResponse[R]:
        """Process a service request and return a response."""
        pass
    
    @property
    def is_started(self) -> bool:
        return self._started
    
    @property
    def health_status(self) -> str:
        return self._health_status
    
    async def _execute_with_timing(self, operation: str, coro) -> tuple[Any, float]:
        """Execute a coroutine with timing and error handling."""
        start_time = datetime.utcnow()
        try:
            result = await coro
            elapsed_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
            logger.debug(f"{self.service_name}.{operation} completed in {elapsed_ms:.2f}ms")
            return result, elapsed_ms
        except Exception as e:
            elapsed_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
            logger.error(f"{self.service_name}.{operation} failed after {elapsed_ms:.2f}ms: {e}")
            raise


class QuizService(BaseService[ServiceRequest, QuizEntity]):
    """Service for quiz lifecycle management: CRUD operations on quizzes."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None, db: Optional[DatabaseProtocol] = None):
        super().__init__("QuizService", config, db)
        self._cache: Dict[str, QuizEntity] = {}
        self._cache_ttl = self.config.get("cache_ttl_seconds", 300)
    
    async def start(self) -> bool:
        """Initialize quiz service."""
        async with self._lock:
            if self._started:
                logger.warning("QuizService already started")
                return True
            
            try:
                db_health = await self.db.health_check()
                if not db_health.get("healthy", False):
                    raise RuntimeError(f"Database unhealthy: {db_health}")
                
                self._started = True
                self._health_status = "healthy"
                logger.info