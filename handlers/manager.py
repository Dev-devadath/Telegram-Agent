from datetime import datetime, time
import logging
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import db_async
import scheduler
import store
from performance import OperationTimer

logger = logging.getLogger(__name__)

VERIFY_PREFIX = "verify:"
REJECT_PREFIX = "reject:"

REPORT_ROLE_PREFIX = "report_role:"
REPORT_PERIOD_PREFIX = "report_period:"
REPORT_OWNER_PREFIX = "report_owner:"
MANAGER_PREFIX = "manager:"
MANAGER_ADD_ROLE = f"{MANAGER_PREFIX}add_role"
MANAGER_ADD_TASK = f"{MANAGER_PREFIX}add_task"
MANAGER_LIST_TASKS = f"{MANAGER_PREFIX}list_tasks"
MANAGER_LIST_WORKERS = f"{MANAGER_PREFIX}list_workers"
MANAGER_FIRE_WORKER = f"{MANAGER_PREFIX}fire_worker"
MANAGER_FIRE_WORKER_PREFIX = f"{MANAGER_PREFIX}fire_worker:"
MANAGER_TERMINATE_WORKER = f"{MANAGER_PREFIX}terminate_worker"
MANAGER_TERMINATE_WORKER_PREFIX = f"{MANAGER_PREFIX}terminate_worker:"
MANAGER_TERMINATE_CONFIRM_PREFIX = f"{MANAGER_PREFIX}terminate_confirm:"
MANAGER_DELETE_TASK_PREFIX = f"{MANAGER_PREFIX}delete_task:"
MANAGER_DELETE_TASK_CONFIRM_PREFIX = f"{MANAGER_PREFIX}delete_task_confirm:"
MANAGER_TASK_ROLE_PREFIX = f"{MANAGER_PREFIX}task_role:"
MANAGER_TASK_RECURRENCE_PREFIX = f"{MANAGER_PREFIX}task_recurrence:"
MANAGER_TASK_WEEKDAY_PREFIX = f"{MANAGER_PREFIX}task_weekday:"
MANAGER_TASK_PARENT_PREFIX = f"{MANAGER_PREFIX}task_parent:"
MANAGER_TASK_PENALTY_PREFIX = f"{MANAGER_PREFIX}task_penalty:"
MANAGER_TASK_VERIFIER_PREFIX = f"{MANAGER_PREFIX}task_verifier:"

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


async def _can_view_reports(telegram_id: int) -> bool:
    return await db_async.db_call(
        store.telegram_has_any_role,
        telegram_id,
        ["admin", "manager", "owner"],
    )


async def _can_verify_task(telegram_id: int) -> bool:
    return await db_async.db_call(
        store.telegram_has_any_role,
        telegram_id,
        ["admin", "manager"],
    )


async def _get_manager_user(telegram_id: int) -> dict | None:
    return await db_async.db_call(store.get_user_by_telegram_and_role, telegram_id, "manager")


async def _get_owner_user(telegram_id: int) -> dict | None:
    return await db_async.db_call(store.get_user_by_telegram_and_role, telegram_id, "owner")


