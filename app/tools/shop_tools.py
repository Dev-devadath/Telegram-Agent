"""Shop Mode — Tools for the ADK agent (Owner queries)."""

from typing import Optional

from app.shop_store import (
    SHOP_STAFF,
    SHOP_DAILY_TASKS,
    SHOP_TASK_TEMPLATES,
    SHOP_COMPLETED_TASK_NUMBERS,
    SHOP_DISPATCHED_TASK_NUMBERS,
    get_task_by_id,
    get_tasks_for_staff,
    get_automatable_templates,
    get_templates_for_staff,
)


def list_shop_tasks(staff_id: str = None, status: str = None) -> dict:
    """
    List today's shop tasks, optionally filtered by staff and/or status.

    Args:
        staff_id: Optional staff ID to filter by (secretary, driver, cook).
        status: Optional status filter (assigned, in_progress, completed, rejected).

    Returns:
        dict with tasks list and count.
    """
    tasks = SHOP_DAILY_TASKS
    if staff_id:
        tasks = [t for t in tasks if t["staff_id"] == staff_id]
    if status:
        tasks = [t for t in tasks if t["status"] == status]

    return {
        "tasks": [
            {
                "id": t["id"],
                "task_number": t["task_number"],
                "description": t["description"],
                "staff": SHOP_STAFF.get(t["staff_id"], {}).get("name", t["staff_id"]),
                "status": t["status"],
                "assigned_at": t["assigned_at"],
                "completed_at": t["completed_at"],
            }
            for t in tasks
        ],
        "count": len(tasks),
    }


def get_shop_daily_summary() -> dict:
    """
    Get a summary of today's shop operations.

    Returns:
        dict with overall stats: total dispatched, completed, pending, rejected per staff.
    """
    summary = {
        "total_templates": len(get_automatable_templates()),
        "dispatched_today": len(SHOP_DISPATCHED_TASK_NUMBERS),
        "completed_today": len(SHOP_COMPLETED_TASK_NUMBERS),
        "staff_breakdown": {},
    }

    for staff_id, staff in SHOP_STAFF.items():

        tasks = get_tasks_for_staff(staff_id)
        if not tasks:
            summary["staff_breakdown"][staff["name"]] = {
                "total": 0,
                "completed": 0,
                "pending": 0,
                "rejected": 0,
            }
            continue

        summary["staff_breakdown"][staff["name"]] = {
            "total": len(tasks),
            "completed": sum(1 for t in tasks if t["status"] == "completed"),
            "pending": sum(1 for t in tasks if t["status"] in ("assigned", "in_progress")),
            "rejected": sum(1 for t in tasks if t["status"] == "rejected"),
        }

    return summary


def get_shop_staff_performance(staff_id: str) -> dict:
    """
    Get performance data for a specific shop staff member.

    Args:
        staff_id: The staff ID (secretary, driver, cook).

    Returns:
        dict with performance metrics.
    """
    staff = SHOP_STAFF.get(staff_id)
    if not staff:
        return {"error": f"Staff '{staff_id}' not found"}

    tasks = get_tasks_for_staff(staff_id)
    total = len(tasks)

    if total == 0:
        return {
            "name": staff["name"],
            "role": staff["role"],
            "tasks_today": 0,
            "completion_rate": 0.0,
            "message": "No tasks dispatched yet today",
        }

    completed = sum(1 for t in tasks if t["status"] == "completed")
    rejected = sum(1 for t in tasks if t["status"] == "rejected")
    pending = sum(1 for t in tasks if t["status"] in ("assigned", "in_progress"))

    return {
        "name": staff["name"],
        "role": staff["role"],
        "shop": staff["shop"],
        "tasks_today": total,
        "completed": completed,
        "rejected": rejected,
        "pending": pending,
        "completion_rate": round((completed / total) * 100, 1) if total > 0 else 0.0,
        "performance_score": staff.get("performance_score", 0),
    }


def get_all_shop_staff_performance() -> dict:
    """
    Get performance data for all shop staff members.

    Returns:
        dict with performance data per staff.
    """
    results = {}
    for staff_id in SHOP_STAFF:
        results[staff_id] = get_shop_staff_performance(staff_id)

    return {"staff_performance": results}


def reassign_shop_task(task_id: str, new_staff_id: str) -> dict:
    """
    Reassign a shop task to a different staff member.

    Args:
        task_id: The task ID to reassign.
        new_staff_id: The new staff member's ID.

    Returns:
        dict with result message.
    """
    task = get_task_by_id(task_id)
    if not task:
        return {"error": f"Task '{task_id}' not found"}

    if new_staff_id not in SHOP_STAFF:
        return {"error": f"Staff '{new_staff_id}' not found"}

    old_staff = SHOP_STAFF.get(task["staff_id"], {}).get("name", task["staff_id"])
    new_staff = SHOP_STAFF[new_staff_id]["name"]

    task["staff_id"] = new_staff_id
    task["status"] = "assigned"

    return {
        "message": f"Task reassigned from {old_staff} to {new_staff}",
        "task": {
            "id": task["id"],
            "description": task["description"],
            "old_staff": old_staff,
            "new_staff": new_staff,
            "status": task["status"],
        },
    }


def get_shop_staff_list() -> dict:
    """
    List all shop staff with their roles and registration status.

    Returns:
        dict with staff list.
    """
    from app.telegram.registry import get_registered_shop_staff
    registered = get_registered_shop_staff()

    staff_list = []
    for staff_id, staff in SHOP_STAFF.items():
        staff_list.append({
            "id": staff_id,
            "name": staff["name"],
            "role": staff["role"],
            "shop": staff["shop"],
            "registered": staff_id in registered,
        })

    return {"staff": staff_list}
