"""
Shop Mode — Data store for Quality GrowHack task management.

Staff registry, CSV parser, task templates, and runtime state.
Runs alongside the existing household store (store.py).
"""

import csv
import re
import uuid
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


# ── IST Timezone ────────────────────────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    """Current datetime in IST."""
    return datetime.now(IST)


# ── Test Mode ───────────────────────────────────────────────────────
SHOP_TEST_MODE: bool = False
SHOP_TEST_TIME_OVERRIDES: dict[int, str] = {}  # task_number → "HH:MM" override


# ── Shop Staff Registry ─────────────────────────────────────────────
# Owner is NOT in this registry — they are identified by SHOP_OWNER_CHAT_ID

SHOP_STAFF: dict[str, dict] = {
    "sanoof": {
        "id": "sanoof",
        "name": "Sanoof",
        "role": "SE",
        "shop": 1,
        "performance_score": 80.0,
    },
    "favan": {
        "id": "favan",
        "name": "Favan",
        "role": "Accounts",
        "shop": 2,
        "performance_score": 80.0,
    },
    "junaid": {
        "id": "junaid",
        "name": "Junaid",
        "role": "SSE",
        "shop": 1,
        "performance_score": 80.0,
    },
    "haris": {
        "id": "haris",
        "name": "Haris",
        "role": "Manager",
        "shop": "both",
        "performance_score": 80.0,
    },
    "yousuf": {
        "id": "yousuf",
        "name": "Yousuf",
        "role": "Director",
        "shop": "verifier_only",
        "performance_score": 80.0,
    },
}

# ── Staff name → ID mapping (case-insensitive lookup) ────────────────

_STAFF_NAME_MAP: dict[str, str] = {
    "sanoof": "sanoof",
    "sanoof - se": "sanoof",
    "sanoof-se": "sanoof",
    "favan": "favan",
    "favan-acounts": "favan",
    "favan-accounts": "favan",
    "junaid": "junaid",
    "junaid -sse": "junaid",
    "junaid-sse": "junaid",
    "haris": "haris",
    "yousuf": "yousuf",
}


def resolve_staff_id(name: str) -> Optional[str]:
    """Resolve a CSV staff name to a staff_id."""
    return _STAFF_NAME_MAP.get(name.strip().lower())


# ── Task Template (parsed from CSV) ─────────────────────────────────

@dataclass
class ShopTaskTemplate:
    """A task template parsed from one row of the CSV."""
    task_number: int              # 1-65 from CSV
    description: str              # "Open Shop 1 at 8:00 AM"
    staff_id: str                 # "sanoof"
    verifier_id: str              # "junaid"
    admin_id: str                 # "haris"
    trigger_time: Optional[str]   # "08:00" or None (24h format)
    trigger_type: str             # "fixed_time" | "sequential" | "event" | "manual"
    depends_on: Optional[int]     # Task number this depends on (AFTER T10 → 10)
    repeat: str                   # "daily" | "monthly" | "weekly" | "quarterly"
    repeat_day: Optional[int]     # 30 for "30th of every month"
    is_customer_task: bool        # True = skipped from automation
    is_excluded: bool             # True for YOUSUF's tasks (rows 56-65)


# All task templates loaded from CSV
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


# ── Time Parsing ────────────────────────────────────────────────────

def _normalize_time(raw: str) -> Optional[str]:
    """
    Convert messy CSV time strings to 24h "HH:MM" format.

    Examples:
        "8.00 AM"     → "08:00"
        "8:00 AM"     → "08:00"
        "7.45 PM"     → "19:45"
        "BEFORE 12 PM" → "11:30"  (approximate)
        "AFTERN NOON"  → "13:00"
        "AFTER NOON"   → "13:00"
        "AFTERNOON"    → "13:00"
        None / ""      → None
    """
    if not raw:
        return None

    raw = raw.strip().upper()

    # Skip non-time values
    skip_patterns = [
        "ON ARRIVAL", "AS PER REQ", "DAILY", "DIALY",
        "PURCHASE ARRIVAL", "WHENEVE", "3 TIME", "3TIME",
    ]
    for pattern in skip_patterns:
        if pattern in raw:
            return None

    # Handle AFTER T* (sequential dependency, not a time)
    if re.match(r"AFTER\s*T\d+", raw):
        return None

    # Handle "AFTERN NOON", "AFTER NOON", "AFTERNOON"
    if "NOON" in raw and "BEFORE" not in raw:
        return "13:00"

    # Handle "BEFORE 12 PM" → approximate as 11:30
    before_match = re.match(r"BEFORE\s+(\d{1,2})\s*(AM|PM)", raw)
    if before_match:
        hour = int(before_match.group(1))
        ampm = before_match.group(2)
        if ampm == "PM" and hour != 12:
            hour += 12
        elif ampm == "AM" and hour == 12:
            hour = 0
        # 30 min before as approximation
        if hour > 0:
            return f"{hour - 1:02d}:30"
        return "23:30"

    # Handle "AFTER 8 PM" → "20:00"
    after_time_match = re.match(r"AFTER\s+(\d{1,2})\s*(AM|PM)", raw)
    if after_time_match:
        hour = int(after_time_match.group(1))
        ampm = after_time_match.group(2)
        if ampm == "PM" and hour != 12:
            hour += 12
        elif ampm == "AM" and hour == 12:
            hour = 0
        return f"{hour:02d}:00"

    # Handle standard time: "8.00 AM", "8:00 AM", "8.10 AM"
    time_match = re.match(r"(\d{1,2})[.:](\d{2})\s*(AM|PM)", raw)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2))
        ampm = time_match.group(3)
        if ampm == "PM" and hour != 12:
            hour += 12
        elif ampm == "AM" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"

    return None


