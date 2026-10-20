```python
import time
from typing import Optional
from fastapi import APIRouter, Request, status, HTTPException, Depends, Body, Path, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.api.health import router as health_router
from src.api.schemas import (
    QuizCreate,
    QuizUpdate,
    QuizResponse,
    QuizListResponse,
    QuestionCreate,
    QuestionResponse,
    AttemptCreate,
    AttemptResponse,
    AttemptResultResponse,
    PaginationParams,
)
from src.config import get_settings
from src.utils.logger import get_logger
from src.core.quiz_service import QuizService
from src.core.telemetry import telemetry

logger = get_logger(__name__)
settings = get_settings()

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health_router, tags=["health"])


def get_quiz_service() -> QuizService:
    """Dependency to get QuizService instance."""
    return QuizService()


def get_pagination_params(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
) -> PaginationParams:
    """Dependency for pagination parameters."""
    return PaginationParams(page=page, page_size=page_size)


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
    with telemetry.span("create_quiz") as span:
        span.set_attribute("quiz.title", quiz_data.title)
        telemetry.record_event("quiz_create_requested", {"title": quiz_data.title})
        
        try:
            quiz = quiz_service.create_quiz(quiz_data)
            telemetry.record_event("quiz_created", {"quiz_id": quiz.id, "title": quiz.title})
            span.set_attribute("quiz.id", quiz.id)
            return QuizResponse.model_validate(quiz)
        except ValueError as e:
            telemetry.record_event("quiz_create_failed", {"error": str(e)})
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@api_router.get(
    "/quizzes",
    response_model=QuizListResponse,
    status_code=status.HTTP_200_OK,
    tags=["quizzes"],
    summary="List quizzes with pagination",
)
async def list_quizzes(
    pagination: PaginationParams = Depends(get_pagination_params),
    quiz_service: QuizService = Depends(get_quiz_service),
):
    """Retrieve a paginated list of quizzes."""
    with telemetry.span("list_quizzes") as span:
        span.set_attribute("pagination.page", pagination.page)
        span.set_attribute("pagination.page_size", pagination.page_size)
        telemetry.record_event("quiz_list_requested", {"page": pagination.page, "page_size": pagination.page_size})
        
        try:
            quizzes, total = quiz_service.list_quizzes(pagination.page, pagination.page_size)
            return QuizListResponse(
                items=[QuizResponse.model_validate(q) for q in quizzes],
                total=total,
                page=pagination.page,
                page_size=pagination.page_size,
            )
        except Exception as e:
            telemetry.record_event("quiz_list_failed", {"error": str(e)})
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve quizzes")


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
    with telemetry.span("get_quiz") as span:
        span.set_attribute("quiz.id", quiz_id)
        telemetry.record_event("quiz_get_requested", {"quiz_id": quiz_id})
        
        quiz = quiz_service.get_quiz(quiz_id)
        if not quiz