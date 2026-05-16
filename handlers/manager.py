from datetime import datetime, time
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import scheduler
import store

logger = logging.getLogger(__name__)

VERIFY_PREFIX = "verify:"
REJECT_PREFIX = "reject:"

REPORT_ROLE_PREFIX = "report_role:"
REPORT_PERIOD_PREFIX = "report_period:"
MANAGER_PREFIX = "manager:"
MANAGER_ADD_ROLE = f"{MANAGER_PREFIX}add_role"
MANAGER_ADD_TASK = f"{MANAGER_PREFIX}add_task"
MANAGER_LIST_TASKS = f"{MANAGER_PREFIX}list_tasks"
MANAGER_LIST_WORKERS = f"{MANAGER_PREFIX}list_workers"
MANAGER_FIRE_WORKER = f"{MANAGER_PREFIX}fire_worker"
MANAGER_FIRE_WORKER_PREFIX = f"{MANAGER_PREFIX}fire_worker:"
MANAGER_DELETE_TASK_PREFIX = f"{MANAGER_PREFIX}delete_task:"
MANAGER_DELETE_TASK_CONFIRM_PREFIX = f"{MANAGER_PREFIX}delete_task_confirm:"
MANAGER_TASK_ROLE_PREFIX = f"{MANAGER_PREFIX}task_role:"
MANAGER_TASK_RECURRENCE_PREFIX = f"{MANAGER_PREFIX}task_recurrence:"
MANAGER_TASK_WEEKDAY_PREFIX = f"{MANAGER_PREFIX}task_weekday:"

OWNER_PREFIX = "owner:"
OWNER_LIST_TASKS = f"{OWNER_PREFIX}list_tasks"
OWNER_LIST_WORKERS = f"{OWNER_PREFIX}list_workers"
OWNER_REPORTS = f"{OWNER_PREFIX}reports"

WEEKDAYS = [
    ("Monday", 0),
    ("Tuesday", 1),
    ("Wednesday", 2),
    ("Thursday", 3),
    ("Friday", 4),
    ("Saturday", 5),
    ("Sunday", 6),
]


def _can_view_reports(telegram_id: int) -> bool:
    return store.telegram_has_role(telegram_id, "admin") or store.telegram_has_role(
        telegram_id, "manager"
    ) or store.telegram_has_role(
        telegram_id, "owner"
    )


def _can_verify_task(telegram_id: int) -> bool:
    return store.telegram_has_role(telegram_id, "admin") or store.telegram_has_role(
        telegram_id, "manager"
    )


def _get_manager_user(telegram_id: int) -> dict | None:
    return store.get_user_by_telegram_and_role(telegram_id, "manager")


def _get_owner_user(telegram_id: int) -> dict | None:
    return store.get_user_by_telegram_and_role(telegram_id, "owner")


def manager_menu_markup() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("Add Role", callback_data=MANAGER_ADD_ROLE)],
        [InlineKeyboardButton("Add Task", callback_data=MANAGER_ADD_TASK)],
        [InlineKeyboardButton("Task List", callback_data=MANAGER_LIST_TASKS)],
        [InlineKeyboardButton("Worker List", callback_data=MANAGER_LIST_WORKERS)],
        [InlineKeyboardButton("Deduct Worker Points", callback_data=MANAGER_FIRE_WORKER)],
        [InlineKeyboardButton("Reports", callback_data=f"{REPORT_ROLE_PREFIX}all")],
    ]
    return InlineKeyboardMarkup(keyboard)


def owner_menu_markup() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("Task List", callback_data=OWNER_LIST_TASKS)],
        [InlineKeyboardButton("Worker List", callback_data=OWNER_LIST_WORKERS)],
        [InlineKeyboardButton("Reports", callback_data=OWNER_REPORTS)],
    ]
    return InlineKeyboardMarkup(keyboard)


async def manager_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    manager = _get_manager_user(update.effective_user.id)
    if not manager:
        await update.message.reply_text("Only managers can use this command.")
        return

    await update.message.reply_text(
        "Manager panel:",
        reply_markup=manager_menu_markup(),
    )


