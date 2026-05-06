from datetime import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import scheduler
import store

ADMIN_PREFIX = "admin:"
ADMIN_ADD_ROLE = f"{ADMIN_PREFIX}add_role"
ADMIN_REMOVE_ROLE = f"{ADMIN_PREFIX}remove_role"
ADMIN_ADD_MANAGER = f"{ADMIN_PREFIX}add_manager"
ADMIN_ADD_TASK = f"{ADMIN_PREFIX}add_task"
ADMIN_REPORT = f"{ADMIN_PREFIX}report"
ADMIN_TESTMODE = f"{ADMIN_PREFIX}testmode"
ADMIN_RESET = f"{ADMIN_PREFIX}reset"
ADMIN_RESET_CONFIRM = f"{ADMIN_PREFIX}reset_confirm"
ADMIN_RESET_CANCEL = f"{ADMIN_PREFIX}reset_cancel"
ADMIN_REMOVE_ROLE_PREFIX = f"{ADMIN_PREFIX}remove_role:"
ADMIN_TASK_ROLE_PREFIX = f"{ADMIN_PREFIX}task_role:"
ADMIN_TASK_MANAGER_PREFIX = f"{ADMIN_PREFIX}task_manager:"


def _is_admin(telegram_id: int) -> bool:
    return store.telegram_has_role(telegram_id, "admin")


def _panel_markup() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("Add Role", callback_data=ADMIN_ADD_ROLE)],
        [InlineKeyboardButton("Remove Role", callback_data=ADMIN_REMOVE_ROLE)],
        [InlineKeyboardButton("Add Manager", callback_data=ADMIN_ADD_MANAGER)],
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
        context.user_data["admin_state"] = "awaiting_task_time"
        await query.edit_message_text("Send task time in 24h format HH:MM (example 10:30).")
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
        try:
            store.add_role(text)
            await update.message.reply_text(f"Role added: {text}")
        except ValueError as exc:
            await update.message.reply_text(f"Failed: {exc}")
        context.user_data.pop("admin_state", None)
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
        tg_id = context.user_data.pop("manager_telegram_id", None)
        try:
            store.add_user(
                telegram_id=tg_id,
                name=text,
                system_role="manager",
                worker_role=None,
            )
            await update.message.reply_text("Manager added.")
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

    if state == "awaiting_task_time":
        if not _valid_hhmm(text):
            await update.message.reply_text("Invalid time format. Send as HH:MM.")
            return
        draft = context.user_data.get("task_draft", {})
        draft["time"] = text
        try:
            task = store.add_task(
                title=draft["title"],
                description=draft["description"],
                worker_role=draft["worker_role"],
                manager_id=draft["manager_id"],
                time_hhmm=draft["time"],
                recurrence="daily",
            )
            scheduler.schedule_task_job(context.application, task)
            await update.message.reply_text("Task added and scheduled.")
        except ValueError as exc:
            await update.message.reply_text(f"Failed to add task: {exc}")
        finally:
            context.user_data.pop("task_draft", None)
            context.user_data.pop("admin_state", None)
