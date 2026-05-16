from datetime import datetime, time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import scheduler
import store

ADMIN_PREFIX = "admin:"
ADMIN_ADD_ROLE = f"{ADMIN_PREFIX}add_role"
ADMIN_REMOVE_ROLE = f"{ADMIN_PREFIX}remove_role"
ADMIN_ADD_MANAGER = f"{ADMIN_PREFIX}add_manager"
ADMIN_LIST_MANAGERS = f"{ADMIN_PREFIX}list_managers"
ADMIN_REMOVE_MANAGER = f"{ADMIN_PREFIX}remove_manager"
ADMIN_EDIT_MANAGER_PASSWORD_PREFIX = f"{ADMIN_PREFIX}edit_manager_password:"
ADMIN_ADD_TASK = f"{ADMIN_PREFIX}add_task"
ADMIN_REPORT = f"{ADMIN_PREFIX}report"
ADMIN_TESTMODE = f"{ADMIN_PREFIX}testmode"
ADMIN_RESET = f"{ADMIN_PREFIX}reset"
ADMIN_RESET_CONFIRM = f"{ADMIN_PREFIX}reset_confirm"
ADMIN_RESET_CANCEL = f"{ADMIN_PREFIX}reset_cancel"
ADMIN_REMOVE_ROLE_PREFIX = f"{ADMIN_PREFIX}remove_role:"
ADMIN_ROLE_MANAGER_PREFIX = f"{ADMIN_PREFIX}role_manager:"
ADMIN_REMOVE_MANAGER_PREFIX = f"{ADMIN_PREFIX}remove_manager:"
ADMIN_REMOVE_MANAGER_CONFIRM_PREFIX = f"{ADMIN_PREFIX}remove_manager_confirm:"
ADMIN_TASK_ROLE_PREFIX = f"{ADMIN_PREFIX}task_role:"
ADMIN_TASK_MANAGER_PREFIX = f"{ADMIN_PREFIX}task_manager:"
ADMIN_TASK_RECURRENCE_PREFIX = f"{ADMIN_PREFIX}task_recurrence:"
ADMIN_TASK_WEEKDAY_PREFIX = f"{ADMIN_PREFIX}task_weekday:"

WEEKDAYS = [
    ("Monday", 0),
    ("Tuesday", 1),
    ("Wednesday", 2),
    ("Thursday", 3),
    ("Friday", 4),
    ("Saturday", 5),
    ("Sunday", 6),
]


def _is_admin(telegram_id: int) -> bool:
    return store.telegram_has_role(telegram_id, "admin")