def _parse_trigger(time_str: str) -> tuple[str, Optional[int]]:
    """
    Determine trigger type and dependency from the TIME column.

    Returns:
        (trigger_type, depends_on_task_number)
    """
    if not time_str:
        return ("manual", None)

    raw = time_str.strip().upper()

    # Sequential: "AFTER T10", "AFTEER T30", "AFTERT11"
    seq_match = re.match(r"AFTE+R\s*T(\d+)", raw)
    if seq_match:
        return ("sequential", int(seq_match.group(1)))

    # "NEXT DAY T38" — treat as sequential for simplicity
    next_match = re.match(r"NEXT\s+DAY\s+T(\d+)", raw)
    if next_match:
        return ("sequential", int(next_match.group(1)))

    # Event-driven
    event_patterns = ["ON ARRIVAL", "AS PER REQ", "PURCHASE ARRIVAL", "WHENEVE"]
    for pat in event_patterns:
        if pat in raw:
            return ("event", None)

    # If we can parse a time, it's a fixed-time task
    normalized = _normalize_time(raw)
    if normalized:
        return ("fixed_time", None)

    # Fallback
    return ("manual", None)


def _parse_repeat(raw: str) -> tuple[str, Optional[int]]:
    """
    Parse the REPEAT column.

    Returns:
        (repeat_frequency, specific_day_or_none)
    """
    if not raw:
        return ("daily", None)

    raw = raw.strip().upper()

    if "MONTH" in raw:
        # "30th of Everymonth" or "1 DAY EVERY MONTH"
        day_match = re.search(r"(\d+)", raw)
        day = int(day_match.group(1)) if day_match else 1
        return ("monthly", day)

    if "WEEK" in raw:
        return ("weekly", None)

    if "QUARTER" in raw:
        return ("quarterly", None)

    return ("daily", None)


# Customer-facing task keywords (these are skipped from automation)
_CUSTOMER_KEYWORDS = [
    "handle customer interaction",
    "explain products to customer",
    "close sales effectively",
    "handle customer interactions",
    "manage sales and handle customers",
]


def _is_customer_task(description: str) -> bool:
    """Check if a task description is customer-facing."""
    desc_lower = description.lower()
    return any(kw in desc_lower for kw in _CUSTOMER_KEYWORDS)


# ── CSV Loader ──────────────────────────────────────────────────────

def load_shop_tasks(csv_path: Optional[str] = None) -> list[ShopTaskTemplate]:
    """
    Parse the Quality GrowHack CSV and populate SHOP_TASK_TEMPLATES.

    Skips:
    - Rows without a task number (unnumbered rows, lines 24-29)
    - YOUSUF's tasks (rows 56-65) — he's verifier-only

    Returns the list of loaded templates.
    """

    if csv_path is None:
        csv_path = str(Path(__file__).parent.parent / "Quality GrowHack - Sheet1.csv")

    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Shop task CSV not found: {csv_path}")

    templates: list[ShopTaskTemplate] = []

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        for row in reader:
            # Skip rows without a task number (unnumbered rows)
            task_num_raw = row.get("", "").strip()
            if not task_num_raw or not task_num_raw.isdigit():
                continue

            task_number = int(task_num_raw)
            description = row.get("TASK", "").strip()
            if not description:
                continue

            # Resolve staff IDs
            staff_id = resolve_staff_id(row.get("STAFF", ""))
            verifier_id = resolve_staff_id(row.get("VERIFIER", ""))
            admin_id = resolve_staff_id(row.get("ADMIN", ""))

            if not staff_id:
                continue  # Can't assign without a valid staff member

            # Check if this is YOUSUF's task (he's verifier-only)
            is_excluded = (staff_id == "yousuf")

            # Parse time and trigger
            time_raw = row.get("TIME", "").strip()
            trigger_type, depends_on = _parse_trigger(time_raw)
            trigger_time = _normalize_time(time_raw)

            # Parse repeat
            repeat_raw = row.get("REPEAT", "").strip()
            repeat, repeat_day = _parse_repeat(repeat_raw)

            # Check if customer-facing
            is_customer = _is_customer_task(description)

            template = ShopTaskTemplate(
                task_number=task_number,
                description=description,
                staff_id=staff_id,
                verifier_id=verifier_id or "haris",  # Default verifier
                admin_id=admin_id or "haris",
                trigger_time=trigger_time,
                trigger_type=trigger_type,
                depends_on=depends_on,
                repeat=repeat,
                repeat_day=repeat_day,
                is_customer_task=is_customer,
                is_excluded=is_excluded,
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
