from fastapi import APIRouter, Response, HTTPException, status
from prometheus_client import generate_latest

from core.prometheus_metrics import (
    quiz_runs_total,
    ai_solver_latency_seconds,
    get_metrics,
)
from services.quiz_service import run_quiz, get_quiz_result
from api.schemas import QuizRunRequest, QuizRunResponse, QuizResultResponse

api_router = APIRouter()


@api_router.get("/metrics")
async def metrics() -> Response:
    """Expose Prometheus metrics for scraping."""
    return Response(
        content=get_metrics(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@api_router.get("/healthz")
async def healthz() -> dict:
    """Kubernetes liveness probe endpoint."""
    return {"status": "ok"}


@api_router.post(
    "/quiz/run",
    response_model=QuizRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def run_quiz_endpoint(request: QuizRunRequest) -> QuizRunResponse:
    """Execute a quiz run with AI solver and record metrics."""
    quiz_runs_total.inc()

    with ai_solver_latency_seconds.time():
        quiz_run = await run_quiz(
            request.questions, request.category, request.difficulty
        )

    return QuizRunResponse(
        quiz_id=quiz_run.quiz_id,
        status=quiz_run.status,
        score=quiz_run.score,
        created_at=quiz_run.created_at,
    )


@api_router.get("/quiz/{quiz_id}", response_model=QuizResultResponse)
async def get_quiz_result_endpoint(quiz_id: str) -> QuizResultResponse:
    """Retrieve quiz result by ID."""
    quiz_result = await get_quiz_result(quiz_id)
    if not quiz_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Quiz not found"
        )

    return QuizResultResponse(
        quiz_id=quiz_result.quiz_id,
        questions=quiz_result.questions,
        answers=quiz_result.answers,
        score=quiz_result.score,
        status=quiz_result.status,
        completed_at=quiz_result.completed_at,
    )