async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    owner = _get_owner_user(update.effective_user.id)
    if not owner:
        await update.message.reply_text("Only owners can use this command.")
        return

    await update.message.reply_text(
        "Owner panel:",
        reply_markup=owner_menu_markup(),
    )


async def manager_verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return
    if not _can_verify_task(query.from_user.id):
        await query.answer("Not allowed.", show_alert=True)
        return
    await query.answer()

    data = query.data
    run_id = data.split(":", maxsplit=1)[1]
    run = store.get_task_run(run_id)
    if not run:
        await query.edit_message_text("Task run not found.")
        return

    worker = store.get_user_by_role(run["worker_role"])
    task = store.get_task_by_id(run["task_id"])
    task_title = task["title"] if task else "Task"
    worker_text = run["worker_role"]
    worker_notified = False
    if worker:
        worker_text = f"{worker['name']} ({run['worker_role']})"

    if data.startswith(VERIFY_PREFIX):
        updated_worker = None
        store.update_task_run(
            run_id,
            {
                "status": "manager_verified",
                "manager_status": "verified",
                "verified_at": datetime.utcnow().replace(microsecond=0).isoformat(),
            },
        )
        if worker:
            if run.get("status") not in {"manager_verified", "manager_rejected"}:
                updated_worker = store.adjust_worker_points(worker["id"], 1)
            try:
                await context.bot.send_message(
                    chat_id=worker["telegram_id"],
                    text=(
                        f"Manager verified your update.\n"
                        f"Task: {task_title}\n"
                        f"Role: {run['worker_role']}\n"
                        "Status: Accepted.\n"
                        "+1 point added.\n"
                        f"Current points: {(updated_worker or worker).get('points', 0)}"
                    ),
                )
                worker_notified = True
            except Exception:
                logger.exception("Failed to notify worker after verify for run_id=%s", run_id)
        await query.edit_message_text("Verified. Task completion is now recorded.")
        return

    if data.startswith(REJECT_PREFIX):
        updated_worker = None
        store.update_task_run(
            run_id,
            {
                "status": "manager_rejected",
                "manager_status": "rejected",
                "verified_at": datetime.utcnow().replace(microsecond=0).isoformat(),
            },
        )
        if worker:
            if run.get("status") not in {"manager_verified", "manager_rejected"}:
                updated_worker = store.adjust_worker_points(worker["id"], -2)
            try:
                await context.bot.send_message(
                    chat_id=worker["telegram_id"],
                    text=(
                        f"Manager rejected your update.\n"
                        f"Task: {task_title}\n"
                        f"Role: {run['worker_role']}\n"
                        "Status: Rejected. Please coordinate with your manager.\n"
                        "-2 points deducted.\n"
                        f"Current points: {(updated_worker or worker).get('points', 0)}"
                    ),
                )
                worker_notified = True
            except Exception:
                logger.exception("Failed to notify worker after reject for run_id=%s", run_id)
        await query.edit_message_text(
            (
                f"Rejected for {worker_text}. Worker has been notified."
                if worker_notified
                else f"Rejected for {worker_text}. Worker notification failed."
            )
        )
        return


