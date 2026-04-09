"""API routes for the dashboard."""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from app.store import WORKERS, TASKS, VERIFICATIONS
from app.tools.task_tools import assign_task, list_tasks, update_task_status, get_pending_tasks
from app.tools.verification_tools import request_verification, process_verification, get_pending_verifications
from app.tools.performance_tools import (
    get_worker_performance,
    get_all_workers_performance,
    get_productivity_trends,
    get_task_distribution,
)
from app.tools.salary_tools import get_salary_recommendation, get_all_salary_recommendations
from app.tools.recommendation_tools import suggest_next_tasks, get_idle_workers


router = APIRouter(prefix="/api")


# ── Schemas ─────────────────────────────────────────────────────────

class AssignTaskRequest(BaseModel):
    worker_id: str
    task_description: str


class UpdateTaskRequest(BaseModel):
    task_id: str
    new_status: str
    worker_response: Optional[str] = None


class VerifyRequest(BaseModel):
    verification_id: str
    confirmed: bool
    secretary_notes: Optional[str] = None


# ── Worker endpoints ────────────────────────────────────────────────

@router.get("/workers")
def api_get_workers():
    return {"workers": list(WORKERS.values())}


@router.get("/workers/{worker_id}")
def api_get_worker(worker_id: str):
    if worker_id not in WORKERS:
        return {"error": "Worker not found"}
    return {"worker": WORKERS[worker_id]}


# ── Task endpoints ──────────────────────────────────────────────────

@router.post("/tasks")
def api_assign_task(req: AssignTaskRequest):
    return assign_task(req.worker_id, req.task_description)


@router.get("/tasks")
def api_list_tasks(worker_id: Optional[str] = None, status: Optional[str] = None):
    return list_tasks(worker_id, status)


@router.put("/tasks/status")
def api_update_task(req: UpdateTaskRequest):
    return update_task_status(req.task_id, req.new_status, req.worker_response)


@router.get("/tasks/pending")
def api_pending_tasks():
    return get_pending_tasks()


# ── Verification endpoints ──────────────────────────────────────────

@router.post("/verifications/{task_id}")
def api_request_verification(task_id: str):
    return request_verification(task_id)


@router.put("/verifications")
def api_process_verification(req: VerifyRequest):
    return process_verification(req.verification_id, req.confirmed, req.secretary_notes)


@router.get("/verifications/pending")
def api_pending_verifications():
    return get_pending_verifications()


# ── Performance endpoints ───────────────────────────────────────────

@router.get("/performance")
def api_all_performance():
    return get_all_workers_performance()


@router.get("/performance/{worker_id}")
def api_worker_performance(worker_id: str):
    return get_worker_performance(worker_id)


@router.get("/trends")
def api_trends(period: str = "weekly"):
    return get_productivity_trends(period)


@router.get("/distribution")
def api_distribution():
    return get_task_distribution()


# ── Salary endpoints ────────────────────────────────────────────────

@router.get("/salary")
def api_all_salary():
    return get_all_salary_recommendations()


@router.get("/salary/{worker_id}")
def api_worker_salary(worker_id: str):
    return get_salary_recommendation(worker_id)


# ── Recommendation endpoints ────────────────────────────────────────

@router.get("/recommendations/{worker_id}")
def api_suggest_tasks(worker_id: str):
    return suggest_next_tasks(worker_id)


@router.get("/idle-workers")
def api_idle_workers():
    return get_idle_workers()
