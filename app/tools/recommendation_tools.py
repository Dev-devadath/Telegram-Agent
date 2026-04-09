"""Tools for recommending next tasks to idle workers."""

import random
from app.store import WORKERS, TASKS, TASK_TEMPLATES


def suggest_next_tasks(worker_id: str) -> dict:
    """Suggest next tasks for a worker based on their role.

    Args:
        worker_id (str): The worker's ID.

    Returns:
        dict: List of suggested tasks.
    """
    if worker_id not in WORKERS:
        return {"error": f"Worker '{worker_id}' not found"}

    worker = WORKERS[worker_id]
    role = worker["role"]

    # Get tasks already assigned/in-progress for this worker
    active_descriptions = {
        t["description"].lower()
        for t in TASKS
        if t["worker_id"] == worker_id and t["status"] in ("assigned", "in_progress")
    }

    # Get role-based templates, filter out active ones
    templates = TASK_TEMPLATES.get(role, [])
    available = [t for t in templates if t.lower() not in active_descriptions]

    if not available:
        available = templates  # All done? suggest from full list again

    # Pick up to 3 suggestions
    suggestions = random.sample(available, min(3, len(available)))

    return {
        "worker": {"id": worker_id, "name": worker["name"], "role": role},
        "suggested_tasks": suggestions,
        "active_task_count": len(active_descriptions),
    }


def get_idle_workers() -> dict:
    """Find workers who have no active tasks (assigned or in-progress).

    Returns:
        List of idle workers.
    """
    busy_worker_ids = {
        t["worker_id"]
        for t in TASKS
        if t["status"] in ("assigned", "in_progress")
    }

    idle = [
        {"id": wid, "name": w["name"], "role": w["role"]}
        for wid, w in WORKERS.items()
        if wid not in busy_worker_ids
    ]

    return {"idle_workers": idle, "count": len(idle)}