def _panel_markup() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("Add Role", callback_data=ADMIN_ADD_ROLE)],
        [InlineKeyboardButton("Remove Role", callback_data=ADMIN_REMOVE_ROLE)],
        [InlineKeyboardButton("Add Manager", callback_data=ADMIN_ADD_MANAGER)],
        [InlineKeyboardButton("List Managers", callback_data=ADMIN_LIST_MANAGERS)],
        [InlineKeyboardButton("Remove Manager", callback_data=ADMIN_REMOVE_MANAGER)],
        [InlineKeyboardButton("Add Task", callback_data=ADMIN_ADD_TASK)],
        [InlineKeyboardButton("Reports", callback_data=ADMIN_REPORT)],
        [InlineKeyboardButton("Toggle Test Mode", callback_data=ADMIN_TESTMODE)],
        [InlineKeyboardButton("Reset Workers & Managers", callback_data=ADMIN_RESET)],
    ]
    return InlineKeyboardMarkup(keyboard)


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Only admin can use this command.")
        return

    await update.message.reply_text("Admin panel:", reply_markup=_panel_markup())


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return
    if not _is_admin(query.from_user.id):
        await query.answer("Only admin can do this.", show_alert=True)
        return

    await query.answer()
    data = query.data

    if data == ADMIN_ADD_ROLE:
        context.user_data["admin_state"] = "awaiting_role_name"
        await query.edit_message_text("Send the new role name (e.g., Gardener).")
        return

    if data.startswith(ADMIN_ROLE_MANAGER_PREFIX):
        manager_id = data.replace(ADMIN_ROLE_MANAGER_PREFIX, "", 1)
        role_name = context.user_data.pop("pending_role_name", None)
        context.user_data.pop("admin_state", None)
        if not role_name:
            await query.edit_message_text("Role name missing. Start again from Add Role.")
            return
        manager = store.get_user_by_id(manager_id)
        if not manager or manager.get("role") != "manager":
            await query.edit_message_text("Manager not found.")
            return
        try:
            store.add_role(role_name, manager_id=manager_id)
            await query.edit_message_text(
                f"Role added: {role_name}\nManager: {manager['name']}"
            )
        except ValueError as exc:
            await query.edit_message_text(f"Failed: {exc}")
        return

    if data == ADMIN_REMOVE_ROLE:
        roles = store.list_roles()
        if not roles:
            await query.edit_message_text("No roles available.")
            return
        keyboard = [
            [InlineKeyboardButton(role, callback_data=f"{ADMIN_REMOVE_ROLE_PREFIX}{role}")]
            for role in roles
        ]
        await query.edit_message_text(
            "Select a role to remove:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith(ADMIN_REMOVE_ROLE_PREFIX):
        role = data.replace(ADMIN_REMOVE_ROLE_PREFIX, "", 1)
        try:
            store.remove_role(role)
            await query.edit_message_text(f"Role removed: {role}")
        except ValueError as exc:
            await query.edit_message_text(f"Cannot remove role: {exc}")
        return

    if data == ADMIN_ADD_MANAGER:
        context.user_data["admin_state"] = "awaiting_manager_telegram_id"
        await query.edit_message_text("Send manager Telegram ID.")
        return

    if data == ADMIN_LIST_MANAGERS:
        managers = store.list_users_by_role("manager")
        if not managers:
            await query.edit_message_text("No active managers available.")
            return
        manager_lines = []
        keyboard = []
        for idx, manager in enumerate(managers, start=1):
            password_status = "set" if manager.get("manager_password") else "not set"
            manager_lines.append(
                f"{idx}. {manager['name']} ({manager['telegram_id']}) - Password: {password_status}"
            )
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"Edit password - {manager['name']}",
                        callback_data=f"{ADMIN_EDIT_MANAGER_PASSWORD_PREFIX}{manager['id']}",
                    )
                ]
            )

        await query.edit_message_text(
            "Active managers:\n"
            + "\n".join(manager_lines)
            + "\n\nSelect a manager below to set/update password:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith(ADMIN_EDIT_MANAGER_PASSWORD_PREFIX):
        manager_id = data.replace(ADMIN_EDIT_MANAGER_PASSWORD_PREFIX, "", 1)
        manager = store.get_user_by_id(manager_id)
        if not manager or manager.get("role") != "manager":
            await query.edit_message_text("Manager not found.")
            return
        context.user_data["admin_state"] = "awaiting_manager_password_update"
        context.user_data["password_manager_id"] = manager_id
        await query.edit_message_text(
            f"Send new registration password for manager {manager['name']}."
        )
        return

    if data == ADMIN_REMOVE_MANAGER:
        managers = store.list_users_by_role("manager")
        if not managers:
            await query.edit_message_text("No active managers available.")
            return
        manager_lines = [
            f"{idx}. {manager['name']} ({manager['telegram_id']})"
            for idx, manager in enumerate(managers, start=1)
        ]
        keyboard = [
            [
                InlineKeyboardButton(
                    f"Remove {manager['name']}",
                    callback_data=f"{ADMIN_REMOVE_MANAGER_PREFIX}{manager['id']}",
                )
            ]
            for manager in managers
        ]
        await query.edit_message_text(
            "Active managers:\n"
            + "\n".join(manager_lines)
            + "\n\nSelect a manager below to remove:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith(ADMIN_REMOVE_MANAGER_PREFIX):
        manager_id = data.replace(ADMIN_REMOVE_MANAGER_PREFIX, "", 1)
        manager = store.get_user_by_id(manager_id)
        if not manager or manager.get("role") != "manager":
            await query.edit_message_text("Manager not found.")
            return
        keyboard = [
            [
                InlineKeyboardButton(
                    "Confirm Remove",
                    callback_data=f"{ADMIN_REMOVE_MANAGER_CONFIRM_PREFIX}{manager_id}",
                )
            ],
            [InlineKeyboardButton("Cancel", callback_data=ADMIN_RESET_CANCEL)],
        ]
        await query.edit_message_text(
            f"Remove manager {manager['name']}?\n"
            "All workers and active tasks under this manager will be removed.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith(ADMIN_REMOVE_MANAGER_CONFIRM_PREFIX):
        manager_id = data.replace(ADMIN_REMOVE_MANAGER_CONFIRM_PREFIX, "", 1)
        try:
            removal = store.remove_manager(manager_id)
        except ValueError as exc:
            await query.edit_message_text(f"Failed to remove manager: {exc}")
            return

        scheduler.clear_all_task_jobs(context.application)
        scheduler.register_all_jobs(context.application)

        for worker in removal["removed_workers"]:
            try:
                await context.bot.send_message(
                    chat_id=worker["telegram_id"],
                    text=(
                        "Your manager has been removed.\n"
                        f"Role: {worker.get('worker_role')}\n"
                        "You have been logged out from this worker role."
                    ),
                )
            except Exception:
                pass

        await query.edit_message_text(
            f"Manager removed: {removal['manager']['name']}\n"
            f"Workers removed: {len(removal['removed_workers'])}\n"
            f"Roles removed: {len(removal['removed_roles'])}\n"
            f"Tasks disabled: {removal['disabled_tasks']}"
        )
        return

    if data == ADMIN_ADD_TASK:
        managers = store.list_users_by_role("manager")
        roles = store.list_roles()
        if not managers:
            await query.edit_message_text("Add at least one manager before creating tasks.")
            return
        if not roles:
            await query.edit_message_text("Add at least one role before creating tasks.")
            return
        context.user_data["admin_state"] = "awaiting_task_title"
        context.user_data["task_draft"] = {}
        await query.edit_message_text("Send task title.")
        return

    if data.startswith(ADMIN_TASK_ROLE_PREFIX):
        role = data.replace(ADMIN_TASK_ROLE_PREFIX, "", 1)
        draft = context.user_data.get("task_draft", {})
        draft["worker_role"] = role
        context.user_data["task_draft"] = draft
        managers = store.list_users_by_role("manager")
        keyboard = [
            [
                InlineKeyboardButton(
                    f"{manager['name']} ({manager['telegram_id']})",
                    callback_data=f"{ADMIN_TASK_MANAGER_PREFIX}{manager['id']}",
                )
            ]
            for manager in managers
        ]
        await query.edit_message_text(
            "Select manager for this task:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith(ADMIN_TASK_MANAGER_PREFIX):
        manager_id = data.replace(ADMIN_TASK_MANAGER_PREFIX, "", 1)
        draft = context.user_data.get("task_draft", {})
        draft["manager_id"] = manager_id
        context.user_data["task_draft"] = draft
        keyboard = [
            [
                InlineKeyboardButton("Once", callback_data=f"{ADMIN_TASK_RECURRENCE_PREFIX}once"),
                InlineKeyboardButton("Daily", callback_data=f"{ADMIN_TASK_RECURRENCE_PREFIX}daily"),
            ],
            [
                InlineKeyboardButton("Weekly", callback_data=f"{ADMIN_TASK_RECURRENCE_PREFIX}weekly"),
            ],
        ]
        await query.edit_message_text(
            "Select repeat option:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith(ADMIN_TASK_RECURRENCE_PREFIX):
        recurrence = data.replace(ADMIN_TASK_RECURRENCE_PREFIX, "", 1)
        draft = context.user_data.get("task_draft", {})
        draft["recurrence"] = recurrence
        context.user_data["task_draft"] = draft
        if recurrence == "once":
            context.user_data["admin_state"] = "awaiting_task_date"
            await query.edit_message_text(
                "Send task date in YYYY-MM-DD format (example 2026-05-20)."
            )
            return
        if recurrence == "weekly":
            keyboard = [
                [
                    InlineKeyboardButton(
                        label,
                        callback_data=f"{ADMIN_TASK_WEEKDAY_PREFIX}{weekday}",
                    )
                ]
                for label, weekday in WEEKDAYS
            ]
            await query.edit_message_text(
                "Select weekly day:",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        context.user_data["admin_state"] = "awaiting_task_time"
        await query.edit_message_text(
            "Send task time in 24h format HH:MM (example 10:30)."
        )
        return

    if data.startswith(ADMIN_TASK_WEEKDAY_PREFIX):
        weekday = int(data.replace(ADMIN_TASK_WEEKDAY_PREFIX, "", 1))
        draft = context.user_data.get("task_draft", {})
        draft["weekday"] = weekday
        context.user_data["task_draft"] = draft
        context.user_data["admin_state"] = "awaiting_task_time"
        await query.edit_message_text(
            "Send task time in 24h format HH:MM (example 10:30)."
        )
        return

    if data == ADMIN_REPORT:
        await query.edit_message_text("Use /report to generate reports.")
        return

    if data == ADMIN_TESTMODE:
        settings = store.get_settings()
        enabled = not settings.get("test_mode", False)
        telegram_id = query.from_user.id if enabled else None
        store.set_test_mode(enabled, telegram_id)
        if enabled:
            remapped_workers = store.map_all_workers_to_telegram(query.from_user.id)
            await query.edit_message_text(
                f"Test mode enabled.\n"
                f"All workers are mapped to your Telegram ID.\n"
                f"Workers remapped: {remapped_workers}"
            )
        else:
            await query.edit_message_text("Test mode disabled.")
        return

    if data == ADMIN_RESET:
        markup = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Confirm Reset", callback_data=ADMIN_RESET_CONFIRM)],
                [InlineKeyboardButton("Cancel", callback_data=ADMIN_RESET_CANCEL)],
            ]
        )
        await query.edit_message_text(
            "This clears workers, managers, tasks, and task history. Continue?",
            reply_markup=markup,
        )
        return

    if data == ADMIN_RESET_CONFIRM:
        store.reset_all()
        scheduler.clear_all_task_jobs(context.application)
        await query.edit_message_text("System reset complete.")
        return

    if data == ADMIN_RESET_CANCEL:
        await query.edit_message_text("Reset cancelled.")
        return


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


async def admin_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not _is_admin(update.effective_user.id):
        return

    state = context.user_data.get("admin_state")
    if not state:
        return

    text = update.message.text.strip()

    if state == "awaiting_role_name":
        managers = store.list_users_by_role("manager")
        if not managers:
            await update.message.reply_text("Add at least one manager before creating roles.")
            context.user_data.pop("admin_state", None)
            return

        context.user_data["pending_role_name"] = text
        keyboard = [
            [
                InlineKeyboardButton(
                    f"{manager['name']} ({manager['telegram_id']})",
                    callback_data=f"{ADMIN_ROLE_MANAGER_PREFIX}{manager['id']}",
                )
            ]
            for manager in managers
        ]
        await update.message.reply_text(
            f"Role: {text}\nSelect manager for this role:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if state == "awaiting_manager_telegram_id":
        if not text.isdigit():
            await update.message.reply_text("Telegram ID must be numeric. Send again.")
            return
        context.user_data["manager_telegram_id"] = int(text)
        context.user_data["admin_state"] = "awaiting_manager_name"
        await update.message.reply_text("Now send manager name.")
        return

    if state == "awaiting_manager_name":
        context.user_data["manager_name"] = text
        context.user_data["admin_state"] = "awaiting_manager_password"
        await update.message.reply_text("Now send a registration password for this manager.")
        return

    if state == "awaiting_manager_password":
        tg_id = context.user_data.pop("manager_telegram_id", None)
        manager_name = context.user_data.pop("manager_name", None)
        try:
            store.add_user(
                telegram_id=tg_id,
                name=manager_name,
                system_role="manager",
                worker_role=None,
                manager_password=text,
            )
            await update.message.reply_text("Manager added with registration password.")
        except ValueError as exc:
            await update.message.reply_text(f"Failed: {exc}")
        context.user_data.pop("admin_state", None)
        return

    if state == "awaiting_manager_password_update":
        manager_id = context.user_data.pop("password_manager_id", None)
        try:
            manager = store.update_manager_password(manager_id, text)
            await update.message.reply_text(
                f"Password updated for manager {manager['name']}."
            )
        except ValueError as exc:
            await update.message.reply_text(f"Failed: {exc}")
        context.user_data.pop("admin_state", None)
        return

    if state == "awaiting_task_title":
        draft = context.user_data.get("task_draft", {})
        draft["title"] = text
        context.user_data["task_draft"] = draft
        context.user_data["admin_state"] = "awaiting_task_description"
        await update.message.reply_text("Send task description.")
        return

    if state == "awaiting_task_description":
        draft = context.user_data.get("task_draft", {})
        draft["description"] = text
        context.user_data["task_draft"] = draft
        context.user_data["admin_state"] = "awaiting_task_role"
        roles = store.list_roles()
        keyboard = [
            [InlineKeyboardButton(role, callback_data=f"{ADMIN_TASK_ROLE_PREFIX}{role}")]
            for role in roles
        ]
        await update.message.reply_text(
            "Select role for this task:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if state == "awaiting_task_date":
        if not _valid_yyyy_mm_dd(text):
            await update.message.reply_text("Invalid date format. Send as YYYY-MM-DD.")
            return
        draft = context.user_data.get("task_draft", {})
        draft["scheduled_date"] = text
        context.user_data["task_draft"] = draft
        context.user_data["admin_state"] = "awaiting_task_time"
        await update.message.reply_text(
            "Send task time in 24h format HH:MM (example 10:30)."
        )
        return

    if state == "awaiting_task_time":
        if not _valid_hhmm(text):
            await update.message.reply_text("Invalid time format. Send as HH:MM.")
            return
        draft = context.user_data.get("task_draft", {})
        if draft.get("recurrence") == "once" and draft.get("scheduled_date"):
            if not _once_schedule_is_future(draft["scheduled_date"], text):
                await update.message.reply_text(
                    "The selected date/time is in the past. Send a future time."
                )
                return
        draft["time"] = text
        try:
            task = store.add_task(
                title=draft["title"],
                description=draft["description"],
                worker_role=draft["worker_role"],
                manager_id=draft["manager_id"],
                time_hhmm=draft["time"],
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
            context.user_data.pop("task_draft", None)
            context.user_data.pop("admin_state", None)
