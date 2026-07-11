from datetime import datetime, time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import scheduler
import store
from handlers.manager import _send_report_role_choices

ADMIN_PREFIX = "admin:"
ADMIN_ADD_ROLE = f"{ADMIN_PREFIX}add_role"
ADMIN_REMOVE_ROLE = f"{ADMIN_PREFIX}remove_role"
ADMIN_ADD_MANAGER = f"{ADMIN_PREFIX}add_manager"
ADMIN_ADD_OWNER = f"{ADMIN_PREFIX}add_owner"
ADMIN_LIST_OWNERS = f"{ADMIN_PREFIX}list_owners"
ADMIN_LIST_MANAGERS = f"{ADMIN_PREFIX}list_managers"
ADMIN_REMOVE_MANAGER = f"{ADMIN_PREFIX}remove_manager"
ADMIN_EDIT_MANAGER_MENU_PREFIX = f"{ADMIN_PREFIX}edit_manager_menu:"
ADMIN_EDIT_MANAGER_NAME_PREFIX = f"{ADMIN_PREFIX}edit_manager_name:"
ADMIN_EDIT_MANAGER_TGID_PREFIX = f"{ADMIN_PREFIX}edit_manager_tgid:"
ADMIN_EDIT_MANAGER_PASSWORD_PREFIX = f"{ADMIN_PREFIX}edit_manager_password:"
ADMIN_EDIT_OWNER_MENU_PREFIX = f"{ADMIN_PREFIX}edit_owner_menu:"
ADMIN_EDIT_OWNER_NAME_PREFIX = f"{ADMIN_PREFIX}edit_owner_name:"
ADMIN_EDIT_OWNER_TGID_PREFIX = f"{ADMIN_PREFIX}edit_owner_tgid:"
ADMIN_REMOVE_OWNER_PREFIX = f"{ADMIN_PREFIX}remove_owner:"
ADMIN_REMOVE_OWNER_CONFIRM_PREFIX = f"{ADMIN_PREFIX}remove_owner_confirm:"
ADMIN_ADD_TASK = f"{ADMIN_PREFIX}add_task"
ADMIN_LIST_TASKS = f"{ADMIN_PREFIX}list_tasks"
ADMIN_EDIT_TASK_MENU_PREFIX = f"{ADMIN_PREFIX}edit_task_menu:"
ADMIN_EDIT_TASK_TITLE_PREFIX = f"{ADMIN_PREFIX}edit_task_title:"
ADMIN_EDIT_TASK_DESCRIPTION_PREFIX = f"{ADMIN_PREFIX}edit_task_description:"
ADMIN_EDIT_TASK_TIME_PREFIX = f"{ADMIN_PREFIX}edit_task_time:"
ADMIN_TOGGLE_TASK_PENALTY_PREFIX = f"{ADMIN_PREFIX}toggle_task_penalty:"
ADMIN_REPORT = f"{ADMIN_PREFIX}report"
ADMIN_TESTMODE = f"{ADMIN_PREFIX}testmode"
ADMIN_RESET = f"{ADMIN_PREFIX}reset"
ADMIN_RESET_CONFIRM = f"{ADMIN_PREFIX}reset_confirm"
ADMIN_RESET_CANCEL = f"{ADMIN_PREFIX}reset_cancel"
ADMIN_REMOVE_ROLE_PREFIX = f"{ADMIN_PREFIX}remove_role:"
ADMIN_ROLE_MANAGER_PREFIX = f"{ADMIN_PREFIX}role_manager:"
ADMIN_REMOVE_MANAGER_PREFIX = f"{ADMIN_PREFIX}remove_manager:"
ADMIN_REMOVE_MANAGER_CONFIRM_PREFIX = f"{ADMIN_PREFIX}remove_manager_confirm:"
ADMIN_OWNER_MANAGER_PREFIX = f"{ADMIN_PREFIX}owner_manager:"
ADMIN_TASK_ROLE_PREFIX = f"{ADMIN_PREFIX}task_role:"
ADMIN_TASK_MANAGER_PREFIX = f"{ADMIN_PREFIX}task_manager:"
ADMIN_TASK_RECURRENCE_PREFIX = f"{ADMIN_PREFIX}task_recurrence:"
ADMIN_TASK_WEEKDAY_PREFIX = f"{ADMIN_PREFIX}task_weekday:"
ADMIN_TASK_PARENT_PREFIX = f"{ADMIN_PREFIX}task_parent:"
ADMIN_TASK_PENALTY_PREFIX = f"{ADMIN_PREFIX}task_penalty:"
ADMIN_TASK_VERIFIER_PREFIX = f"{ADMIN_PREFIX}task_verifier:"
ADMIN_EDIT_TASK_VERIFIER_PREFIX = f"{ADMIN_PREFIX}edit_task_verifier:"
ADMIN_SET_TASK_VERIFIER_PREFIX = f"{ADMIN_PREFIX}set_task_verifier:"
ADMIN_TERMINATE_STAFF = f"{ADMIN_PREFIX}terminate_staff"
ADMIN_TERMINATE_STAFF_PREFIX = f"{ADMIN_PREFIX}terminate_staff:"
ADMIN_TERMINATE_CONFIRM_PREFIX = f"{ADMIN_PREFIX}terminate_confirm:"

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
        [InlineKeyboardButton("Add Owner", callback_data=ADMIN_ADD_OWNER)],
        [InlineKeyboardButton("List Owners", callback_data=ADMIN_LIST_OWNERS)],
        [InlineKeyboardButton("List / Edit Managers", callback_data=ADMIN_LIST_MANAGERS)],
        [InlineKeyboardButton("Remove Manager", callback_data=ADMIN_REMOVE_MANAGER)],
        [InlineKeyboardButton("Terminate Staff", callback_data=ADMIN_TERMINATE_STAFF)],
        [InlineKeyboardButton("Add Task", callback_data=ADMIN_ADD_TASK)],
        [InlineKeyboardButton("List / Edit Tasks", callback_data=ADMIN_LIST_TASKS)],
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


