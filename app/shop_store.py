"""
Shop Mode — Data store for client task management.

Staff registry, task templates, and runtime state.
Tasks are defined inline (no CSV needed).
"""

import uuid
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional


# ── IST Timezone ────────────────────────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    """Current datetime in IST."""
    return datetime.now(IST)


# ── Test Mode ───────────────────────────────────────────────────────
SHOP_TEST_MODE: bool = False
SHOP_TEST_TIME_OVERRIDES: dict[int, str] = {}  # task_number → "HH:MM" override


# ── Staff Registry ──────────────────────────────────────────────────
# Owner is NOT in this registry — they are identified by SHOP_OWNER_CHAT_ID

SHOP_STAFF: dict[str, dict] = {
    "secretary": {
        "id": "secretary",
        "name": "Secretary",
        "role": "Secretary",
        "shop": 1,
        "performance_score": 80.0,
    },
    "driver": {
        "id": "driver",
        "name": "Driver",
        "role": "Driver",
        "shop": 1,
        "performance_score": 80.0,
    },
    "cook": {
        "id": "cook",
        "name": "Cook",
        "role": "Cook",
        "shop": 1,
        "performance_score": 80.0,
    },
}

# ── Staff name → ID mapping (case-insensitive lookup) ────────────────

_STAFF_NAME_MAP: dict[str, str] = {
    "secretary": "secretary",
    "driver": "driver",
    "cook": "cook",
}


def resolve_staff_id(name: str) -> Optional[str]:
    """Resolve a staff name to a staff_id."""
    return _STAFF_NAME_MAP.get(name.strip().lower())


# ── Task Template ───────────────────────────────────────────────────

@dataclass
class ShopTaskTemplate:
    """A task template representing a scheduled check/question."""
    task_number: int              # Unique task number
    description: str              # The question/check to ask
    staff_id: str                 # "secretary", "driver", "cook"
    verifier_id: str              # Owner verifies all
    admin_id: str                 # Owner
    trigger_time: Optional[str]   # "08:00" or None (24h format)
    trigger_type: str             # "fixed_time" | "sequential" | "event" | "manual"
    depends_on: Optional[int]     # Task number this depends on
    repeat: str                   # "daily"
    repeat_day: Optional[int]     # None for daily
    is_customer_task: bool        # False for all
    is_excluded: bool             # False for all


# All task templates
SHOP_TASK_TEMPLATES: list[ShopTaskTemplate] = []


# ── Runtime State (daily instances) ──────────────────────────────────

SHOP_DAILY_TASKS: list[dict] = []          # Today's instantiated tasks
SHOP_COMPLETED_TASK_NUMBERS: set[int] = set()  # Template numbers completed today
SHOP_DISPATCHED_TASK_NUMBERS: set[int] = set()  # Template numbers already sent today


def generate_shop_id() -> str:
    """Generate a short unique ID for shop tasks."""
    return f"shop-{str(uuid.uuid4())[:8]}"


def now_iso() -> str:
    """Current timestamp in IST, ISO format."""
    return now_ist().isoformat()


# ── Inline Task Definitions ─────────────────────────────────────────