async def manager_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return

    manager = _get_manager_user(query.from_user.id)
    if not manager:
        await query.answer("Only managers can do this.", show_alert=True)
        return

    await query.answer()
    data = query.data

    if data == MANAGER_ADD_ROLE:
        context.user_data["manager_state"] = "awaiting_role_name"
        await query.edit_message_text("Send the new role name to add under you.")
        return

    if data == MANAGER_ADD_TASK:
        roles = store.list_roles_for_manager(manager["id"])
        if not roles:
            await query.edit_message_text(
                "No roles are under you yet. Use /manager -> Add Role first."
            )
            return

        context.user_data["manager_state"] = "awaiting_task_title"
        context.user_data["manager_task_draft"] = {"manager_id": manager["id"]}
        await query.edit_message_text("Send task title.")
        return

    if data == MANAGER_LIST_TASKS:
        await _send_manager_task_list(query, manager["id"])
        return

    if data == MANAGER_LIST_WORKERS:
        await _send_manager_worker_list(query, manager["id"])
        return

    if data == MANAGER_FIRE_WORKER:
        workers = store.list_workers_under_manager(manager["id"])
        if not workers:
            await query.edit_message_text("No active workers are assigned under you.")
            return

        keyboard = [
            [
                InlineKeyboardButton(
                    f"{worker['worker_role']} - {worker['name']}",
                    callback_data=f"{MANAGER_FIRE_WORKER_PREFIX}{worker['id']}",
                )
            ]
            for worker in workers
        ]
        await query.edit_message_text(
            "Select worker to deduct 2 points from:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith(MANAGER_TASK_ROLE_PREFIX):
        role = data.replace(MANAGER_TASK_ROLE_PREFIX, "", 1)
        draft = context.user_data.get("manager_task_draft", {})
        draft["worker_role"] = role
        context.user_data["manager_task_draft"] = draft
        keyboard = [
            [
                InlineKeyboardButton("Once", callback_data=f"{MANAGER_TASK_RECURRENCE_PREFIX}once"),
                InlineKeyboardButton("Daily", callback_data=f"{MANAGER_TASK_RECURRENCE_PREFIX}daily"),
            ],
            [
                InlineKeyboardButton("Weekly", callback_data=f"{MANAGER_TASK_RECURRENCE_PREFIX}weekly"),
            ],
        ]
        await query.edit_message_text(
            "Select repeat option:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith(MANAGER_TASK_RECURRENCE_PREFIX):
        recurrence = data.replace(MANAGER_TASK_RECURRENCE_PREFIX, "", 1)
        draft = context.user_data.get("manager_task_draft", {})
        draft["recurrence"] = recurrence
        context.user_data["manager_task_draft"] = draft
        if recurrence == "once":
            context.user_data["manager_state"] = "awaiting_task_date"
            await query.edit_message_text(
                "Send task date in YYYY-MM-DD format (example 2026-05-20)."
            )
            return
        if recurrence == "weekly":
            keyboard = [
                [
                    InlineKeyboardButton(
                        label,
                        callback_data=f"{MANAGER_TASK_WEEKDAY_PREFIX}{weekday}",
                    )
                ]
                for label, weekday in WEEKDAYS
            ]
            await query.edit_message_text(
                "Select weekly day:",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        context.user_data["manager_state"] = "awaiting_task_time"
        await query.edit_message_text(
            "Send task time in 24h format HH:MM (example 10:30)."
        )
        return

    if data.startswith(MANAGER_TASK_WEEKDAY_PREFIX):
        weekday = int(data.replace(MANAGER_TASK_WEEKDAY_PREFIX, "", 1))
        draft = context.user_data.get("manager_task_draft", {})
        draft["weekday"] = weekday
        context.user_data["manager_task_draft"] = draft
        context.user_data["manager_state"] = "awaiting_task_time"
        await query.edit_message_text(
            "Send task time in 24h format HH:MM (example 10:30)."
        )
        return

    if data.startswith(MANAGER_DELETE_TASK_CONFIRM_PREFIX):
        task_id = data.replace(MANAGER_DELETE_TASK_CONFIRM_PREFIX, "", 1)
        try:
            task = store.deactivate_manager_task(task_id, manager["id"])
        except ValueError as exc:
            await query.edit_message_text(f"Failed to delete task: {exc}")
            return

        scheduler.clear_all_task_jobs(context.application)
        scheduler.register_all_jobs(context.application)
        await query.edit_message_text(f"Task deleted: {task['title']}")
        return

    if data.startswith(MANAGER_DELETE_TASK_PREFIX):
        task_id = data.replace(MANAGER_DELETE_TASK_PREFIX, "", 1)
        task = store.get_task_by_id(task_id)
        if not task or not task.get("active", True) or task.get("manager_id") != manager["id"]:
            await query.edit_message_text("Task not found or already deleted.")
            return

        keyboard = [
            [
                InlineKeyboardButton(
                    "Confirm Delete",
                    callback_data=f"{MANAGER_DELETE_TASK_CONFIRM_PREFIX}{task_id}",
                )
            ],
            [InlineKeyboardButton("Back to Task List", callback_data=MANAGER_LIST_TASKS)],
        ]
        await query.edit_message_text(
            f"Delete task?\n\n"
            f"Task: {task['title']}\n"
            f"Role: {task['worker_role']}\n"
            f"Time: {task['time']}\n"
            f"Repeat: {task.get('recurrence', 'daily')}",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith(MANAGER_FIRE_WORKER_PREFIX):
        worker_id = data.replace(MANAGER_FIRE_WORKER_PREFIX, "", 1)
        worker = store.get_user_by_id(worker_id)
        if not worker or worker.get("role") != "worker":
            await query.edit_message_text("Worker not found.")
            return

        context.user_data["manager_state"] = "awaiting_fire_reason"
        context.user_data["fire_worker_id"] = worker_id
        await query.edit_message_text(
            f"Send the reason for deducting points from "
            f"{worker['name']} ({worker['worker_role']})."
        )
        return


async def owner_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return

    owner = _get_owner_user(query.from_user.id)
    if not owner:
        await query.answer("Only owners can do this.", show_alert=True)
        return

    await query.answer()
    data = query.data

    if data == OWNER_LIST_TASKS:
        await _send_owner_task_list(query, owner["id"])
        return

    if data == OWNER_LIST_WORKERS:
        await _send_owner_worker_list(query, owner["id"])
        return

    if data == OWNER_REPORTS:
        await _send_report_role_choices(query, query.from_user.id)
        return


def _format_task_row(index: int, task: dict) -> str:
    recurrence = task.get("recurrence", "daily")
    weekday = task.get("weekday")
    weekly_text = ""
    if recurrence == "weekly" and weekday is not None and 0 <= weekday < len(WEEKDAYS):
        weekly_text = f" ({WEEKDAYS[weekday][0]})"
    date_text = f"\n   Date: {task['scheduled_date']}" if task.get("scheduled_date") else ""
    manager_text = f"   Manager: {task['manager_name']}\n" if task.get("manager_name") else ""
    return (
        f"{index}. {task['title']}\n"
        f"   Worker Role: {task['worker_role']}\n"
        f"   Worker: {task['worker_name']}\n"
        f"{manager_text}"
        f"   Time: {task['time']}\n"
        f"   Repeat: {recurrence}{weekly_text}"
        f"{date_text}"
    )


async def _send_manager_task_list(query, manager_id: str) -> None:
    tasks = store.list_tasks_for_manager(manager_id)
    if not tasks:
        await query.edit_message_text("No active tasks found under you.")
        return

    task_lines = [_format_task_row(index, task) for index, task in enumerate(tasks, start=1)]
    keyboard = [
        [
            InlineKeyboardButton(
                f"Delete {index}. {task['title'][:25]}",
                callback_data=f"{MANAGER_DELETE_TASK_PREFIX}{task['id']}",
            )
        ]
        for index, task in enumerate(tasks, start=1)
    ]
    await query.edit_message_text(
        "Task List\n\n" + "\n\n".join(task_lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _send_owner_task_list(query, owner_id: str) -> None:
    tasks = store.list_tasks_for_owner(owner_id)
    if not tasks:
        await query.edit_message_text("No active tasks found under your managers.")
        return

    task_lines = [_format_task_row(index, task) for index, task in enumerate(tasks, start=1)]
    await query.edit_message_text("Task List\n\n" + "\n\n".join(task_lines))


def _format_worker_row(index: int, worker: dict) -> str:
    return (
        f"{index}. {worker['name']}\n"
        f"   Role: {worker['worker_role']}\n"
        f"   Telegram ID: {worker['telegram_id']}\n"
        f"   Points: {worker.get('points', 0)}"
    )


async def _send_manager_worker_list(query, manager_id: str) -> None:
    workers = store.list_workers_under_manager(manager_id)
    if not workers:
        await query.edit_message_text("No active workers are assigned under you.")
        return

    worker_lines = [
        _format_worker_row(index, worker)
        for index, worker in enumerate(workers, start=1)
    ]
    await query.edit_message_text("Worker List\n\n" + "\n\n".join(worker_lines))


async def _send_owner_worker_list(query, owner_id: str) -> None:
    workers = store.list_workers_under_owner(owner_id)
    if not workers:
        await query.edit_message_text("No active workers are assigned under your managers.")
        return

    worker_lines = [
        _format_worker_row(index, worker)
        for index, worker in enumerate(workers, start=1)
    ]
    await query.edit_message_text("Worker List\n\n" + "\n\n".join(worker_lines))


def _report_scope_for_user(telegram_id: int) -> dict:
    if store.telegram_has_role(telegram_id, "admin"):
        return {
            "type": "admin",
            "roles": store.list_roles(),
            "manager_id": None,
            "owner_id": None,
            "workers": store.list_users_by_role("worker"),
        }

    owner = _get_owner_user(telegram_id)
    if owner:
        return {
            "type": "owner",
            "roles": store.list_roles_for_owner(owner["id"]),
            "manager_id": None,
            "owner_id": owner["id"],
            "workers": store.list_workers_under_owner(owner["id"]),
        }

    manager = _get_manager_user(telegram_id)
    if manager:
        return {
            "type": "manager",
            "roles": store.list_roles_for_manager(manager["id"]),
            "manager_id": manager["id"],
            "owner_id": None,
            "workers": store.list_workers_under_manager(manager["id"]),
        }

    return {
        "type": "none",
        "roles": [],
        "manager_id": None,
        "owner_id": None,
        "workers": [],
    }


async def _send_report_role_choices(target, telegram_id: int) -> None:
    scope = _report_scope_for_user(telegram_id)
    roles = scope["roles"]
    if not roles:
        text = (
            "No roles found for reports."
            if scope["type"] == "admin"
            else "No roles are assigned under you yet."
        )
        if hasattr(target, "edit_message_text"):
            await target.edit_message_text(text)
        else:
            await target.reply_text(text)
        return

    role_buttons = [[InlineKeyboardButton("All", callback_data=f"{REPORT_ROLE_PREFIX}all")]]
    for role in roles:
        role_buttons.append(
            [InlineKeyboardButton(role, callback_data=f"{REPORT_ROLE_PREFIX}{role}")]
        )
    markup = InlineKeyboardMarkup(role_buttons)
    if hasattr(target, "edit_message_text"):
        await target.edit_message_text("Select role:", reply_markup=markup)
    else:
        await target.reply_text("Select role:", reply_markup=markup)


def _valid_hhmm(value: str) -> bool:
    try:
        hour, minute = value.split(":")
        time(int(hour), int(minute))
        return True
    except Exception:
        return False


def _valid_yyyy_mm_dd(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except Exception:
        return False


def _once_schedule_is_future(date_value: str, time_value: str) -> bool:
    try:
        run_at = datetime.strptime(f"{date_value} {time_value}", "%Y-%m-%d %H:%M")
        return run_at > datetime.now()
    except Exception:
        return False


async def manager_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    state = context.user_data.get("manager_state")
    if not state:
        return

    manager = _get_manager_user(update.effective_user.id)
    if not manager:
        return

    text = update.message.text.strip()

    if state == "awaiting_task_title":
        draft = context.user_data.get("manager_task_draft", {})
        draft["title"] = text
        context.user_data["manager_task_draft"] = draft
        context.user_data["manager_state"] = "awaiting_task_description"
        await update.message.reply_text("Send task description.")
        return

    if state == "awaiting_task_description":
        draft = context.user_data.get("manager_task_draft", {})
        draft["description"] = text
        context.user_data["manager_task_draft"] = draft
        roles = store.list_roles_for_manager(manager["id"])
        if not roles:
            await update.message.reply_text(
                "No roles are under you yet. Use /manager -> Add Role first."
            )
            context.user_data.pop("manager_state", None)
            context.user_data.pop("manager_task_draft", None)
            return
        keyboard = [
            [InlineKeyboardButton(role, callback_data=f"{MANAGER_TASK_ROLE_PREFIX}{role}")]
            for role in roles
        ]
        await update.message.reply_text(
            "Select role for this task:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if state == "awaiting_role_name":
        try:
            store.add_role(text, manager_id=manager["id"])
        except ValueError as exc:
            await update.message.reply_text(f"Failed to add role: {exc}")
        else:
            await update.message.reply_text(f"Role added under you: {text}")
        finally:
            context.user_data.pop("manager_state", None)
        return

    if state == "awaiting_task_date":
        if not _valid_yyyy_mm_dd(text):
            await update.message.reply_text("Invalid date format. Send as YYYY-MM-DD.")
            return
        draft = context.user_data.get("manager_task_draft", {})
        draft["scheduled_date"] = text
        context.user_data["manager_task_draft"] = draft
        context.user_data["manager_state"] = "awaiting_task_time"
        await update.message.reply_text(
            "Send task time in 24h format HH:MM (example 10:30)."
        )
        return

    if state == "awaiting_task_time":
        if not _valid_hhmm(text):
            await update.message.reply_text("Invalid time format. Send as HH:MM.")
            return

        draft = context.user_data.get("manager_task_draft", {})
        if draft.get("recurrence") == "once" and draft.get("scheduled_date"):
            if not _once_schedule_is_future(draft["scheduled_date"], text):
                await update.message.reply_text(
                    "The selected date/time is in the past. Send a future time."
                )
                return
        try:
            task = store.add_task(
                title=draft["title"],
                description=draft["description"],
                worker_role=draft["worker_role"],
                manager_id=manager["id"],
                time_hhmm=text,
                recurrence=draft.get("recurrence", "daily"),
                weekday=draft.get("weekday"),
                scheduled_date=draft.get("scheduled_date"),
            )
            scheduler.schedule_task_job(context.application, task)
            await update.message.reply_text(
                f"Task added and scheduled ({task['recurrence']})."
            )
        except ValueError as exc:
            await update.message.reply_text(f"Failed to add task: {exc}")
        finally:
            context.user_data.pop("manager_state", None)
            context.user_data.pop("manager_task_draft", None)
        return

    if state != "awaiting_fire_reason":
        return

    worker_id = context.user_data.get("fire_worker_id")
    worker = store.get_user_by_id(worker_id)
    if not worker:
        await update.message.reply_text("Worker is no longer active.")
        context.user_data.pop("manager_state", None)
        context.user_data.pop("fire_worker_id", None)
        return

    reason = text
    try:
        firing = store.fire_worker(worker_id, manager["id"], reason)
    except ValueError as exc:
        await update.message.reply_text(f"Failed to fire worker: {exc}")
    else:
        await context.bot.send_message(
            chat_id=firing["worker_telegram_id"],
            text=(
                "Manager action recorded.\n"
                f"Role: {firing['worker_role']}\n"
                f"Reason: {firing['reason']}\n\n"
                "-2 points deducted.\n"
                f"Current points: {firing.get('worker_points', 'n/a')}"
            ),
        )
        await update.message.reply_text(
            f"Worker notified and -2 points deducted: "
            f"{firing['worker_role']} - {firing['worker_name']}"
        )
    finally:
        context.user_data.pop("manager_state", None)
        context.user_data.pop("fire_worker_id", None)


async def report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not _can_view_reports(update.effective_user.id):
        await update.message.reply_text("Only managers, owners, or admin can view reports.")
        return

    await _send_report_role_choices(update.message, update.effective_user.id)


async def report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return
    if not _can_view_reports(query.from_user.id):
        await query.answer("Not allowed.", show_alert=True)
        return
    await query.answer()

    data = query.data
    if data.startswith(REPORT_ROLE_PREFIX):
        role = data.replace(REPORT_ROLE_PREFIX, "", 1)
        scope = _report_scope_for_user(query.from_user.id)
        if role != "all" and role not in scope["roles"]:
            await query.edit_message_text("This role is not available in your report scope.")
            return
        keyboard = [
            [
                InlineKeyboardButton(
                    "Today",
                    callback_data=f"{REPORT_PERIOD_PREFIX}today|{role}",
                ),
                InlineKeyboardButton(
                    "This Week",
                    callback_data=f"{REPORT_PERIOD_PREFIX}week|{role}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "This Month",
                    callback_data=f"{REPORT_PERIOD_PREFIX}month|{role}",
                ),
                InlineKeyboardButton(
                    "All Time",
                    callback_data=f"{REPORT_PERIOD_PREFIX}all|{role}",
                ),
            ],
        ]
        await query.edit_message_text(
            f"Selected role: {role}. Select period:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith(REPORT_PERIOD_PREFIX):
        payload = data.replace(REPORT_PERIOD_PREFIX, "", 1)
        period, role = payload.split("|", maxsplit=1)
        worker_role = None if role == "all" else role
        scope = _report_scope_for_user(query.from_user.id)
        if worker_role and worker_role not in scope["roles"]:
            await query.edit_message_text("This role is not available in your report scope.")
            return

        runs = store.get_runs_for_report(
            worker_role=worker_role,
            period=period,
            manager_id=scope["manager_id"],
            owner_id=scope["owner_id"],
        )
        stats = store.summarize_runs(runs)
        completion_rate = (
            int((stats["verified"] / stats["total"]) * 100) if stats["total"] else 0
        )
        if worker_role:
            report_workers = [
                worker
                for worker in [store.get_user_by_role(worker_role)]
                if worker is not None
            ]
        else:
            report_workers = scope["workers"]
        total_worker_points = sum(worker.get("points", 0) for worker in report_workers)
        point_lines = [
            f"{worker['name']} ({worker['worker_role']}): {worker.get('points', 0)}"
            for worker in report_workers
        ]
        yes_count = sum(1 for run in runs if run.get("worker_response") == "yes")
        no_count = sum(1 for run in runs if run.get("worker_response") == "no")
        extend_count = sum(1 for run in runs if run.get("worker_response") == "extend")
        pending_response_count = sum(
            1 for run in runs if run.get("worker_response") is None
        )
        pending_manager_count = sum(
            1
            for run in runs
            if run.get("worker_response") in {"yes", "no"}
            and run.get("manager_status") == "pending"
        )

        task_metrics: dict[str, dict[str, int | str]] = {}
        for run in runs:
            task_id = run.get("task_id")
            if not task_id:
                continue
            task = store.get_task_by_id(task_id)
            task_title = task["title"] if task else f"Unknown Task ({task_id})"
            if task_id not in task_metrics:
                task_metrics[task_id] = {
                    "title": task_title,
                    "total": 0,
                    "verified": 0,
                    "not_done": 0,
                    "rejected": 0,
                    "pending_manager": 0,
                }

            metric = task_metrics[task_id]
            metric["total"] += 1
            if run.get("status") == "manager_verified":
                metric["verified"] += 1
            if run.get("worker_response") == "no":
                metric["not_done"] += 1
            if run.get("status") == "manager_rejected":
                metric["rejected"] += 1
            if (
                run.get("worker_response") in {"yes", "no"}
                and run.get("manager_status") == "pending"
            ):
                metric["pending_manager"] += 1

        sorted_task_metrics = sorted(
            task_metrics.values(), key=lambda item: int(item["total"]), reverse=True
        )
        task_lines: list[str] = []
        max_tasks_to_show = 12
        for index, metric in enumerate(sorted_task_metrics[:max_tasks_to_show], start=1):
            task_lines.append(
                f"{index}) {metric['title']}\n"
                f"   Total: {metric['total']} | Verified: {metric['verified']} | "
                f"NO: {metric['not_done']} | Rejected: {metric['rejected']} | "
                f"Pending manager: {metric['pending_manager']}"
            )
        if len(sorted_task_metrics) > max_tasks_to_show:
            task_lines.append(
                f"...and {len(sorted_task_metrics) - max_tasks_to_show} more tasks."
            )

        role_label = "All" if role == "all" else role
        report_text = (
            f"Role: {role_label}\n"
            f"Period: {period.title()}\n\n"
            f"Total assigned: {stats['total']}\n"
            f"Completed (verified): {stats['verified']}\n"
            f"Not completed: {stats['not_completed']}\n"
            f"Rejected by manager: {stats['rejected']}\n"
            f"Extended: {stats['extended']}\n"
            f"Completion rate: {completion_rate}%\n\n"
            f"Total worker points: {total_worker_points}\n"
            "Worker points:\n"
            + ("\n".join(point_lines) if point_lines else "No active workers found.")
            + "\n\n"
            f"Responses -> YES: {yes_count}, NO: {no_count}, EXTEND: {extend_count}, "
            f"No response: {pending_response_count}\n"
            f"Manager verification pending: {pending_manager_count}\n\n"
            "Task-wise metrics:\n"
            + ("\n".join(task_lines) if task_lines else "No task runs in this period.")
        )
        await query.edit_message_text(report_text)
