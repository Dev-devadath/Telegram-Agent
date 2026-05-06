import json
import os
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from config import ADMIN_TELEGRAM_ID, DATA_FILE

_LOCK = threading.Lock()
PLACEHOLDER_ADMIN_TELEGRAM_ID = 123456789


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _default_data() -> dict[str, Any]:
    data = {
        "settings": {
            "test_mode": False,
            "test_telegram_id": None,
        },
        "roles": ["Driver", "Cook", "Cleaner", "Security"],
        "users": [],
        "tasks": [],
        "task_runs": [],
    }
    if ADMIN_TELEGRAM_ID:
        data["users"].append(
            {
                "id": _new_id("u"),
                "telegram_id": ADMIN_TELEGRAM_ID,
                "name": "Admin",
                "role": "admin",
                "worker_role": None,
                "active": True,
                "created_at": _now_iso(),
            }
        )
    return data


def _sync_admin_user(data: dict[str, Any]) -> bool:
    changed = False
    users = data.get("users", [])

    if ADMIN_TELEGRAM_ID:
        # Replace known placeholder admin entry with configured admin ID.
        for user in users:
            if (
                user.get("role") == "admin"
                and user.get("telegram_id") == PLACEHOLDER_ADMIN_TELEGRAM_ID
                and ADMIN_TELEGRAM_ID != PLACEHOLDER_ADMIN_TELEGRAM_ID
            ):
                user["telegram_id"] = ADMIN_TELEGRAM_ID
                changed = True

        has_configured_admin = any(
            user.get("role") == "admin" and user.get("telegram_id") == ADMIN_TELEGRAM_ID
            for user in users
        )
        if not has_configured_admin:
            users.append(
                {
                    "id": _new_id("u"),
                    "telegram_id": ADMIN_TELEGRAM_ID,
                    "name": "Admin",
                    "role": "admin",
                    "worker_role": None,
                    "active": True,
                    "created_at": _now_iso(),
                }
            )
            changed = True

    data["users"] = users
    return changed


def ensure_data_file() -> None:
    if DATA_FILE.exists():
        with _LOCK:
            with DATA_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
        if _sync_admin_user(data):
            save_data(data)
        return
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = _default_data()
    _sync_admin_user(data)
    save_data(data)


def load_data() -> dict[str, Any]:
    ensure_data_file()
    with _LOCK:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)


def save_data(data: dict[str, Any]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = Path(f"{DATA_FILE}.tmp")
    with _LOCK:
        with temp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=True)
        os.replace(temp_path, DATA_FILE)


def get_settings() -> dict[str, Any]:
    return load_data()["settings"]


def set_test_mode(enabled: bool, telegram_id: int | None) -> dict[str, Any]:
    data = load_data()
    data["settings"]["test_mode"] = enabled
    data["settings"]["test_telegram_id"] = telegram_id
    save_data(data)
    return data["settings"]


def map_all_workers_to_telegram(telegram_id: int) -> int:
    data = load_data()
    updated = 0
    for idx, user in enumerate(data["users"]):
        if user.get("role") == "worker" and user.get("active", True):
            if data["users"][idx].get("telegram_id") != telegram_id:
                data["users"][idx]["telegram_id"] = telegram_id
                updated += 1
    if updated:
        save_data(data)
    return updated


def get_user_by_telegram(telegram_id: int) -> dict[str, Any] | None:
    data = load_data()
    for user in data["users"]:
        if user["telegram_id"] == telegram_id and user.get("active", True):
            return user
    return None


def list_users_by_telegram(telegram_id: int) -> list[dict[str, Any]]:
    data = load_data()
    return [
        user
        for user in data["users"]
        if user.get("telegram_id") == telegram_id and user.get("active", True)
    ]


def telegram_has_role(telegram_id: int, role: str) -> bool:
    users = list_users_by_telegram(telegram_id)
    return any(user.get("role") == role for user in users)


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    data = load_data()
    for user in data["users"]:
        if user["id"] == user_id and user.get("active", True):
            return user
    return None


def get_user_by_role(worker_role: str) -> dict[str, Any] | None:
    data = load_data()
    for user in data["users"]:
        if (
            user.get("role") == "worker"
            and user.get("worker_role") == worker_role
            and user.get("active", True)
        ):
            return user
    return None


def list_users_by_role(role: str) -> list[dict[str, Any]]:
    data = load_data()
    return [
        user
        for user in data["users"]
        if user.get("role") == role and user.get("active", True)
    ]


def list_roles() -> list[str]:
    return load_data()["roles"]


def add_role(role_name: str) -> None:
    role_name = role_name.strip()
    if not role_name:
        raise ValueError("Role cannot be empty.")
    data = load_data()
    if role_name in data["roles"]:
        raise ValueError("Role already exists.")
    data["roles"].append(role_name)
    save_data(data)


def remove_role(role_name: str) -> None:
    data = load_data()
    if role_name not in data["roles"]:
        raise ValueError("Role not found.")
    claimed = get_user_by_role(role_name)
    if claimed:
        raise ValueError("Role is already claimed by a worker.")
    data["roles"] = [role for role in data["roles"] if role != role_name]
    save_data(data)


def get_unclaimed_roles() -> list[str]:
    data = load_data()
    claimed_roles = {
        user.get("worker_role")
        for user in data["users"]
        if user.get("role") == "worker" and user.get("active", True)
    }
    return [role for role in data["roles"] if role not in claimed_roles]