_TASK_DEFINITIONS = [
    # ── Secretary Tasks ──────────────────────────────────────────
    {
        "task_number": 1,
        "description": "Are today's contents ready?",
        "staff_id": "secretary",
        "trigger_time": "10:00",
    },
    {
        "task_number": 2,
        "description": "Was the social media post uploaded successfully?",
        "staff_id": "secretary",
        "trigger_time": "19:00",
    },
    {
        "task_number": 3,
        "description": "Have the daily schedules been prepared?",
        "staff_id": "secretary",
        "trigger_time": "09:30",
    },
    {
        "task_number": 4,
        "description": "Was the 10:30 AM medicine intake done?",
        "staff_id": "secretary",
        "trigger_time": "10:30",
    },
    {
        "task_number": 5,
        "description": "Was the 10:00 PM medicine intake done?",
        "staff_id": "secretary",
        "trigger_time": "22:00",
    },

    # ── Driver Tasks ─────────────────────────────────────────────
    {
        "task_number": 6,
        "description": "Did you punch in/clock in at 9:00 AM?",
        "staff_id": "driver",
        "trigger_time": "09:00",
    },
    {
        "task_number": 7,
        "description": "Was the full vehicle wash completed today?",
        "staff_id": "driver",
        "trigger_time": "09:30",
    },
    {
        "task_number": 8,
        "description": "Has the interior of the car been cleaned and detailed?",
        "staff_id": "driver",
        "trigger_time": "10:00",
    },
    {
        "task_number": 9,
        "description": "Were all scheduled purchases for today finalized?",
        "staff_id": "driver",
        "trigger_time": "17:00",
    },
    {
        "task_number": 10,
        "description": "Have the car accessories and equipment been checked?",
        "staff_id": "driver",
        "trigger_time": "17:30",
    },
    {
        "task_number": 11,
        "description": "Did tomorrow's breakfast ingredients are there?",
        "staff_id": "driver",
        "trigger_time": "21:00",
    },

    # ── Cook Tasks ───────────────────────────────────────────────
    {
        "task_number": 12,
        "description": "Were the Vegetable Salad and Cucumber Juice prepared?",
        "staff_id": "cook",
        "trigger_time": "08:00",
    },
    {
        "task_number": 13,
        "description": "Were the Porridge and Curd (Yogurt) prepared?",
        "staff_id": "cook",
        "trigger_time": "09:00",
    },
    {
        "task_number": 14,
        "description": "Was the Salted Lemon Water prepared?",
        "staff_id": "cook",
        "trigger_time": "11:00",
    },
    {
        "task_number": 15,
        "description": "Was the Fruit Salad prepared?",
        "staff_id": "cook",
        "trigger_time": "12:00",
    },
    {
        "task_number": 16,
        "description": "Was the Protein Powder Shake prepared?",
        "staff_id": "cook",
        "trigger_time": "13:00",
    },
    {
        "task_number": 17,
        "description": "Were the Bread, Cheese, Poached Egg, and Water prepared?",
        "staff_id": "cook",
        "trigger_time": "14:00",
    },
    {
        "task_number": 18,
        "description": "Was the Gooseberry Juice prepared?",
        "staff_id": "cook",
        "trigger_time": "16:00",
    },
    {
        "task_number": 19,
        "description": "Was the Avocado Shake prepared?",
        "staff_id": "cook",
        "trigger_time": "17:00",
    },
    {
        "task_number": 20,
        "description": "Was the Vegetable Salad with Protein (per rotation) prepared?",
        "staff_id": "cook",
        "trigger_time": "19:00",
    },
]


# ── Task Loader (inline, no CSV) ────────────────────────────────────

def load_shop_tasks(csv_path: Optional[str] = None) -> list[ShopTaskTemplate]:
    """
    Build task templates from inline definitions.
    The csv_path parameter is kept for API compatibility but is ignored.

    Returns the list of loaded templates.
    """
    templates: list[ShopTaskTemplate] = []

    for task_def in _TASK_DEFINITIONS:
        template = ShopTaskTemplate(
            task_number=task_def["task_number"],
            description=task_def["description"],
            staff_id=task_def["staff_id"],
            verifier_id="owner",      # Owner verifies all tasks
            admin_id="owner",
            trigger_time=task_def.get("trigger_time"),
            trigger_type="fixed_time" if task_def.get("trigger_time") else "manual",
            depends_on=task_def.get("depends_on"),
            repeat="daily",
            repeat_day=None,
            is_customer_task=False,
            is_excluded=False,
        )
        templates.append(template)

    SHOP_TASK_TEMPLATES.clear()
    SHOP_TASK_TEMPLATES.extend(templates)
    return templates


def get_automatable_templates() -> list[ShopTaskTemplate]:
    """Get templates that can be automated (not excluded, not customer-facing)."""
    return [
        t for t in SHOP_TASK_TEMPLATES
        if not t.is_excluded and not t.is_customer_task
    ]


def get_fixed_time_templates() -> list[ShopTaskTemplate]:
    """Get templates with fixed trigger times."""
    return [
        t for t in get_automatable_templates()
        if t.trigger_type == "fixed_time" and t.trigger_time
    ]


def get_sequential_templates() -> list[ShopTaskTemplate]:
    """Get templates that depend on other tasks."""
    return [
        t for t in get_automatable_templates()
        if t.trigger_type == "sequential" and t.depends_on is not None
    ]


def get_daily_standing_templates(staff_id: Optional[str] = None) -> list[ShopTaskTemplate]:
    """Get daily tasks with no fixed time and no dependency (event/manual type, daily repeat)."""
    templates = [
        t for t in get_automatable_templates()
        if t.trigger_type in ("event", "manual") and t.repeat == "daily"
    ]
    if staff_id:
        templates = [t for t in templates if t.staff_id == staff_id]
    return templates


