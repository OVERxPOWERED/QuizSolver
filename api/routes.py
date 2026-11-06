import os
import json
import asyncio
from typing import Optional, List
from fastapi import APIRouter, Response, HTTPException, status, BackgroundTasks
from prometheus_client import generate_latest

from core.prometheus_metrics import (
    quiz_runs_total,
    ai_solver_latency_seconds,
    get_metrics,
)
from services.quiz_service import run_quiz, get_quiz_result
from api.schemas import QuizRunRequest, QuizRunResponse, QuizResultResponse
from core.alerting_engine import AlertingEngine
from core.alerting_notifiers import get_notifier
from src.api.alerting_schemas import AlertRule, NotificationChannel

api_router = APIRouter()

alerting_engine: Optional[AlertingEngine] = None
_evaluation_task: Optional[asyncio.Task] = None


async def _alert_callback(rule: AlertRule, payload: dict) -> None:
    """Callback invoked by AlertingEngine when a rule fires."""
    for channel in rule.notification_channels:
        notifier = get_notifier(channel.type)
        if notifier:
            await notifier.send(payload, channel)


async def _load_rules_from_config() -> List[AlertRule]:
    """Load alert rules from ALERT_RULES_JSON env var (JSON string or file path)."""
    raw = os.getenv("ALERT_RULES_JSON")
    if not raw:
        return []
    try:
        # If it's a file path, read it
        if os.path.isfile(raw):
            with open(raw, "r") as f:
                data = json.load(f)
        else:
            data = json.loads(raw)
        return [AlertRule(**item) for item in data]
    except Exception as e:
        # Log error but don't crash startup
        print(f"Failed to load alert rules: {e}")
        return []


@api_router.on_event("startup")
async def start_alerting_engine() -> None:
    global alerting_engine, _evaluation_task
    rules = await _load_rules_from_config()
    alerting_engine = AlertingEngine(rules=rules, callback=_alert_callback)
    _evaluation_task = asyncio.create_task(alerting_engine.evaluation_loop())


@api_router.on_event("shutdown")
async def stop_alerting_engine() -> None:
    global _evaluation_task
    if _evaluation_task:
        _evaluation_task.cancel()
        try:
            await _evaluation_task
        except asyncio.CancelledError:
            pass


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


# ------------------- Alerting Rules CRUD -------------------

@api_router.get("/alerting/rules", response_model=List[AlertRule])
async def list_alert_rules() -> List[AlertRule]:
    """List all configured alert rules."""
    if not alerting_engine:
        raise HTTPException(status_code=503, detail="Alerting engine not initialized")
    return alerting_engine.get_rules()


@api_router.post("/alerting/rules", response_model=AlertRule, status_code=status.HTTP_201_CREATED)
async def create_alert_rule(rule: AlertRule) -> AlertRule:
    """Create a new alert rule and add it to the engine."""
    if not alerting_engine:
        raise HTTPException(status_code=503, detail="Alerting engine not initialized")
    # Validate rule (pydantic does basic validation)
    alerting_engine.add_rule(rule)
    return rule


@api_router.put("/alerting/rules/{rule_name}", response_model=AlertRule)
async def update_alert_rule(rule_name: str, rule: AlertRule) -> AlertRule:
    """Update an existing alert rule."""
    if not alerting_engine:
        raise HTTPException(status_code=503, detail="Alerting engine not initialized")
    if rule.name != rule_name:
        raise HTTPException(status_code=400, detail="Rule name in path and body must match")
    alerting_engine.remove_rule(rule_name)
    alerting_engine.add_rule(rule)
    return rule


@api_router.delete("/alerting/rules/{rule_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_rule(rule_name: str) -> None:
    """Delete an alert rule by name."""
    if not alerting_engine:
        raise HTTPException(status_code=503, detail="Alerting engine not initialized")
    alerting_engine.remove_rule(rule_name)
    return None