```python
import time
from fastapi import APIRouter, Request, status, HTTPException, Depends, Body, Path
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from src.api.health import router as health_router
from src.config import get_settings
from src.utils.logger import get_logger
from src.core.quiz_service import QuizService
from src.core.validation import (
    QuizCreate,
    QuizUpdate,
    QuizResponse,
    QuestionCreate,
    QuestionResponse,
    AttemptCreate,
    AttemptResponse,
)
from src.core.telemetry import telemetry
from src.core.models import Quiz, Question, Attempt

logger = get_logger(__name__)
settings = get_settings()

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health_router, tags=["health"])


def get_quiz_service() -> QuizService:
    """Dependency to get QuizService instance."""
    return QuizService()


@api_router.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Log incoming requests and outgoing responses."""
    start_time = time.time()
    
    logger.info(
        "Incoming request",
        extra={
            "method": request.method,
            "url": str(request.url),
            "client_ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
        }
    )
    
    try:
        response = await call_next(request)
    except Exception as exc:
        logger.exception(
            "Request failed",
            extra={
                "method": request.method,
                "url": str(request.url),
                "error": str(exc),
            }
        )
        raise
    
    process_time = time.time() - start_time
    logger.info(
        "Request completed",
        extra={
            "method": request.method,
            "url": str(request.url),
            "status_code": response.status_code,
            "process_time_ms": round(process_time * 1000, 2),
        }
    )
    
    response.headers["X-Process-Time"] = str(process_time)
    return response


@api_router.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors with structured response."""
    logger.warning(
        "Validation error",
        extra={
            "method": request.method,
            "url": str(request.url),
            "errors": exc.errors(),
        }
    )
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": exc.errors(),
            }
        },
    )


@api_router.post(
    "/quizzes",
    response_model=QuizResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["quizzes"],
    summary="Create a new quiz",
)
async def create_quiz(
    quiz_data: QuizCreate = Body(...),
    quiz_service: QuizService = Depends(get_quiz_service),
):
    """Create a new quiz with validation and telemetry."""
    telemetry.record_event("quiz_create_requested", {"title": quiz_data.title})
    
    try:
        quiz = quiz_service.create_quiz(quiz_data)
        telemetry.record_event("quiz_created", {"quiz_id": quiz.id, "title": quiz.title})
        return QuizResponse.model_validate(quiz)
    except ValueError as e:
        telemetry.record_event("quiz_create_failed", {"error": str(e)})
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@api_router.get(
    "/quizzes/{quiz_id}",
    response_model=QuizResponse,
    status_code=status.HTTP_200_OK,
    tags=["quizzes"],
    summary="Get a quiz by ID",
)
async def get_quiz(
    quiz_id: str = Path(..., description="Quiz ID"),
    quiz_service: QuizService = Depends(get_quiz_service),
):
    """Retrieve a quiz by its ID."""
    telemetry.record_event("quiz_retrieve_requested", {"quiz_id": quiz_id})
    
    quiz = quiz_service.get_quiz(quiz_id)
    if not quiz:
        telemetry.record_event("quiz_not_found", {"quiz_id": quiz_id})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz not found")
    
    telemetry.record_event("quiz_retrieved", {"quiz_id": quiz_id})
    return QuizResponse.model_validate(quiz)


@api_router.put(
    "/quizzes/{quiz_id}",
    response_model=QuizResponse,
    status_code=status.HTTP_200_OK,
    tags=["quizzes"],
    summary="Update a quiz",
)
async def update_quiz(
    quiz_id: str = Path(..., description="Quiz ID"),
    quiz_data: QuizUpdate = Body(...),
    quiz_service: QuizService = Depends(get_quiz_service),
):
    """Update an existing quiz."""
    telemetry.record_event("quiz_update_requested", {"quiz_id": quiz_id})
    
    try:
        quiz = quiz_service.update_quiz(quiz_id, quiz_data)
        if not quiz:
            telemetry.record_event("quiz_not_found", {"quiz_id": quiz_id})
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz not found")
        
        telemetry.record_event("quiz_updated", {"quiz_id": quiz_id})
        return QuizResponse.model_validate(quiz)
    except ValueError as e:
        telemetry.record_event("quiz_update_failed", {"quiz_id": quiz_id, "error": str(e)})
        raise HTTPException(status_code=status.HTTP_400_BAD