def get_templates_for_staff(staff_id: str) -> list[ShopTaskTemplate]:
    """Get all automatable templates assigned to a specific staff member."""
    return [
        t for t in get_automatable_templates()
        if t.staff_id == staff_id
    ]


def get_dependents(task_number: int) -> list[ShopTaskTemplate]:
    """Get templates that depend on a given task number."""
    return [
        t for t in get_automatable_templates()
        if t.depends_on == task_number
    ]


# ── Daily Task Instance Helpers ──────────────────────────────────────

def create_daily_task(template: ShopTaskTemplate) -> dict:
    """Create a live task instance from a template for today."""
    task = {
        "id": generate_shop_id(),
        "task_number": template.task_number,
        "description": template.description,
        "staff_id": template.staff_id,
        "verifier_id": template.verifier_id,
        "admin_id": template.admin_id,
        "status": "assigned",  # assigned → in_progress → completed / rejected
        "worker_response": None,
        "verifier_response": None,
        "assigned_at": now_iso(),
        "completed_at": None,
        "trigger_type": template.trigger_type,
        "depends_on": template.depends_on,
    }
    SHOP_DAILY_TASKS.append(task)
    return task


def get_task_by_id(task_id: str) -> Optional[dict]:
    """Find a daily task by its ID."""
    return next((t for t in SHOP_DAILY_TASKS if t["id"] == task_id), None)


def get_tasks_for_staff(staff_id: str, status: Optional[str] = None) -> list[dict]:
    """Get today's tasks for a staff member, optionally filtered by status."""
    tasks = [t for t in SHOP_DAILY_TASKS if t["staff_id"] == staff_id]
    if status:
        tasks = [t for t in tasks if t["status"] == status]
    return tasks


def reset_daily_state():
    """Clear daily state — called at start of each day."""
    SHOP_DAILY_TASKS.clear()
    SHOP_COMPLETED_TASK_NUMBERS.clear()
    SHOP_DISPATCHED_TASK_NUMBERS.clear()


# ── Test Mode Activation ─────────────────────────────────────────────

def activate_test_mode():
    """
    Activate test mode: override all fixed-time task triggers to
    fire at now+5min, now+10min, now+15min, etc.

    Sequential tasks keep their chain logic (fire on dependency completion)
    but are also given a fallback time in case the chain breaks.
    """
    global SHOP_TEST_MODE
    SHOP_TEST_MODE = True
    SHOP_TEST_TIME_OVERRIDES.clear()
    SHOP_DISPATCHED_TASK_NUMBERS.clear()

    now = now_ist()
    automatable = get_automatable_templates()

    # Sort: fixed_time first (by their original time), then sequential, then others
    def sort_key(t):
        if t.trigger_type == "fixed_time" and t.trigger_time:
            return (0, t.trigger_time)
        if t.trigger_type == "sequential":
            return (1, str(t.depends_on or 0).zfill(5))
        return (2, "")

    sorted_templates = sorted(automatable, key=sort_key)

    offset = 5  # First task at +5 min
    for template in sorted_templates:
        if template.trigger_type in ("fixed_time", "event", "manual"):
            # Override with test timing
            test_time = now + timedelta(minutes=offset)
            time_str = test_time.strftime("%H:%M")
            SHOP_TEST_TIME_OVERRIDES[template.task_number] = time_str

            # Also update the template's trigger for the scheduler
            template.trigger_time = time_str
            template.trigger_type = "fixed_time"

            offset += 5

    # Sequential tasks keep their chain behavior — no time override needed
    # They fire when their dependency completes

    return SHOP_TEST_TIME_OVERRIDES


def get_test_schedule_preview() -> list[dict]:
    """Get a preview of the test mode schedule."""
    if not SHOP_TEST_MODE:
        return []

    preview = []
    for template in get_automatable_templates():
        override = SHOP_TEST_TIME_OVERRIDES.get(template.task_number)
        if override:
            preview.append({
                "task_number": template.task_number,
                "description": template.description,
                "staff": SHOP_STAFF.get(template.staff_id, {}).get("name", template.staff_id),
                "fire_at": override,
                "type": "timed (test)",
            })
        elif template.trigger_type == "sequential":
            preview.append({
                "task_number": template.task_number,
                "description": template.description,
                "staff": SHOP_STAFF.get(template.staff_id, {}).get("name", template.staff_id),
                "fire_at": f"after T{template.depends_on}",
                "type": "sequential",
            })

    return preview
