from datetime import datetime, time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import scheduler
import store

VERIFY_PREFIX = "verify:"
REJECT_PREFIX = "reject:"

REPORT_ROLE_PREFIX = "report_role:"
REPORT_PERIOD_PREFIX = "report_period:"
MANAGER_PREFIX = "manager:"
MANAGER_ADD_ROLE = f"{MANAGER_PREFIX}add_role"
MANAGER_ADD_TASK = f"{MANAGER_PREFIX}add_task"
MANAGER_FIRE_WORKER = f"{MANAGER_PREFIX}fire_worker"
MANAGER_FIRE_WORKER_PREFIX = f"{MANAGER_PREFIX}fire_worker:"
MANAGER_TASK_ROLE_PREFIX = f"{MANAGER_PREFIX}task_role:"
MANAGER_TASK_RECURRENCE_PREFIX = f"{MANAGER_PREFIX}task_recurrence:"
MANAGER_TASK_WEEKDAY_PREFIX = f"{MANAGER_PREFIX}task_weekday:"

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
    )


def _get_manager_user(telegram_id: int) -> dict | None:
    return store.get_user_by_telegram_and_role(telegram_id, "manager")


def manager_menu_markup() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("Add Role", callback_data=MANAGER_ADD_ROLE)],
        [InlineKeyboardButton("Add Task", callback_data=MANAGER_ADD_TASK)],
        [InlineKeyboardButton("Fire Worker", callback_data=MANAGER_FIRE_WORKER)],
        [InlineKeyboardButton("Reports", callback_data=f"{REPORT_ROLE_PREFIX}all")],
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


async def manager_verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return
    if not _can_view_reports(query.from_user.id):
        await query.answer("Not allowed.", show_alert=True)
        return
    await query.answer()

    data = query.data
    run_id = data.split(":", maxsplit=1)[1]
    run = store.get_task_run(run_id)
    if not run:
        await query.edit_message_text("Task run not found.")
        return

    if data.startswith(VERIFY_PREFIX):
        store.update_task_run(
            run_id,
            {
                "status": "manager_verified",
                "manager_status": "verified",
                "verified_at": datetime.utcnow().replace(microsecond=0).isoformat(),
            },
        )
        await query.edit_message_text("Verified. Task completion is now recorded.")
        return

    if data.startswith(REJECT_PREFIX):
        store.update_task_run(
            run_id,
            {
                "status": "manager_rejected",
                "manager_status": "rejected",
                "verified_at": datetime.utcnow().replace(microsecond=0).isoformat(),
            },
        )
        await query.edit_message_text("Rejected.")
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
            "Select worker to fire:",
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

    if data.startswith(MANAGER_FIRE_WORKER_PREFIX):
        worker_id = data.replace(MANAGER_FIRE_WORKER_PREFIX, "", 1)
        worker = store.get_user_by_id(worker_id)
        if not worker or worker.get("role") != "worker":
            await query.edit_message_text("Worker not found.")
            return

        context.user_data["manager_state"] = "awaiting_fire_reason"
        context.user_data["fire_worker_id"] = worker_id
        await query.edit_message_text(
            f"Send the reason for firing {worker['name']} ({worker['worker_role']})."
        )
        return


def _valid_hhmm(value: str) -> bool:
    try:
        hour, minute = value.split(":")
        time(int(hour), int(minute))
        return True
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

    if state == "awaiting_task_time":
        if not _valid_hhmm(text):
            await update.message.reply_text("Invalid time format. Send as HH:MM.")
            return

        draft = context.user_data.get("manager_task_draft", {})
        try:
            task = store.add_task(
                title=draft["title"],
                description=draft["description"],
                worker_role=draft["worker_role"],
                manager_id=manager["id"],
                time_hhmm=text,
                recurrence=draft.get("recurrence", "daily"),
                weekday=draft.get("weekday"),
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
                "You have been fired.\n"
                f"Role: {firing['worker_role']}\n"
                f"Reason: {firing['reason']}\n\n"
                "You are now logged out from this worker role."
            ),
        )
        await update.message.reply_text(
            f"Worker fired and notified: {firing['worker_role']} - {firing['worker_name']}"
        )
    finally:
        context.user_data.pop("manager_state", None)
        context.user_data.pop("fire_worker_id", None)


async def report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not _can_view_reports(update.effective_user.id):
        await update.message.reply_text("Only managers/admin can view reports.")
        return

    roles = store.list_roles()
    role_buttons = [[InlineKeyboardButton("All", callback_data=f"{REPORT_ROLE_PREFIX}all")]]
    for role in roles:
        role_buttons.append(
            [InlineKeyboardButton(role, callback_data=f"{REPORT_ROLE_PREFIX}{role}")]
        )
    await update.message.reply_text(
        "Select role:",
        reply_markup=InlineKeyboardMarkup(role_buttons),
    )


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

        runs = store.get_runs_for_report(worker_role=worker_role, period=period)
        stats = store.summarize_runs(runs)
        completion_rate = (
            int((stats["verified"] / stats["total"]) * 100) if stats["total"] else 0
        )
        role_label = "All" if role == "all" else role
        report_text = (
            f"Role: {role_label}\n"
            f"Total assigned: {stats['total']}\n"
            f"Completed (verified): {stats['verified']}\n"
            f"Not completed: {stats['not_completed']}\n"
            f"Rejected by manager: {stats['rejected']}\n"
            f"Extended: {stats['extended']}\n"
            f"Completion rate: {completion_rate}%"
        )
        await query.edit_message_text(report_text)
