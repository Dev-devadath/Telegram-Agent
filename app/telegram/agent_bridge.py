"""
Bridge between Telegram bot and ADK agents.
Processes worker responses, manager confirmations, and generates reports.
"""

import asyncio
from google.adk.runners import InMemoryRunner
from google.genai import types

from app.agents.manager_agent import manager_agent
from app.store import (
    WORKERS, TASKS, TASK_TEMPLATES, DAILY_TASK_STATUS,
    generate_id, now_iso,
)
from app.tools.task_tools import assign_task, list_tasks, update_task_status
from app.tools.verification_tools import request_verification, process_verification
from app.tools.performance_tools import (
    get_worker_performance,
    get_all_workers_performance,
    get_productivity_trends,
    get_task_distribution,
)
from app.tools.salary_tools import get_all_salary_recommendations


# ── ADK Runner (shared) ────────────────────────────────────────────
runner = InMemoryRunner(agent=manager_agent, app_name="household_tg")
_sessions: dict[str, str] = {}


async def _get_session(user_id: str) -> str:
    """Get or create an ADK session for a user."""
    if user_id not in _sessions:
        session = await runner.session_service.create_session(
            app_name="household_tg",
            user_id=user_id,
        )
        _sessions[user_id] = session.id
    return _sessions[user_id]


async def ask_agent(user_id: str, message: str) -> str:
    """
    Send a message to the ADK manager agent and collect the text response.
    """
    session_id = await _get_session(user_id)
    parts: list[str] = []

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=types.Content(
            role="user",
            parts=[types.Part(text=message)],
        ),
    ):
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            if part.function_call or part.function_response:
                continue
            if part.text and part.text.strip():
                parts.append(part.text.strip())

    return "\n".join(parts) if parts else "No response from agent."


# ── Worker Task Helpers ─────────────────────────────────────────────

def get_worker_daily_tasks(worker_id: str) -> list[dict]:
    """
    Get today's tasks for a worker:
    1. Any existing assigned/in_progress tasks
    2. If none, auto-assign tasks from role templates
    """
    worker = WORKERS.get(worker_id)
    if not worker:
        return []

    # Existing pending tasks
    existing = [
        t for t in TASKS
        if t["worker_id"] == worker_id and t["status"] in ("assigned", "in_progress")
    ]

    # If worker has no pending tasks, auto-assign from templates
    if not existing:
        role = worker["role"]
        templates = TASK_TEMPLATES.get(role, [])
        # Pick up to 3 tasks
        for desc in templates[:3]:
            task = assign_task(worker_id, desc)
            if "error" not in task:
                existing.append(task)

    return existing


def prepare_broadcast() -> dict[str, list[dict]]:
    """
    Prepare daily task broadcast for all workers.
    Returns {worker_id: [task_dicts]} and populates DAILY_TASK_STATUS.
    """
    DAILY_TASK_STATUS.clear()
    result: dict[str, list[dict]] = {}

    for worker_id in WORKERS:
        tasks = get_worker_daily_tasks(worker_id)
        if tasks:
            result[worker_id] = tasks
            DAILY_TASK_STATUS[worker_id] = [
                {
                    "task_id": t["id"],
                    "description": t["description"],
                    "worker_response": None,     # True/False/None
                    "manager_confirmed": None,   # True/False/None
                }
                for t in tasks
            ]

    return result


def get_worker_by_task_id(task_id: str) -> str | None:
    """Find which worker_id a task belongs to (from DAILY_TASK_STATUS)."""
    for worker_id, entries in DAILY_TASK_STATUS.items():
        for entry in entries:
            if entry["task_id"] == task_id:
                return worker_id
    return None


# ── Response Processing ─────────────────────────────────────────────

def record_worker_response(worker_id: str, task_id: str, accepted: bool) -> str:
    """
    Record a worker's YES/NO response to a task.
    Updates both DAILY_TASK_STATUS and task status in store.
    """
    # Update daily tracking
    daily = DAILY_TASK_STATUS.get(worker_id, [])
    for entry in daily:
        if entry["task_id"] == task_id:
            entry["worker_response"] = accepted
            break

    # Update the actual task
    if accepted:
        update_task_status(task_id, "in_progress", "Accepted via Telegram")
    else:
        update_task_status(task_id, "rejected", "Declined via Telegram")

    worker_name = WORKERS.get(worker_id, {}).get("name", worker_id)
    task_desc = next(
        (e["description"] for e in daily if e["task_id"] == task_id), "Unknown task"
    )
    status = "✅ Accepted" if accepted else "❌ Declined"
    return f"{worker_name} → {task_desc}: {status}"


def is_worker_done_responding(worker_id: str) -> bool:
    """Check if all tasks for a worker have been responded to."""
    daily = DAILY_TASK_STATUS.get(worker_id, [])
    return len(daily) > 0 and all(e["worker_response"] is not None for e in daily)


def get_worker_response_summary(worker_id: str) -> str:
    """Format a summary of the worker's responses for the manager."""
    worker_name = WORKERS.get(worker_id, {}).get("name", worker_id)
    daily = DAILY_TASK_STATUS.get(worker_id, [])

    lines = [f"📋 *{worker_name}* — Task Responses:"]
    for entry in daily:
        icon = "✅" if entry["worker_response"] else "❌"
        lines.append(f"  {icon} {entry['description']}")

    accepted = sum(1 for e in daily if e["worker_response"])
    total = len(daily)
    lines.append(f"\n_Accepted {accepted}/{total} tasks_")
    return "\n".join(lines)


def record_manager_confirmation(worker_id: str, confirmed: bool) -> str:
    """
    Manager confirms or rejects a worker's batch.
    Triggers verification for accepted tasks.
    """
    daily = DAILY_TASK_STATUS.get(worker_id, [])
    worker_name = WORKERS.get(worker_id, {}).get("name", worker_id)

    for entry in daily:
        entry["manager_confirmed"] = confirmed
        if confirmed and entry["worker_response"]:
            # Request and auto-confirm verification for accepted tasks
            ver = request_verification(entry["task_id"])
            if "verification" in ver:
                process_verification(ver["verification"]["id"], True, "Confirmed by manager via Telegram")
                update_task_status(entry["task_id"], "completed")

    status = "✅ Confirmed" if confirmed else "❌ Rejected"
    return f"{status} all tasks for {worker_name}"


def get_workers_pending_confirmation() -> list[str]:
    """Get worker_ids that have responded but not yet confirmed by manager."""
    pending = []
    for worker_id, entries in DAILY_TASK_STATUS.items():
        all_responded = all(e["worker_response"] is not None for e in entries)
        any_unconfirmed = any(e["manager_confirmed"] is None for e in entries)
        if all_responded and any_unconfirmed:
            pending.append(worker_id)
    return pending


# ── Performance Report ──────────────────────────────────────────────

async def generate_performance_report() -> str:
    """Generate a performance report using the ADK agent."""
    report = await ask_agent(
        "manager_report",
        "Give me a detailed performance report for all workers. "
        "Include performance scores, completion rates, top performers, "
        "task distribution, and salary recommendations. "
        "Format it cleanly for a Telegram message."
    )
    return report