def add_user(
    telegram_id: int,
    name: str,
    system_role: str,
    worker_role: str | None = None,
) -> dict[str, Any]:
    data = load_data()
    existing_same_role = next(
        (
            user
            for user in data["users"]
            if user["telegram_id"] == telegram_id
            and user.get("role") == system_role
            and user.get("active", True)
        ),
        None,
    )
    if existing_same_role:
        raise ValueError(f"Telegram ID is already registered as {system_role}.")

    settings = data.get("settings", {})
    is_test_mode = bool(settings.get("test_mode"))
    test_telegram_id = settings.get("test_telegram_id")
    if not is_test_mode:
        existing_any = next(
            (
                user
                for user in data["users"]
                if user["telegram_id"] == telegram_id and user.get("active", True)
            ),
            None,
        )
        if existing_any:
            raise ValueError("Telegram ID already registered.")
    else:
        # In test mode, only the configured test telegram ID may be reused
        # across different roles to simulate full workflow on one account.
        existing_any = next(
            (
                user
                for user in data["users"]
                if user["telegram_id"] == telegram_id and user.get("active", True)
            ),
            None,
        )
        if existing_any and telegram_id != test_telegram_id:
            raise ValueError("Telegram ID already registered.")

    if system_role == "worker":
        if not worker_role:
            raise ValueError("Worker role is required.")
        if worker_role not in data["roles"]:
            raise ValueError("Worker role does not exist.")
        if get_user_by_role(worker_role):
            raise ValueError("This role is already claimed.")

    user = {
        "id": _new_id("u"),
        "telegram_id": telegram_id,
        "name": name.strip() or system_role.title(),
        "role": system_role,
        "worker_role": worker_role,
        "active": True,
        "created_at": _now_iso(),
    }
    data["users"].append(user)
    save_data(data)
    return user


def add_task(
    title: str,
    description: str,
    worker_role: str,
    manager_id: str,
    time_hhmm: str,
    recurrence: str = "daily",
) -> dict[str, Any]:
    data = load_data()
    if worker_role not in data["roles"]:
        raise ValueError("Unknown worker role.")
    manager = get_user_by_id(manager_id)
    if not manager or manager.get("role") != "manager":
        raise ValueError("Invalid manager.")

    task = {
        "id": _new_id("t"),
        "title": title.strip(),
        "description": description.strip(),
        "worker_role": worker_role,
        "manager_id": manager_id,
        "time": time_hhmm,
        "recurrence": recurrence,
        "active": True,
        "created_at": _now_iso(),
    }
    data["tasks"].append(task)
    save_data(data)
    return task


def list_active_tasks() -> list[dict[str, Any]]:
    data = load_data()
    return [task for task in data["tasks"] if task.get("active", True)]


def get_task_by_id(task_id: str) -> dict[str, Any] | None:
    data = load_data()
    for task in data["tasks"]:
        if task["id"] == task_id:
            return task
    return None


def add_task_run(task: dict[str, Any], scheduled_for: str) -> dict[str, Any]:
    data = load_data()
    run = {
        "id": _new_id("r"),
        "task_id": task["id"],
        "worker_role": task["worker_role"],
        "manager_id": task["manager_id"],
        "scheduled_for": scheduled_for,
        "status": "sent_to_worker",
        "worker_response": None,
        "reason": None,
        "manager_status": "pending",
        "created_at": _now_iso(),
        "completed_at": None,
        "verified_at": None,
    }
    data["task_runs"].append(run)
    save_data(data)
    return run


def get_task_run(run_id: str) -> dict[str, Any] | None:
    data = load_data()
    for run in data["task_runs"]:
        if run["id"] == run_id:
            return run
    return None


def update_task_run(run_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    data = load_data()
    for idx, run in enumerate(data["task_runs"]):
        if run["id"] == run_id:
            data["task_runs"][idx] = {**run, **updates}
            save_data(data)
            return data["task_runs"][idx]
    raise ValueError("Task run not found.")


def get_runs_for_report(
    worker_role: str | None = None,
    period: str = "today",
) -> list[dict[str, Any]]:
    data = load_data()
    now = datetime.utcnow()
    from_time: datetime | None = None
    if period == "today":
        from_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        from_time = now - timedelta(days=7)
    elif period == "month":
        from_time = now - timedelta(days=30)

    results: list[dict[str, Any]] = []
    for run in data["task_runs"]:
        if worker_role and run.get("worker_role") != worker_role:
            continue
        created_at = datetime.fromisoformat(run["created_at"])
        if from_time and created_at < from_time:
            continue
        results.append(run)
    return results


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(runs),
        "verified": sum(1 for run in runs if run.get("status") == "manager_verified"),
        "not_completed": sum(1 for run in runs if run.get("status") == "worker_not_done"),
        "rejected": sum(1 for run in runs if run.get("status") == "manager_rejected"),
        "extended": sum(1 for run in runs if run.get("status") == "extended"),
    }


def reset_all() -> None:
    data = load_data()
    admins = [user for user in data["users"] if user.get("role") == "admin"]
    data["users"] = admins
    data["tasks"] = []
    data["task_runs"] = []
    data["settings"]["test_mode"] = False
    data["settings"]["test_telegram_id"] = None
    save_data(data)
