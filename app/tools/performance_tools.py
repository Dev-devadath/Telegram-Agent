"""Tools for performance analytics and metrics."""

from app.store import WORKERS, TASKS, VERIFICATIONS


def get_worker_performance(worker_id: str) -> dict:
    """Get detailed performance metrics for a specific worker.

    Args:
        worker_id: The worker's ID.

    Returns:
        Performance metrics including score, completion rate, task counts.
    """
    if worker_id not in WORKERS:
        return {"error": f"Worker '{worker_id}' not found"}

    worker = WORKERS[worker_id]
    worker_tasks = [t for t in TASKS if t["worker_id"] == worker_id]

    total = len(worker_tasks)
    completed = len([t for t in worker_tasks if t["status"] == "completed"])
    rejected = len([t for t in worker_tasks if t["status"] == "rejected"])
    in_progress = len([t for t in worker_tasks if t["status"] == "in_progress"])
    assigned = len([t for t in worker_tasks if t["status"] == "assigned"])

    # Verification success rate
    worker_verifications = [v for v in VERIFICATIONS if v["worker_id"] == worker_id and v["status"] != "pending"]
    verified_count = len(worker_verifications)
    confirmed_count = len([v for v in worker_verifications if v["secretary_confirmed"]])
    verification_rate = (confirmed_count / verified_count * 100) if verified_count > 0 else 0

    # Update performance score
    if total > 0:
        score = ((completed / total) * 70) + ((verification_rate / 100) * 30)
        worker["performance_score"] = round(score, 1)

    return {
        "worker": {
            "id": worker_id,
            "name": worker["name"],
            "role": worker["role"],
        },
        "metrics": {
            "performance_score": worker["performance_score"],
            "total_tasks": total,
            "completed": completed,
            "rejected": rejected,
            "in_progress": in_progress,
            "assigned": assigned,
            "completion_rate": round((completed / total * 100), 1) if total > 0 else 0,
            "verification_success_rate": round(verification_rate, 1),
        },
    }


def get_all_workers_performance() -> dict:
    """Get performance overview for all workers.

    Returns:
        Performance summary for every worker.
    """
    results = []
    for worker_id in WORKERS:
        perf = get_worker_performance(worker_id)
        if "error" not in perf:
            results.append(perf)
    return {"workers_performance": results, "count": len(results)}


def get_productivity_trends(period: str = "weekly") -> dict:
    """Get productivity trends for the household.

    Args:
        period: Time period — 'daily', 'weekly', or 'monthly'.

    Returns:
        Productivity trend data.
    """
    total_tasks = len(TASKS)
    completed_tasks = len([t for t in TASKS if t["status"] == "completed"])
    rejected_tasks = len([t for t in TASKS if t["status"] == "rejected"])

    # Find top performers
    worker_completions = {}
    for task in TASKS:
        if task["status"] == "completed":
            wid = task["worker_id"]
            worker_completions[wid] = worker_completions.get(wid, 0) + 1

    top_workers = sorted(worker_completions.items(), key=lambda x: x[1], reverse=True)
    top_workers = [
        {"worker_id": wid, "worker_name": WORKERS[wid]["name"], "completed_tasks": count}
        for wid, count in top_workers[:5]
        if wid in WORKERS
    ]

    return {
        "period": period,
        "summary": {
            "total_tasks": total_tasks,
            "completed": completed_tasks,
            "rejected": rejected_tasks,
            "completion_rate": round((completed_tasks / total_tasks * 100), 1) if total_tasks > 0 else 0,
        },
        "top_performers": top_workers,
    }


def get_task_distribution() -> dict:
    """Get task distribution across roles.

    Returns:
        Tasks completed per role and average completion times.
    """
    role_stats = {}
    for task in TASKS:
        worker_id = task["worker_id"]
        if worker_id in WORKERS:
            role = WORKERS[worker_id]["role"]
            if role not in role_stats:
                role_stats[role] = {"total": 0, "completed": 0, "rejected": 0}
            role_stats[role]["total"] += 1
            if task["status"] == "completed":
                role_stats[role]["completed"] += 1
            elif task["status"] == "rejected":
                role_stats[role]["rejected"] += 1

    return {"distribution": role_stats}
