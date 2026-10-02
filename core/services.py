from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Generic, TypeVar
from pydantic import BaseModel, Field
from datetime import datetime

# Import existing models
from models import Question, Option, QuizEntity
from core.ai_solver import AICodeSolution, AISolution

T = TypeVar('T')
R = TypeVar('R')


class ServiceRequest(BaseModel):
    """Base model for all service requests."""
    request_id: str = Field(..., description="Unique identifier for the request")
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


class BaseService(ABC, Generic[T, R]):
    """Abstract base class for all services with lifecycle management."""
    
    def __init__(self, service_name: str, config: Optional[Dict[str, Any]] = None):
        self.service_name = service_name
        self.config = config or {}
        self._started = False
        self._health_status = "unknown"
    
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


class QuizSessionService(BaseService[QuizSessionRequest, QuizEntity]):
    """Abstract service for quiz session lifecycle management."""
    
    @abstractmethod
    async def create_session(self, request: QuizSessionRequest) -> ServiceResponse[QuizEntity]:
        """Create a new quiz session."""
        pass
    
    @abstractmethod
    async def get_session(self, session_id: str) -> ServiceResponse[QuizEntity]:
        """Retrieve an existing quiz session."""
        pass
    
    @abstractmethod
    async def update_session(self, session_id: str, updates: Dict[str, Any]) -> ServiceResponse[QuizEntity]:
        """Update quiz session state."""
        pass
    
    @abstractmethod
    async def end_session(self, session_id: str, reason: str = "completed") -> ServiceResponse[QuizEntity]:
        """End a quiz session."""
        pass
    
    @abstractmethod
    async def list_sessions(self, user_id: Optional[str] = None, quiz_id: Optional[str] = None) -> ServiceResponse[List[QuizEntity]]:
        """List quiz sessions with optional filters."""
        pass


class QuestionProcessingService(BaseService[QuestionSolveRequest, AISolution]):
    """Abstract service for question parsing, analysis, and solving."""
    
    @abstractmethod
    async def parse_question(self, raw_content: str, source_format: str = "html") -> ServiceResponse[Question]:
        """Parse raw question content into structured Question model."""
        pass
    
    @abstractmethod
    async def analyze_question(self, question: Question) -> ServiceResponse[Dict[str, Any]]:
        """Analyze question for type, difficulty, topics, etc."""
        pass
    
    @abstractmethod
    async def solve_question(self, request: QuestionSolveRequest) -> ServiceResponse[AISolution]:
        """Solve a question using AI solvers."""
        pass
    
    @abstractmethod
    async def validate_solution(self, question: Question, solution: AISolution) -> ServiceResponse[bool]:
        """Validate a solution against the question."""
        pass
    
    @abstractmethod
    async def get_solution_explanation(self, question: Question, solution: AISolution) -> ServiceResponse[str]:
        """Generate human-readable explanation for a solution."""
        pass


class LMSIntegrationService(BaseService[LMSSubmissionRequest, Dict[str, Any]]):
    """Abstract service for LMS platform interactions."""
    
    @abstractmethod
    async def authenticate(self, credentials: Dict[str, Any]) -> ServiceResponse[bool]:
        """Authenticate with the LMS platform."""
        pass
    
    @abstractmethod
    async def fetch_quiz(self, quiz_id: str, course_id: Optional[str] = None) -> ServiceResponse[QuizEntity]:
        """Fetch quiz details from LMS."""
        pass
    
    @abstractmethod
    async def fetch_questions(self, quiz_id: str) -> ServiceResponse[List[Question]]:
        """Fetch all questions for a quiz from LMS."""
        pass
    
    @abstractmethod
    async def submit_answers(self, request: LMSSubmissionRequest) -> ServiceResponse[Dict[str, Any]]:
        """Submit answers to LMS."""
        pass
    
    @abstractmethod
    async def get_submission_result(self, submission_id: str) -> ServiceResponse[Dict[str, Any]]:
        """Get submission results from LMS."""
        pass
    
    @abstractmethod
    async def get_gradebook(self, course_id: str, user_id: Optional[str] = None) -> ServiceResponse[Dict[str, Any]]:
        """Fetch gradebook data from LMS."""
        pass


class ServiceRegistry:
    """Registry for service instances with dependency injection support."""
    
    def __init__(self):
        self._services: Dict[str, BaseService] = {}
        self._factories: Dict[str, callable] = {}
    
    def register_factory(self, service_type: str, factory: callable) -> None:
        """Register a factory function for a service type."""
        self._factories[service_type] = factory
    
    def register_instance(self, service_type: str, instance: BaseService) -> None:
        """Register a service instance."""
        self._services[service_type] = instance
    
    def get_service(self, service_type: str) -> Optional[BaseService]:
        """Get a service instance by type."""
        return self._services.get(service_type)