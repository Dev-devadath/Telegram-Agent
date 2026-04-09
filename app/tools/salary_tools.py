"""Tools for salary recommendations based on performance."""

from app.store import WORKERS
from app.tools.performance_tools import get_worker_performance


def get_salary_recommendation(worker_id: str) -> dict:
    """Get salary adjustment recommendation based on performance score.

    Args:
        worker_id: The worker's ID.

    Returns:
        Salary recommendation with reasoning.

    Rules:
        Score > 90  → Recommend increase
        Score 70-90 → No change
        Score < 70  → Consider reduction / warning
    """
    if worker_id not in WORKERS:
        return {"error": f"Worker '{worker_id}' not found"}

    worker = WORKERS[worker_id]
    perf = get_worker_performance(worker_id)
    score = perf["metrics"]["performance_score"]
    current_salary = worker["salary"]

    if score > 90:
        recommendation = "increase"
        suggested_change = round(current_salary * 0.10)
        reasoning = f"Excellent performance (score: {score}). Recommend 10% increase."
        suggested_salary = current_salary + suggested_change
    elif score >= 70:
        recommendation = "no_change"
        suggested_change = 0
        reasoning = f"Satisfactory performance (score: {score}). No salary change needed."
        suggested_salary = current_salary
    else:
        recommendation = "warning"
        suggested_change = round(current_salary * -0.05)
        reasoning = f"Below expectations (score: {score}). Consider a warning or 5% reduction."
        suggested_salary = current_salary + suggested_change

    return {
        "worker": {
            "id": worker_id,
            "name": worker["name"],
            "role": worker["role"],
        },
        "current_salary": current_salary,
        "performance_score": score,
        "recommendation": recommendation,
        "reasoning": reasoning,
        "suggested_salary": suggested_salary,
        "suggested_change": suggested_change,
    }


def get_all_salary_recommendations() -> dict:
    """Get salary recommendations for all workers.

    Returns:
        List of salary recommendations for every worker.
    """
    recommendations = []
    for worker_id in WORKERS:
        rec = get_salary_recommendation(worker_id)
        if "error" not in rec:
            recommendations.append(rec)
    return {"recommendations": recommendations, "count": len(recommendations)}
