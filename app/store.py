"""
In-memory data store for the Household Staff Performance Manager.
All data lives in Python dicts — no database needed.
"""

import uuid
from datetime import datetime


# ── Seeded Workers ──────────────────────────────────────────────────
WORKERS: dict[str, dict] = {
    "driver-1": {
        "id": "driver-1",
        "name": "Driver 1",
        "role": "Driver",
        "salary": 15000,
        "performance_score": 85.0,
    },
    "driver-2": {
        "id": "driver-2",
        "name": "Driver 2",
        "role": "Driver",
        "salary": 14000,
        "performance_score": 78.0,
    },
    "cook": {
        "id": "cook",
        "name": "Cook",
        "role": "Cook",
        "salary": 12000,
        "performance_score": 92.0,
    },
    "massager": {
        "id": "massager",
        "name": "Massager",
        "role": "Massager",
        "salary": 10000,
        "performance_score": 70.0,
    },
    "pa": {
        "id": "pa",
        "name": "Personal Assistant",
        "role": "PA",
        "salary": 18000,
        "performance_score": 88.0,
    },
    "social-media": {
        "id": "social-media",
        "name": "Social Media Manager",
        "role": "Social Media",
        "salary": 16000,
        "performance_score": 75.0,
    },
}

# ── Tasks ───────────────────────────────────────────────────────────
TASKS: list[dict] = []

# ── Verifications ───────────────────────────────────────────────────
VERIFICATIONS: list[dict] = []

# ── Daily Task Status (Telegram broadcasts) ─────────────────────────
# {worker_id: [{task_id, description, worker_response, manager_confirmed}]}
DAILY_TASK_STATUS: dict[str, list[dict]] = {}


# ── Role-based task templates (for recommendation engine) ───────────
TASK_TEMPLATES: dict[str, list[str]] = {
    "Driver": [
        "Wash the car",
        "Pick up owner from airport",
        "Refuel the vehicle",
        "Check fuel level",
        "Clean car interior",
        "Prepare vehicle for next trip",
        "Drop children to school",
        "Service vehicle check",
    ],
    "Cook": [
        "Prepare breakfast",
        "Prepare lunch",
        "Prepare dinner",
        "Check kitchen inventory",
        "Clean the kitchen",
        "Prepare snacks",
    ],
    "Massager": [
        "Morning therapy session",
        "Evening relaxation massage",
        "Prepare oils and equipment",
        "Clean therapy room",
    ],
    "PA": [
        "Schedule meetings",
        "Book travel tickets",
        "Manage daily agenda",
        "Organize documents",
        "Handle correspondence",
    ],
    "Social Media": [
        "Post daily update",
        "Respond to comments",
        "Plan weekly content",
        "Analyze engagement metrics",
        "Create story content",
    ],
}


def generate_id() -> str:
    uid: str = str(uuid.uuid4())
    return uid[:8]


def now_iso() -> str:
    return datetime.now().isoformat()