def manager_menu_markup() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("Add Role", callback_data=MANAGER_ADD_ROLE)],
        [InlineKeyboardButton("Add Task", callback_data=MANAGER_ADD_TASK)],
        [InlineKeyboardButton("Task List", callback_data=MANAGER_LIST_TASKS)],
        [InlineKeyboardButton("Worker List", callback_data=MANAGER_LIST_WORKERS)],
        [InlineKeyboardButton("Deduct Worker Points", callback_data=MANAGER_FIRE_WORKER)],
        [InlineKeyboardButton("Terminate Staff", callback_data=MANAGER_TERMINATE_WORKER)],
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
    manager = await _get_manager_user(update.effective_user.id)
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
    owner = await _get_owner_user(update.effective_user.id)
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
    await query.answer()

    with OperationTimer("manager.verify_callback", user_id=query.from_user.id):
        if not await _can_verify_task(query.from_user.id):
            await query.edit_message_text("Not allowed.")
            return

        data = query.data
        run_id = data.split(":", maxsplit=1)[1]

        if data.startswith(VERIFY_PREFIX):
            result = await db_async.db_call(store.verify_task_run, run_id)
            run = result["run"]
            task = result["task"]
            worker = result["worker"]
            updated_worker = result["updated_worker"]
            task_title = task["title"] if task else "Task"
            worker_text = run["worker_role"]
            if worker:
                worker_text = f"{worker['name']} ({run['worker_role']})"

            if worker:
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
                except Exception:
                    logger.exception(
                        "Failed to notify worker after verify for run_id=%s", run_id
                    )

            dependent_tasks = result["dependent_tasks"]
            if dependent_tasks and not result["was_already_finalized"]:
                await query.edit_message_text(
                    "Verified. Task completion is now recorded.\n"
                    "Triggering dependent tasks..."
                )
                context.application.create_task(
                    scheduler.fire_dependent_tasks_background(
                        context,
                        dependent_tasks,
                        run_id,
                    )
                )
            else:
                await query.edit_message_text("Verified. Task completion is now recorded.")
            return

        if data.startswith(REJECT_PREFIX):
            result = await db_async.db_call(store.reject_task_run, run_id)
            run = result["run"]
            task = result["task"]
            worker = result["worker"]
            updated_worker = result["updated_worker"]
            task_title = task["title"] if task else "Task"
            worker_text = run["worker_role"]
            worker_notified = False
            points_text = (
                "No points deducted for this no-penalty task."
                if task and task.get("no_penalty")
                else "-2 points deducted."
            )
            if worker:
                worker_text = f"{worker['name']} ({run['worker_role']})"
                try:
                    await context.bot.send_message(
                        chat_id=worker["telegram_id"],
                        text=(
                            f"Manager rejected your update.\n"
                            f"Task: {task_title}\n"
                            f"Role: {run['worker_role']}\n"
                            "Status: Rejected. Please coordinate with your manager.\n"
                            f"{points_text}\n"
                            f"Current points: {(updated_worker or worker).get('points', 0)}"
                        ),
                    )
                    worker_notified = True
                except Exception:
                    logger.exception(
                        "Failed to notify worker after reject for run_id=%s", run_id
                    )
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
    await query.answer()

    manager = await _get_manager_user(query.from_user.id)
    if not manager:
        await query.edit_message_text("Only managers can do this.")
        return

    data = query.data

    if data == MANAGER_ADD_ROLE:
        context.user_data["manager_state"] = "awaiting_role_name"
        await query.edit_message_text("Send the new role name to add under you.")
        return

    if data == MANAGER_ADD_TASK:
        roles = await db_async.db_call(store.list_roles_for_manager, manager["id"])
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
        workers = await db_async.db_call(store.list_workers_under_manager, manager["id"])
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

    if data == MANAGER_TERMINATE_WORKER:
        workers = await db_async.db_call(store.list_workers_under_manager, manager["id"])
        if not workers:
            await query.edit_message_text("No active workers are assigned under you.")
            return

        keyboard = [
            [
                InlineKeyboardButton(
                    f"{worker['worker_role']} - {worker['name']}",
                    callback_data=f"{MANAGER_TERMINATE_WORKER_PREFIX}{worker['id']}",
                )
            ]
            for worker in workers
        ]
        await query.edit_message_text(
            "Select staff to terminate (their role becomes available again):",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith(MANAGER_TERMINATE_CONFIRM_PREFIX):
        worker_id = data.replace(MANAGER_TERMINATE_CONFIRM_PREFIX, "", 1)
        try:
            worker = await db_async.db_call(
                store.terminate_worker, worker_id, manager["id"]
            )
        except ValueError as exc:
            await query.edit_message_text(f"Failed to terminate staff: {exc}")
            return

        try:
            await context.bot.send_message(
                chat_id=worker["telegram_id"],
                text=(
                    "You have been removed from your role.\n"
                    f"Role: {worker.get('worker_role')}\n"
                    "Please contact your manager for details."
                ),
            )
        except Exception:
            logger.exception(
                "Failed to notify terminated worker worker_id=%s", worker_id
            )
        await query.edit_message_text(
            f"Staff terminated: {worker['name']} ({worker.get('worker_role')}).\n"
            "The role is now available for a new registration."
        )
        return

    if data.startswith(MANAGER_TERMINATE_WORKER_PREFIX):
        worker_id = data.replace(MANAGER_TERMINATE_WORKER_PREFIX, "", 1)
        worker = await db_async.db_call(store.get_user_by_id, worker_id)
        if not worker or worker.get("role") != "worker":
            await query.edit_message_text("Worker not found.")
            return

        keyboard = [
            [
                InlineKeyboardButton(
                    "Confirm Terminate",
                    callback_data=f"{MANAGER_TERMINATE_CONFIRM_PREFIX}{worker_id}",
                )
            ],
            [InlineKeyboardButton("Cancel", callback_data=MANAGER_TERMINATE_WORKER)],
        ]
        await query.edit_message_text(
            f"Terminate {worker['name']} ({worker.get('worker_role')})?\n"
            "They will be logged out and the role becomes claimable again.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith(MANAGER_TASK_PENALTY_PREFIX):
        value = data.replace(MANAGER_TASK_PENALTY_PREFIX, "", 1)
        draft = context.user_data.get("manager_task_draft", {})
        draft["no_penalty"] = value == "no_penalty"
        context.user_data["manager_task_draft"] = draft
        roles = await db_async.db_call(store.list_roles_for_manager, manager["id"])
        if not roles:
            await query.edit_message_text(
                "No roles are under you yet. Use /manager -> Add Role first."
            )
            context.user_data.pop("manager_state", None)
            context.user_data.pop("manager_task_draft", None)
            return
        keyboard = [
            [InlineKeyboardButton(role, callback_data=f"{MANAGER_TASK_ROLE_PREFIX}{role}")]
            for role in roles
        ]
        await query.edit_message_text(
            "Select role for this task:",
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
                InlineKeyboardButton(
                    "Me (verify myself)",
                    callback_data=f"{MANAGER_TASK_VERIFIER_PREFIX}self",
                )
            ]
        ]
        managers = await db_async.db_call(store.list_users_by_role, "manager")
        for candidate in managers:
            if candidate["id"] == manager["id"]:
                continue
            keyboard.append(
                [
                    InlineKeyboardButton(
                        candidate["name"],
                        callback_data=f"{MANAGER_TASK_VERIFIER_PREFIX}{candidate['id']}",
                    )
                ]
            )
        await query.edit_message_text(
            "Who should verify this task when the worker responds?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith(MANAGER_TASK_VERIFIER_PREFIX):
        value = data.replace(MANAGER_TASK_VERIFIER_PREFIX, "", 1)
        draft = context.user_data.get("manager_task_draft", {})
        draft["verifier_id"] = None if value == "self" else value
        context.user_data["manager_task_draft"] = draft
        keyboard = [
            [
                InlineKeyboardButton("Once", callback_data=f"{MANAGER_TASK_RECURRENCE_PREFIX}once"),
                InlineKeyboardButton("Daily", callback_data=f"{MANAGER_TASK_RECURRENCE_PREFIX}daily"),
            ],
            [
                InlineKeyboardButton("Weekly", callback_data=f"{MANAGER_TASK_RECURRENCE_PREFIX}weekly"),
                InlineKeyboardButton(
                    "After Another Task",
                    callback_data=f"{MANAGER_TASK_RECURRENCE_PREFIX}after_task",
                ),
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
        if recurrence == "after_task":
            parent_tasks = await db_async.db_call(
                store.list_parent_task_options,
                manager_id=manager["id"],
            )
            if not parent_tasks:
                await query.edit_message_text(
                    "No parent tasks available yet. Create a normal task first."
                )
                return
            keyboard = [
                [
                    InlineKeyboardButton(
                        f"{task['title']} ({task['worker_role']})",
                        callback_data=f"{MANAGER_TASK_PARENT_PREFIX}{task['id']}",
                    )
                ]
                for task in parent_tasks
            ]
            await query.edit_message_text(
                "Select parent task (this task will fire after parent verification):",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        context.user_data["manager_state"] = "awaiting_task_time"
        await query.edit_message_text(
            "Send task time in 24h format HH:MM (example 10:30)."
        )
        return

    if data.startswith(MANAGER_TASK_PARENT_PREFIX):
        parent_task_id = data.replace(MANAGER_TASK_PARENT_PREFIX, "", 1)
        draft = context.user_data.get("manager_task_draft", {})
        draft["depends_on_task_id"] = parent_task_id
        context.user_data["manager_task_draft"] = draft
        await _create_task_from_draft(query, context, manager["id"])
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
            task = await db_async.db_call(
                store.deactivate_manager_task,
                task_id,
                manager["id"],
            )
        except ValueError as exc:
            await query.edit_message_text(f"Failed to delete task: {exc}")
            return

        scheduler.clear_all_task_jobs(context.application)
        scheduler.register_all_jobs(context.application)
        await query.edit_message_text(f"Task deleted: {task['title']}")
        return

    if data.startswith(MANAGER_DELETE_TASK_PREFIX):
        task_id = data.replace(MANAGER_DELETE_TASK_PREFIX, "", 1)
        task = await db_async.db_call(store.get_task_by_id, task_id)
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
        worker = await db_async.db_call(store.get_user_by_id, worker_id)
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
    await query.answer()

    owner = await _get_owner_user(query.from_user.id)
    if not owner:
        await query.edit_message_text("Only owners can do this.")
        return

    data = query.data

    if data == OWNER_LIST_TASKS:
        await _send_owner_task_list(query, owner["id"])
        return

    if data == OWNER_LIST_WORKERS:
        await _send_owner_worker_list(query, owner["id"])
        return

    if data == OWNER_REPORTS:
        await _send_report_role_choices(query, query.from_user.id, context)
        return


def _format_task_row(index: int, task: dict) -> str:
    recurrence = task.get("recurrence", "daily")
    weekday = task.get("weekday")
    weekly_text = ""
    if recurrence == "weekly" and weekday is not None and 0 <= weekday < len(WEEKDAYS):
        weekly_text = f" ({WEEKDAYS[weekday][0]})"
    if recurrence == "after_task":
        repeat_text = "after_task"
        time_text = "After parent verification"
        date_text = ""
    else:
        repeat_text = f"{recurrence}{weekly_text}"
        time_text = task["time"]
        date_text = f"\n   Date: {task['scheduled_date']}" if task.get("scheduled_date") else ""
    manager_text = f"   Manager: {task['manager_name']}\n" if task.get("manager_name") else ""
    verifier_text = (
        f"   Verifier: {task['verifier_name']}\n" if task.get("verifier_name") else ""
    )
    parent_text = (
        f"\n   After: {task['parent_task_title']}"
        if recurrence == "after_task" and task.get("parent_task_title")
        else ""
    )
    description = task.get("description") or "No description"
    penalty_text = "\n   Points: No deduction on rejection" if task.get("no_penalty") else ""
    return (
        f"{index}. {task['title']}\n"
        f"   Description: {description}\n"
        f"   Worker Role: {task['worker_role']}\n"
        f"   Worker: {task['worker_name']}\n"
        f"{manager_text}"
        f"{verifier_text}"
        f"   Time: {time_text}\n"
        f"   Repeat: {repeat_text}"
        f"{penalty_text}"
        f"{parent_text}"
        f"{date_text}"
    )


async def _send_manager_task_list(query, manager_id: str) -> None:
    tasks = await db_async.db_call(store.list_tasks_for_manager, manager_id)
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
    tasks = await db_async.db_call(store.list_tasks_for_owner, owner_id)
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
    workers = await db_async.db_call(store.list_workers_under_manager, manager_id)
    if not workers:
        await query.edit_message_text("No active workers are assigned under you.")
        return

    worker_lines = [
        _format_worker_row(index, worker)
        for index, worker in enumerate(workers, start=1)
    ]
    await query.edit_message_text("Worker List\n\n" + "\n\n".join(worker_lines))


async def _send_owner_worker_list(query, owner_id: str) -> None:
    workers = await db_async.db_call(store.list_workers_under_owner, owner_id)
    if not workers:
        await query.edit_message_text("No active workers are assigned under your managers.")
        return

    worker_lines = [
        _format_worker_row(index, worker)
        for index, worker in enumerate(workers, start=1)
    ]
    await query.edit_message_text("Worker List\n\n" + "\n\n".join(worker_lines))


async def _send_manager_task_role_choices(target, manager_id: str) -> None:
    roles = await db_async.db_call(store.list_roles_for_manager, manager_id)
    if not roles:
        await target.reply_text("No roles are under you yet. Use /manager -> Add Role first.")
        return
    keyboard = [
        [InlineKeyboardButton(role, callback_data=f"{MANAGER_TASK_ROLE_PREFIX}{role}")]
        for role in roles
    ]
    await target.reply_text(
        "Select role for this task:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _report_scope_for_user(telegram_id: int) -> dict:
    if await db_async.db_call(store.telegram_has_role, telegram_id, "admin"):
        return {
            "type": "admin",
            "roles": await db_async.db_call(store.list_roles),
            "manager_id": None,
            "owner_id": None,
            "workers": await db_async.db_call(store.list_users_by_role, "worker"),
        }

    owner = await _get_owner_user(telegram_id)
    if owner:
        return {
            "type": "owner",
            "roles": await db_async.db_call(store.list_roles_for_owner, owner["id"]),
            "manager_id": None,
            "owner_id": owner["id"],
            "workers": await db_async.db_call(store.list_workers_under_owner, owner["id"]),
        }

    manager = await _get_manager_user(telegram_id)
    if manager:
        return {
            "type": "manager",
            "roles": await db_async.db_call(store.list_roles_for_manager, manager["id"]),
            "manager_id": manager["id"],
            "owner_id": None,
            "workers": await db_async.db_call(store.list_workers_under_manager, manager["id"]),
        }

    return {
        "type": "none",
        "roles": [],
        "manager_id": None,
        "owner_id": None,
        "workers": [],
    }


async def _send_report_role_choices(
    target,
    telegram_id: int,
    context: ContextTypes.DEFAULT_TYPE | None = None,
    owner_choice: str | None = None,
) -> None:
    scope = await _report_scope_for_user(telegram_id)

    if scope["type"] == "admin" and owner_choice is None:
        owners = await db_async.db_call(store.list_users_by_role, "owner")
        if owners:
            keyboard = [
                [
                    InlineKeyboardButton(
                        "All Companies",
                        callback_data=f"{REPORT_OWNER_PREFIX}all",
                    )
                ]
            ]
            for owner in owners:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            owner["name"],
                            callback_data=f"{REPORT_OWNER_PREFIX}{owner['id']}",
                        )
                    ]
                )
            markup = InlineKeyboardMarkup(keyboard)
            if hasattr(target, "edit_message_text"):
                await target.edit_message_text("Select company:", reply_markup=markup)
            else:
                await target.reply_text("Select company:", reply_markup=markup)
            return

    if scope["type"] == "admin" and owner_choice and owner_choice != "all":
        owner = await db_async.db_call(store.get_user_by_id, owner_choice)
        if not owner or owner.get("role") != "owner":
            text = "Company not found."
            if hasattr(target, "edit_message_text"):
                await target.edit_message_text(text)
            else:
                await target.reply_text(text)
            return
        scope["owner_id"] = owner_choice
        scope["roles"] = await db_async.db_call(store.list_roles_for_owner, owner_choice)

    if context is not None:
        context.user_data["report_scope"] = scope
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


async def _create_task_from_draft(
    target,
    context: ContextTypes.DEFAULT_TYPE,
    manager_id: str,
) -> None:
    draft = context.user_data.get("manager_task_draft", {})
    try:
        task = await db_async.db_call(
            store.add_task,
            title=draft["title"],
            description=draft["description"],
            worker_role=draft["worker_role"],
            manager_id=manager_id,
            time_hhmm=draft.get("time", "00:00"),
            recurrence=draft.get("recurrence", "daily"),
            weekday=draft.get("weekday"),
            scheduled_date=draft.get("scheduled_date"),
            depends_on_task_id=draft.get("depends_on_task_id"),
            no_penalty=draft.get("no_penalty", False),
            verifier_id=draft.get("verifier_id"),
        )
        scheduler.schedule_task_job(context.application, task)
        message = f"Task added and scheduled ({task['recurrence']})."
        if hasattr(target, "edit_message_text"):
            await target.edit_message_text(message)
        else:
            await target.reply_text(message)
    except ValueError as exc:
        message = f"Failed to add task: {exc}"
        if hasattr(target, "edit_message_text"):
            await target.edit_message_text(message)
        else:
            await target.reply_text(message)
    finally:
        context.user_data.pop("manager_state", None)
        context.user_data.pop("manager_task_draft", None)


async def manager_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    state = context.user_data.get("manager_state")
    if not state:
        return

    manager = await _get_manager_user(update.effective_user.id)
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
        context.user_data["manager_state"] = "awaiting_task_penalty"
        keyboard = [
            [
                InlineKeyboardButton(
                    "Normal points",
                    callback_data=f"{MANAGER_TASK_PENALTY_PREFIX}normal",
                )
            ],
            [
                InlineKeyboardButton(
                    "No deduction on rejection",
                    callback_data=f"{MANAGER_TASK_PENALTY_PREFIX}no_penalty",
                )
            ],
        ]
        await update.message.reply_text(
            "Should this task deduct points if the manager rejects the worker response?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if state == "awaiting_role_name":
        try:
            await db_async.db_call(store.add_role, text, manager_id=manager["id"])
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
        draft["time"] = text
        context.user_data["manager_task_draft"] = draft
        await _create_task_from_draft(update.message, context, manager["id"])
        return

    if state != "awaiting_fire_reason":
        return

    worker_id = context.user_data.get("fire_worker_id")
    worker = await db_async.db_call(store.get_user_by_id, worker_id)
    if not worker:
        await update.message.reply_text("Worker is no longer active.")
        context.user_data.pop("manager_state", None)
        context.user_data.pop("fire_worker_id", None)
        return

    reason = text
    try:
        firing = await db_async.db_call(store.fire_worker, worker_id, manager["id"], reason)
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


def _format_report_text(role: str, period: str, summary: dict[str, Any]) -> str:
    stats = summary["stats"]
    completion_rate = (
        int((stats["verified"] / stats["total"]) * 100) if stats["total"] else 0
    )
    report_workers = summary["workers"]
    role_performance = summary.get("role_performance", {})
    total_worker_points = sum(worker.get("points", 0) for worker in report_workers)
    point_lines = []
    for worker in report_workers:
        perf = role_performance.get(worker["worker_role"])
        if perf and perf["total"]:
            # Performance = points earned (1 per verified task) / max earnable points.
            percentage = round(perf["verified"] * 100 / perf["total"])
            perf_text = (
                f" | Performance: {percentage}% "
                f"({perf['verified']}/{perf['total']} pts)"
            )
        else:
            perf_text = " | Performance: n/a"
        point_lines.append(
            f"{worker['name']} ({worker['worker_role']}): "
            f"{worker.get('points', 0)}{perf_text}"
        )

    task_metrics = summary["task_metrics"]
    task_lines: list[str] = []
    for index, metric in enumerate(task_metrics, start=1):
        description = metric.get("description") or "No description"
        penalty_text = " | No-penalty" if metric.get("no_penalty") else ""
        worker_label = metric.get("worker_name") or "Unassigned"
        role_label_line = metric.get("worker_role") or ""
        task_lines.append(
            f"{index}) {metric['title']}\n"
            f"   Description: {description}\n"
            f"   Worker: {worker_label} ({role_label_line})\n"
            f"   Total: {metric['total']} | Verified: {metric['verified']} | "
            f"NO: {metric['not_done']} | Rejected: {metric['rejected']} | "
            f"Pending worker: {metric['pending_response']} | "
            f"Pending manager: {metric['pending_manager']}{penalty_text}"
        )
    if summary["total_task_groups"] > len(task_metrics):
        task_lines.append(
            f"...and {summary['total_task_groups'] - len(task_metrics)} more tasks."
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
        f"Responses -> YES: {summary['yes_count']}, NO: {summary['no_count']}, "
        f"EXTEND: {summary['extend_count']}, "
        f"No response: {summary['pending_response_count']}\n"
        f"Manager verification pending: {summary['pending_manager_count']}\n\n"
        "Task-wise metrics:\n"
        + ("\n".join(task_lines) if task_lines else "No task runs in this period.")
    )
    return report_text


def _split_message(text: str, limit: int = 3900) -> list[str]:
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n\n", 0, limit)
        if split_at == -1:
            split_at = remaining.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


async def report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _can_view_reports(update.effective_user.id):
        await update.message.reply_text("Only managers, owners, or admin can view reports.")
        return

    await _send_report_role_choices(update.message, update.effective_user.id, context)


async def report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return
    await query.answer()

    with OperationTimer("manager.report_callback", user_id=query.from_user.id):
        if not await _can_view_reports(query.from_user.id):
            await query.edit_message_text("Not allowed.")
            return

        data = query.data
        if data.startswith(REPORT_OWNER_PREFIX):
            owner_choice = data.replace(REPORT_OWNER_PREFIX, "", 1)
            await _send_report_role_choices(
                query, query.from_user.id, context, owner_choice=owner_choice
            )
            return

        if data.startswith(REPORT_ROLE_PREFIX):
            role = data.replace(REPORT_ROLE_PREFIX, "", 1)
            scope = context.user_data.get("report_scope")
            if not scope:
                scope = await _report_scope_for_user(query.from_user.id)
                context.user_data["report_scope"] = scope
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
                [
                    InlineKeyboardButton(
                        "Pending Tasks",
                        callback_data=f"{REPORT_PERIOD_PREFIX}pending|{role}",
                    )
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
            scope = context.user_data.get("report_scope")
            if not scope:
                scope = await _report_scope_for_user(query.from_user.id)
            if worker_role and worker_role not in scope["roles"]:
                await query.edit_message_text("This role is not available in your report scope.")
                return

            summary = await db_async.db_call(
                store.get_report_summary,
                worker_role=worker_role,
                period=period,
                manager_id=scope["manager_id"],
                owner_id=scope["owner_id"],
            )
            report_text = _format_report_text(role, period, summary)
            chunks = _split_message(report_text)
            await query.edit_message_text(chunks[0])
            if query.message:
                for chunk in chunks[1:]:
                    await query.message.reply_text(chunk)
            return