def _format_admin_task_row(index: int, task: dict) -> str:
    recurrence = task.get("recurrence", "daily")
    if recurrence == "after_task":
        time_text = "After parent verification"
    else:
        time_text = task["time"]
    penalty_text = "No deduction on rejection" if task.get("no_penalty") else "Normal points"
    verifier_text = task.get("verifier_name") or "Task manager"
    return (
        f"{index}. {task['title']}\n"
        f"   Description: {task.get('description') or 'No description'}\n"
        f"   Manager: {task.get('manager_name', 'Unknown')}\n"
        f"   Verifier: {verifier_text}\n"
        f"   Worker Role: {task['worker_role']}\n"
        f"   Worker: {task.get('worker_name', 'Unassigned')}\n"
        f"   Time: {time_text}\n"
        f"   Repeat: {recurrence}\n"
        f"   Points: {penalty_text}"
    )


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

    if data == ADMIN_ADD_OWNER:
        managers = store.list_users_by_role("manager")
        if not managers:
            await query.edit_message_text("Add at least one manager before creating an owner.")
            return
        context.user_data["admin_state"] = "awaiting_owner_telegram_id"
        await query.edit_message_text("Send owner Telegram ID.")
        return

    if data == ADMIN_LIST_OWNERS:
        owners = store.list_users_by_role("owner")
        if not owners:
            await query.edit_message_text("No active owners available.")
            return

        owner_lines = []
        keyboard = []
        for idx, owner in enumerate(owners, start=1):
            managers = store.list_managers_for_owner(owner["id"])
            manager_names = (
                ", ".join(manager["name"] for manager in managers)
                if managers
                else "No managers assigned"
            )
            owner_lines.append(
                f"{idx}. {owner['name']} ({owner['telegram_id']})\n"
                f"   Managers: {manager_names}"
            )
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"Edit {owner['name']}",
                        callback_data=f"{ADMIN_EDIT_OWNER_MENU_PREFIX}{owner['id']}",
                    ),
                    InlineKeyboardButton(
                        f"Remove {owner['name']}",
                        callback_data=f"{ADMIN_REMOVE_OWNER_PREFIX}{owner['id']}",
                    ),
                ]
            )

        await query.edit_message_text(
            "Active owners:\n\n"
            + "\n\n".join(owner_lines)
            + "\n\nSelect an owner below to edit or remove:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
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
            owner = (
                store.get_user_by_id(manager["owner_id"])
                if manager.get("owner_id")
                else None
            )
            owner_status = owner["name"] if owner else "not assigned"
            manager_lines.append(
                f"{idx}. {manager['name']} ({manager['telegram_id']}) - "
                f"Password: {password_status} - Owner: {owner_status}"
            )
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"Edit {manager['name']}",
                        callback_data=f"{ADMIN_EDIT_MANAGER_MENU_PREFIX}{manager['id']}",
                    )
                ]
            )

        await query.edit_message_text(
            "Active managers:\n"
            + "\n".join(manager_lines)
            + "\n\nSelect a manager below to edit:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith(ADMIN_EDIT_MANAGER_MENU_PREFIX):
        manager_id = data.replace(ADMIN_EDIT_MANAGER_MENU_PREFIX, "", 1)
        manager = store.get_user_by_id(manager_id)
        if not manager or manager.get("role") != "manager":
            await query.edit_message_text("Manager not found.")
            return
        keyboard = [
            [
                InlineKeyboardButton(
                    "Edit name",
                    callback_data=f"{ADMIN_EDIT_MANAGER_NAME_PREFIX}{manager_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "Edit Telegram ID",
                    callback_data=f"{ADMIN_EDIT_MANAGER_TGID_PREFIX}{manager_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "Edit password",
                    callback_data=f"{ADMIN_EDIT_MANAGER_PASSWORD_PREFIX}{manager_id}",
                )
            ],
            [InlineKeyboardButton("Back to managers", callback_data=ADMIN_LIST_MANAGERS)],
        ]
        await query.edit_message_text(
            f"Edit manager: {manager['name']}\n"
            f"Telegram ID: {manager['telegram_id']}\n"
            f"Password: {'set' if manager.get('manager_password') else 'not set'}",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith(ADMIN_EDIT_MANAGER_NAME_PREFIX):
        manager_id = data.replace(ADMIN_EDIT_MANAGER_NAME_PREFIX, "", 1)
        manager = store.get_user_by_id(manager_id)
        if not manager or manager.get("role") != "manager":
            await query.edit_message_text("Manager not found.")
            return
        context.user_data["admin_state"] = "awaiting_edit_manager_name"
        context.user_data["edit_manager_id"] = manager_id
        await query.edit_message_text(
            f"Send new name for manager {manager['name']}."
        )
        return

    if data.startswith(ADMIN_EDIT_MANAGER_TGID_PREFIX):
        manager_id = data.replace(ADMIN_EDIT_MANAGER_TGID_PREFIX, "", 1)
        manager = store.get_user_by_id(manager_id)
        if not manager or manager.get("role") != "manager":
            await query.edit_message_text("Manager not found.")
            return
        context.user_data["admin_state"] = "awaiting_edit_manager_telegram_id"
        context.user_data["edit_manager_id"] = manager_id
        await query.edit_message_text(
            f"Send new Telegram ID for manager {manager['name']}."
        )
        return

    if data.startswith(ADMIN_EDIT_MANAGER_PASSWORD_PREFIX):
        manager_id = data.replace(ADMIN_EDIT_MANAGER_PASSWORD_PREFIX, "", 1)
        manager = store.get_user_by_id(manager_id)
        if not manager or manager.get("role") != "manager":
            await query.edit_message_text("Manager not found.")
            return
        context.user_data["admin_state"] = "awaiting_manager_password_update"
        context.user_data["edit_manager_id"] = manager_id
        await query.edit_message_text(
            f"Send new registration password for manager {manager['name']}."
        )
        return

    if data.startswith(ADMIN_EDIT_OWNER_MENU_PREFIX):
        owner_id = data.replace(ADMIN_EDIT_OWNER_MENU_PREFIX, "", 1)
        owner = store.get_user_by_id(owner_id)
        if not owner or owner.get("role") != "owner":
            await query.edit_message_text("Owner not found.")
            return
        keyboard = [
            [
                InlineKeyboardButton(
                    "Edit name",
                    callback_data=f"{ADMIN_EDIT_OWNER_NAME_PREFIX}{owner_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "Edit Telegram ID",
                    callback_data=f"{ADMIN_EDIT_OWNER_TGID_PREFIX}{owner_id}",
                )
            ],
            [InlineKeyboardButton("Back to owners", callback_data=ADMIN_LIST_OWNERS)],
        ]
        await query.edit_message_text(
            f"Edit owner: {owner['name']}\nTelegram ID: {owner['telegram_id']}",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith(ADMIN_EDIT_OWNER_NAME_PREFIX):
        owner_id = data.replace(ADMIN_EDIT_OWNER_NAME_PREFIX, "", 1)
        owner = store.get_user_by_id(owner_id)
        if not owner or owner.get("role") != "owner":
            await query.edit_message_text("Owner not found.")
            return
        context.user_data["admin_state"] = "awaiting_edit_owner_name"
        context.user_data["edit_owner_id"] = owner_id
        await query.edit_message_text(f"Send new name for owner {owner['name']}.")
        return

    if data.startswith(ADMIN_EDIT_OWNER_TGID_PREFIX):
        owner_id = data.replace(ADMIN_EDIT_OWNER_TGID_PREFIX, "", 1)
        owner = store.get_user_by_id(owner_id)
        if not owner or owner.get("role") != "owner":
            await query.edit_message_text("Owner not found.")
            return
        context.user_data["admin_state"] = "awaiting_edit_owner_telegram_id"
        context.user_data["edit_owner_id"] = owner_id
        await query.edit_message_text(
            f"Send new Telegram ID for owner {owner['name']}."
        )
        return

    if data.startswith(ADMIN_REMOVE_OWNER_PREFIX):
        owner_id = data.replace(ADMIN_REMOVE_OWNER_PREFIX, "", 1)
        owner = store.get_user_by_id(owner_id)
        if not owner or owner.get("role") != "owner":
            await query.edit_message_text("Owner not found.")
            return
        keyboard = [
            [
                InlineKeyboardButton(
                    "Confirm Remove",
                    callback_data=f"{ADMIN_REMOVE_OWNER_CONFIRM_PREFIX}{owner_id}",
                )
            ],
            [InlineKeyboardButton("Cancel", callback_data=ADMIN_LIST_OWNERS)],
        ]
        await query.edit_message_text(
            f"Remove owner {owner['name']}?\n"
            "Managers under this owner will be unassigned from the owner.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith(ADMIN_REMOVE_OWNER_CONFIRM_PREFIX):
        owner_id = data.replace(ADMIN_REMOVE_OWNER_CONFIRM_PREFIX, "", 1)
        try:
            owner = store.remove_owner(owner_id)
        except ValueError as exc:
            await query.edit_message_text(f"Failed to remove owner: {exc}")
            return
        await query.edit_message_text(f"Owner removed: {owner['name']}")
        return

    if data.startswith(ADMIN_OWNER_MANAGER_PREFIX):
        manager_id = data.replace(ADMIN_OWNER_MANAGER_PREFIX, "", 1)
        tg_id = context.user_data.pop("owner_telegram_id", None)
        owner_name = context.user_data.pop("owner_name", None)
        context.user_data.pop("admin_state", None)
        if not tg_id or not owner_name:
            await query.edit_message_text("Owner details missing. Start again from Add Owner.")
            return
        try:
            owner = store.add_user(
                telegram_id=tg_id,
                name=owner_name,
                system_role="owner",
            )
            manager = store.assign_manager_to_owner(manager_id, owner["id"])
        except ValueError as exc:
            await query.edit_message_text(f"Failed: {exc}")
            return

        await query.edit_message_text(
            f"Owner added: {owner['name']}\n"
            f"Assigned manager: {manager['name']}"
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

    if data == ADMIN_TERMINATE_STAFF:
        workers = store.list_users_by_role("worker")
        if not workers:
            await query.edit_message_text("No active workers available.")
            return
        keyboard = [
            [
                InlineKeyboardButton(
                    f"{worker['worker_role']} - {worker['name']}",
                    callback_data=f"{ADMIN_TERMINATE_STAFF_PREFIX}{worker['id']}",
                )
            ]
            for worker in workers
        ]
        await query.edit_message_text(
            "Select staff to terminate (their role becomes available again):",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith(ADMIN_TERMINATE_CONFIRM_PREFIX):
        worker_id = data.replace(ADMIN_TERMINATE_CONFIRM_PREFIX, "", 1)
        try:
            worker = store.terminate_worker(worker_id)
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
            pass
        await query.edit_message_text(
            f"Staff terminated: {worker['name']} ({worker.get('worker_role')}).\n"
            "The role is now available for a new registration."
        )
        return

    if data.startswith(ADMIN_TERMINATE_STAFF_PREFIX):
        worker_id = data.replace(ADMIN_TERMINATE_STAFF_PREFIX, "", 1)
        worker = store.get_user_by_id(worker_id)
        if not worker or worker.get("role") != "worker":
            await query.edit_message_text("Worker not found.")
            return
        keyboard = [
            [
                InlineKeyboardButton(
                    "Confirm Terminate",
                    callback_data=f"{ADMIN_TERMINATE_CONFIRM_PREFIX}{worker_id}",
                )
            ],
            [InlineKeyboardButton("Cancel", callback_data=ADMIN_TERMINATE_STAFF)],
        ]
        await query.edit_message_text(
            f"Terminate {worker['name']} ({worker.get('worker_role')})?\n"
            "They will be logged out and the role becomes claimable again.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data == ADMIN_LIST_TASKS:
        tasks = store.list_tasks_for_admin()
        if not tasks:
            await query.edit_message_text("No active tasks available.")
            return
        task_lines = [
            _format_admin_task_row(index, task)
            for index, task in enumerate(tasks, start=1)
        ]
        keyboard = [
            [
                InlineKeyboardButton(
                    f"Edit {index}. {task['title'][:25]}",
                    callback_data=f"{ADMIN_EDIT_TASK_MENU_PREFIX}{task['id']}",
                )
            ]
            for index, task in enumerate(tasks, start=1)
        ]
        await query.edit_message_text(
            "Active tasks:\n\n"
            + "\n\n".join(task_lines)
            + "\n\nSelect a task below to edit:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith(ADMIN_EDIT_TASK_MENU_PREFIX):
        task_id = data.replace(ADMIN_EDIT_TASK_MENU_PREFIX, "", 1)
        task = store.get_task_by_id(task_id)
        if not task or not task.get("active", True):
            await query.edit_message_text("Task not found.")
            return
        keyboard = [
            [
                InlineKeyboardButton(
                    "Edit title",
                    callback_data=f"{ADMIN_EDIT_TASK_TITLE_PREFIX}{task_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "Edit description",
                    callback_data=f"{ADMIN_EDIT_TASK_DESCRIPTION_PREFIX}{task_id}",
                )
            ],
        ]
        if task.get("recurrence") != "after_task":
            keyboard.append(
                [
                    InlineKeyboardButton(
                        "Edit time",
                        callback_data=f"{ADMIN_EDIT_TASK_TIME_PREFIX}{task_id}",
                    )
                ]
            )
        keyboard.extend(
            [
                [
                    InlineKeyboardButton(
                        "Edit verifier",
                        callback_data=f"{ADMIN_EDIT_TASK_VERIFIER_PREFIX}{task_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "Toggle no-deduction",
                        callback_data=f"{ADMIN_TOGGLE_TASK_PENALTY_PREFIX}{task_id}",
                    )
                ],
                [InlineKeyboardButton("Back to tasks", callback_data=ADMIN_LIST_TASKS)],
            ]
        )
        penalty_text = (
            "No deduction on rejection" if task.get("no_penalty") else "Normal points"
        )
        await query.edit_message_text(
            f"Edit task: {task['title']}\n"
            f"Description: {task.get('description') or 'No description'}\n"
            f"Time: {task['time']}\n"
            f"Repeat: {task.get('recurrence', 'daily')}\n"
            f"Points: {penalty_text}",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith(ADMIN_EDIT_TASK_TITLE_PREFIX):
        task_id = data.replace(ADMIN_EDIT_TASK_TITLE_PREFIX, "", 1)
        task = store.get_task_by_id(task_id)
        if not task or not task.get("active", True):
            await query.edit_message_text("Task not found.")
            return
        context.user_data["admin_state"] = "awaiting_edit_task_title"
        context.user_data["edit_task_id"] = task_id
        await query.edit_message_text(f"Send new title for task {task['title']}.")
        return

    if data.startswith(ADMIN_EDIT_TASK_DESCRIPTION_PREFIX):
        task_id = data.replace(ADMIN_EDIT_TASK_DESCRIPTION_PREFIX, "", 1)
        task = store.get_task_by_id(task_id)
        if not task or not task.get("active", True):
            await query.edit_message_text("Task not found.")
            return
        context.user_data["admin_state"] = "awaiting_edit_task_description"
        context.user_data["edit_task_id"] = task_id
        await query.edit_message_text(f"Send new description for task {task['title']}.")
        return

    if data.startswith(ADMIN_EDIT_TASK_TIME_PREFIX):
        task_id = data.replace(ADMIN_EDIT_TASK_TIME_PREFIX, "", 1)
        task = store.get_task_by_id(task_id)
        if not task or not task.get("active", True):
            await query.edit_message_text("Task not found.")
            return
        context.user_data["admin_state"] = "awaiting_edit_task_time"
        context.user_data["edit_task_id"] = task_id
        await query.edit_message_text("Send new task time in 24h format HH:MM.")
        return

    if data.startswith(ADMIN_EDIT_TASK_VERIFIER_PREFIX):
        task_id = data.replace(ADMIN_EDIT_TASK_VERIFIER_PREFIX, "", 1)
        task = store.get_task_by_id(task_id)
        if not task or not task.get("active", True):
            await query.edit_message_text("Task not found.")
            return
        keyboard = [
            [
                InlineKeyboardButton(
                    "Same as task manager",
                    callback_data=f"{ADMIN_SET_TASK_VERIFIER_PREFIX}{task_id}:same",
                )
            ]
        ]
        for manager in store.list_users_by_role("manager"):
            if manager["id"] == task.get("manager_id"):
                continue
            keyboard.append(
                [
                    InlineKeyboardButton(
                        manager["name"],
                        callback_data=f"{ADMIN_SET_TASK_VERIFIER_PREFIX}{task_id}:{manager['id']}",
                    )
                ]
            )
        await query.edit_message_text(
            f"Select verifier for task {task['title']}:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith(ADMIN_SET_TASK_VERIFIER_PREFIX):
        payload = data.replace(ADMIN_SET_TASK_VERIFIER_PREFIX, "", 1)
        task_id, value = payload.split(":", maxsplit=1)
        verifier_id = None if value == "same" else value
        verifier_name = "Task manager"
        if verifier_id:
            verifier = store.get_user_by_id(verifier_id)
            if not verifier or verifier.get("role") != "manager":
                await query.edit_message_text("Verifier not found.")
                return
            verifier_name = verifier["name"]
        try:
            task = store.update_task(task_id, {"verifier_id": verifier_id})
        except ValueError as exc:
            await query.edit_message_text(f"Failed: {exc}")
            return
        await query.edit_message_text(
            f"Verifier updated for task {task['title']}: {verifier_name}",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Back to tasks", callback_data=ADMIN_LIST_TASKS)]]
            ),
        )
        return

    if data.startswith(ADMIN_TOGGLE_TASK_PENALTY_PREFIX):
        task_id = data.replace(ADMIN_TOGGLE_TASK_PENALTY_PREFIX, "", 1)
        task = store.get_task_by_id(task_id)
        if not task or not task.get("active", True):
            await query.edit_message_text("Task not found.")
            return
        updated = store.update_task(task_id, {"no_penalty": not task.get("no_penalty")})
        penalty_text = (
            "No deduction on rejection" if updated.get("no_penalty") else "Normal points"
        )
        await query.edit_message_text(
            f"Task point behavior updated: {updated['title']}\nPoints: {penalty_text}",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Back to tasks", callback_data=ADMIN_LIST_TASKS)]]
            ),
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

    if data.startswith(ADMIN_TASK_PENALTY_PREFIX):
        value = data.replace(ADMIN_TASK_PENALTY_PREFIX, "", 1)
        draft = context.user_data.get("task_draft", {})
        draft["no_penalty"] = value == "no_penalty"
        context.user_data["task_draft"] = draft
        roles = store.list_roles()
        if not roles:
            await query.edit_message_text("Add at least one role before creating tasks.")
            context.user_data.pop("admin_state", None)
            context.user_data.pop("task_draft", None)
            return
        keyboard = [
            [InlineKeyboardButton(role, callback_data=f"{ADMIN_TASK_ROLE_PREFIX}{role}")]
            for role in roles
        ]
        await query.edit_message_text(
            "Select role for this task:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
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
                InlineKeyboardButton(
                    "Same as task manager",
                    callback_data=f"{ADMIN_TASK_VERIFIER_PREFIX}same",
                )
            ]
        ]
        for manager in store.list_users_by_role("manager"):
            if manager["id"] == manager_id:
                continue
            keyboard.append(
                [
                    InlineKeyboardButton(
                        manager["name"],
                        callback_data=f"{ADMIN_TASK_VERIFIER_PREFIX}{manager['id']}",
                    )
                ]
            )
        await query.edit_message_text(
            "Who should verify this task when the worker responds?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data.startswith(ADMIN_TASK_VERIFIER_PREFIX):
        value = data.replace(ADMIN_TASK_VERIFIER_PREFIX, "", 1)
        draft = context.user_data.get("task_draft", {})
        draft["verifier_id"] = None if value == "same" else value
        context.user_data["task_draft"] = draft
        keyboard = [
            [
                InlineKeyboardButton("Once", callback_data=f"{ADMIN_TASK_RECURRENCE_PREFIX}once"),
                InlineKeyboardButton("Daily", callback_data=f"{ADMIN_TASK_RECURRENCE_PREFIX}daily"),
            ],
            [
                InlineKeyboardButton("Weekly", callback_data=f"{ADMIN_TASK_RECURRENCE_PREFIX}weekly"),
                InlineKeyboardButton(
                    "After Another Task",
                    callback_data=f"{ADMIN_TASK_RECURRENCE_PREFIX}after_task",
                ),
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
        if recurrence == "after_task":
            manager_id = draft.get("manager_id")
            parent_tasks = store.list_parent_task_options(manager_id=manager_id)
            if not parent_tasks:
                await query.edit_message_text(
                    "No parent tasks available for this manager. Create a normal task first."
                )
                return
            keyboard = [
                [
                    InlineKeyboardButton(
                        f"{task['title']} ({task['worker_role']})",
                        callback_data=f"{ADMIN_TASK_PARENT_PREFIX}{task['id']}",
                    )
                ]
                for task in parent_tasks
            ]
            await query.edit_message_text(
                "Select parent task (this task will fire after parent verification):",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return

        context.user_data["admin_state"] = "awaiting_task_time"
        await query.edit_message_text(
            "Send task time in 24h format HH:MM (example 10:30)."
        )
        return

    if data.startswith(ADMIN_TASK_PARENT_PREFIX):
        parent_task_id = data.replace(ADMIN_TASK_PARENT_PREFIX, "", 1)
        draft = context.user_data.get("task_draft", {})
        draft["depends_on_task_id"] = parent_task_id
        context.user_data["task_draft"] = draft
        await _create_task_from_draft(query, context)
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
        await _send_report_role_choices(query, query.from_user.id, context)
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


async def _create_task_from_draft(target, context: ContextTypes.DEFAULT_TYPE) -> None:
    draft = context.user_data.get("task_draft", {})
    try:
        task = store.add_task(
            title=draft["title"],
            description=draft["description"],
            worker_role=draft["worker_role"],
            manager_id=draft["manager_id"],
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
        context.user_data.pop("task_draft", None)
        context.user_data.pop("admin_state", None)


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

    if state == "awaiting_edit_manager_name":
        manager_id = context.user_data.pop("edit_manager_id", None)
        try:
            manager = store.update_manager(manager_id, name=text)
            await update.message.reply_text(f"Manager name updated to {manager['name']}.")
        except ValueError as exc:
            await update.message.reply_text(f"Failed: {exc}")
        context.user_data.pop("admin_state", None)
        return

    if state == "awaiting_edit_manager_telegram_id":
        if not text.isdigit():
            await update.message.reply_text("Telegram ID must be numeric. Send again.")
            return
        manager_id = context.user_data.pop("edit_manager_id", None)
        try:
            manager = store.update_manager(manager_id, telegram_id=int(text))
            await update.message.reply_text(
                f"Manager Telegram ID updated to {manager['telegram_id']}."
            )
        except ValueError as exc:
            await update.message.reply_text(f"Failed: {exc}")
        context.user_data.pop("admin_state", None)
        return

    if state == "awaiting_manager_password_update":
        manager_id = context.user_data.pop("edit_manager_id", None)
        try:
            manager = store.update_manager(manager_id, password=text)
            await update.message.reply_text(
                f"Password updated for manager {manager['name']}."
            )
        except ValueError as exc:
            await update.message.reply_text(f"Failed: {exc}")
        context.user_data.pop("admin_state", None)
        return

    if state == "awaiting_edit_owner_name":
        owner_id = context.user_data.pop("edit_owner_id", None)
        try:
            owner = store.update_owner(owner_id, name=text)
            await update.message.reply_text(f"Owner name updated to {owner['name']}.")
        except ValueError as exc:
            await update.message.reply_text(f"Failed: {exc}")
        context.user_data.pop("admin_state", None)
        return

    if state == "awaiting_edit_owner_telegram_id":
        if not text.isdigit():
            await update.message.reply_text("Telegram ID must be numeric. Send again.")
            return
        owner_id = context.user_data.pop("edit_owner_id", None)
        try:
            owner = store.update_owner(owner_id, telegram_id=int(text))
            await update.message.reply_text(
                f"Owner Telegram ID updated to {owner['telegram_id']}."
            )
        except ValueError as exc:
            await update.message.reply_text(f"Failed: {exc}")
        context.user_data.pop("admin_state", None)
        return

    if state == "awaiting_edit_task_title":
        task_id = context.user_data.pop("edit_task_id", None)
        try:
            task = store.update_task(task_id, {"title": text})
            await update.message.reply_text(f"Task title updated to {task['title']}.")
        except ValueError as exc:
            await update.message.reply_text(f"Failed: {exc}")
        context.user_data.pop("admin_state", None)
        return

    if state == "awaiting_edit_task_description":
        task_id = context.user_data.pop("edit_task_id", None)
        try:
            task = store.update_task(task_id, {"description": text})
            await update.message.reply_text(f"Task description updated for {task['title']}.")
        except ValueError as exc:
            await update.message.reply_text(f"Failed: {exc}")
        context.user_data.pop("admin_state", None)
        return

    if state == "awaiting_edit_task_time":
        if not _valid_hhmm(text):
            await update.message.reply_text("Invalid time format. Send as HH:MM.")
            return
        task_id = context.user_data.pop("edit_task_id", None)
        try:
            current_task = store.get_task_by_id(task_id)
            if (
                current_task
                and current_task.get("recurrence") == "once"
                and current_task.get("scheduled_date")
                and not _once_schedule_is_future(current_task["scheduled_date"], text)
            ):
                await update.message.reply_text(
                    "The selected date/time is in the past. Send a future time."
                )
                context.user_data["edit_task_id"] = task_id
                return
            task = store.update_task(task_id, {"time": text})
            scheduler.schedule_task_job(context.application, task)
            await update.message.reply_text(f"Task time updated to {task['time']}.")
        except ValueError as exc:
            await update.message.reply_text(f"Failed: {exc}")
        context.user_data.pop("admin_state", None)
        return

    if state == "awaiting_owner_telegram_id":
        if not text.isdigit():
            await update.message.reply_text("Telegram ID must be numeric. Send again.")
            return
        context.user_data["owner_telegram_id"] = int(text)
        context.user_data["admin_state"] = "awaiting_owner_name"
        await update.message.reply_text("Now send owner name.")
        return

    if state == "awaiting_owner_name":
        managers = store.list_users_by_role("manager")
        if not managers:
            await update.message.reply_text("No active managers available.")
            context.user_data.pop("admin_state", None)
            context.user_data.pop("owner_telegram_id", None)
            return
        context.user_data["owner_name"] = text
        keyboard = [
            [
                InlineKeyboardButton(
                    f"{manager['name']} ({manager['telegram_id']})",
                    callback_data=f"{ADMIN_OWNER_MANAGER_PREFIX}{manager['id']}",
                )
            ]
            for manager in managers
        ]
        await update.message.reply_text(
            f"Owner: {text}\nSelect manager to assign under this owner:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
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
        context.user_data["admin_state"] = "awaiting_task_penalty"
        keyboard = [
            [
                InlineKeyboardButton(
                    "Normal points",
                    callback_data=f"{ADMIN_TASK_PENALTY_PREFIX}normal",
                )
            ],
            [
                InlineKeyboardButton(
                    "No deduction on rejection",
                    callback_data=f"{ADMIN_TASK_PENALTY_PREFIX}no_penalty",
                )
            ],
        ]
        await update.message.reply_text(
            "Should this task deduct points if the manager rejects the worker response?",
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
        await _create_task_from_draft(update.message, context)
        return
