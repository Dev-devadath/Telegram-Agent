"""Tools for secretary task verification."""

from app.store import TASKS, VERIFICATIONS, generate_id, now_iso


def request_verification(task_id: str) -> dict:
    """Request the secretary to verify a completed task.

    Args:
        task_id: The task ID to verify.

    Returns:
        Verification request details.
    """
    task = next((t for t in TASKS if t["id"] == task_id), None)
    if not task:
        return {"error": f"Task '{task_id}' not found"}

    # Check if already has a pending verification
    existing = next((v for v in VERIFICATIONS if v["task_id"] == task_id and v["status"] == "pending"), None)
    if existing:
        return {"message": "Verification already pending for this task", "verification": existing}

    verification = {
        "id": generate_id(),
        "task_id": task_id,
        "worker_id": task["worker_id"],
        "worker_name": task["worker_name"],
        "task_description": task["description"],
        "status": "pending",
        "secretary_confirmed": None,
        "secretary_notes": None,
        "requested_at": now_iso(),
        "verified_at": None,
    }
    VERIFICATIONS.append(verification)
    return {
        "message": f"Verification requested for task: {task['description']}",
        "verification": verification,
    }


def process_verification(verification_id: str, confirmed: bool, secretary_notes: str = None) -> dict:
    """Secretary confirms or rejects a task completion.

    Args:
        verification_id: The verification ID to process.
        confirmed: True if secretary confirms, False if rejected.
        secretary_notes: Optional notes from the secretary.

    Returns:
        Updated verification and task details.
    """
    verification = next((v for v in VERIFICATIONS if v["id"] == verification_id), None)
    if not verification:
        return {"error": f"Verification '{verification_id}' not found"}

    verification["secretary_confirmed"] = confirmed
    verification["secretary_notes"] = secretary_notes
    verification["status"] = "confirmed" if confirmed else "rejected"
    verification["verified_at"] = now_iso()

    # Update the corresponding task
    task = next((t for t in TASKS if t["id"] == verification["task_id"]), None)
    if task:
        task["status"] = "completed" if confirmed else "rejected"
        if confirmed:
            task["completed_at"] = now_iso()

    status_word = "confirmed" if confirmed else "rejected"
    return {
        "message": f"Task {status_word} by secretary",
        "verification": verification,
        "task": task,
    }


def get_pending_verifications() -> dict:
    """Get all verifications waiting for secretary response.

    Returns:
        List of pending verifications.
    """
    pending = [v for v in VERIFICATIONS if v["status"] == "pending"]
    return {"pending_verifications": pending, "count": len(pending)}
