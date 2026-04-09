"""Tools for task assignment and management."""

import asyncio
from typing import Dict, List, Optional
from app.store import WORKERS, TASKS, generate_id, now_iso
from google.genai import types


def assign_task(worker_id: str, description: str) -> Dict:
    """
    Assign a new task to a worker.
    Args:
        worker_id (str): The ID of the worker (e.g., 'driver-1', 'cook')
        description (str): A clear description of the task
    Returns:
        dict: The created task object.
    """
    if worker_id not in WORKERS:
        return {"error": f"Worker '{worker_id}' not found."}

    task = {
        "id": generate_id(),
        "worker_id": worker_id,
        "worker_name": WORKERS[worker_id]["name"],
        "description": description,
        "status": "assigned",
        "assigned_at": now_iso(),
        "completed_at": None,
    }
    TASKS.append(task)
    
    # Inject a notification into the worker's chat session asynchronously
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If we're already in an async context, schedule the notification
            loop.create_task(_notify_worker(worker_id, task))
    except RuntimeError:
        pass
        
    return task


async def _notify_worker(worker_id: str, task: dict):
    """Internal helper to inject a system message into a worker's session."""
    from app.main import runner, get_or_create_session
    try:
        session_id = await get_or_create_session(worker_id)
        session = await runner.session_service.get_session(session_id)
        
        # We simulate a system message being added to the history
        notification = types.Content(
            role="model",
            parts=[types.Part(text=f"📋 **New Task Assigned:** {task['description']}")]
        )
        
        if hasattr(session, 'state') and hasattr(session.state, 'setdefault'):
            messages = session.state.setdefault("messages", [])
            messages.append(notification)
            await runner.session_service.save_session(session)
    except Exception:
        pass  # Expected to fail in Telegram-only mode


def list_tasks(worker_id: str = None, status_filter: str = None) -> dict:
    """List tasks, optionally filtered by worker and/or status.

    Args:
        worker_id: Optional worker ID to filter by.
        status_filter: Optional status filter (assigned, in_progress, completed, rejected).

    Returns:
        List of matching tasks.
    """
    filtered = TASKS
    if worker_id:
        filtered = [t for t in filtered if t["worker_id"] == worker_id]
    if status_filter:
        filtered = [t for t in filtered if t["status"] == status_filter]
    return {"tasks": filtered, "count": len(filtered)}


def update_task_status(task_id: str, new_status: str, worker_response: str = None) -> dict:
    """Update the status of a task (worker responds).

    Args:
        task_id: The task ID to update.
        new_status: New status — one of: in_progress, completed, rejected.
        worker_response: Optional response message from the worker.

    Returns:
        Updated task details.
    """
    for task in TASKS:
        if task["id"] == task_id:
            task["status"] = new_status
            if worker_response:
                task["worker_response"] = worker_response
            if new_status == "completed":
                task["completed_at"] = now_iso()
            return {"message": f"Task {task_id} updated to '{new_status}'", "task": task}
    return {"error": f"Task '{task_id}' not found"}


def get_pending_tasks() -> dict:
    """Get all tasks that are assigned or in progress.

    Returns:
        List of pending tasks.
    """
    pending = [t for t in TASKS if t["status"] in ("assigned", "in_progress")]
    return {"pending_tasks": pending, "count": len(pending)}
