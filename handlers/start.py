from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import store
from handlers.manager import manager_menu_markup, owner_menu_markup


REGISTER_ROLE_PREFIX = "register_role:"


def _is_registration_pending(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(context.user_data.get("pending_worker_role"))


def _is_password_pending(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(context.user_data.get("awaiting_manager_password"))


async def _send_manager_role_choices(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    manager: dict,
) -> None:
    unclaimed_roles = store.get_unclaimed_roles_for_manager(manager["id"])
    if not unclaimed_roles:
        await update.message.reply_text(
            "No worker roles are currently available under this manager. Please contact admin."
        )
        return

    context.user_data["registration_manager_id"] = manager["id"]
    keyboard = [
        [InlineKeyboardButton(role, callback_data=f"{REGISTER_ROLE_PREFIX}{role}")]
        for role in unclaimed_roles
    ]
    await update.message.reply_text(
        f"Manager matched: {manager['name']}\nSelect your role to register:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id
    if store.telegram_has_role(telegram_id, "owner"):
        owner = store.get_user_by_telegram_and_role(telegram_id, "owner")
        await update.message.reply_text(
            f"Welcome back, Owner {owner['name']}.",
            reply_markup=owner_menu_markup(),
        )
        return

    if store.telegram_has_role(telegram_id, "manager"):
        manager = store.get_user_by_telegram_and_role(telegram_id, "manager")
        await update.message.reply_text(
            f"Welcome back, Manager {manager['name']}.",
            reply_markup=manager_menu_markup(),
        )
        return

    user = store.get_user_by_telegram(telegram_id)
    if user:
        if user["role"] == "worker":
            await update.message.reply_text(
                f"Welcome back. You are registered as {user['worker_role']}."
            )
        else:
            await update.message.reply_text(f"Welcome back, {user['role'].title()}.")
        return

    context.user_data.clear()
    context.user_data["awaiting_manager_password"] = True
    await update.message.reply_text("Send your manager registration password.")


async def register_role_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return

    await query.answer()
    role = query.data.replace(REGISTER_ROLE_PREFIX, "", 1)
    manager_id = context.user_data.get("registration_manager_id")
    if not manager_id:
        await query.edit_message_text("Please use /start and enter your manager password first.")
        return
    if role not in store.get_unclaimed_roles_for_manager(manager_id):
        await query.edit_message_text("This role is already claimed. Please choose another.")
        return

    context.user_data["pending_worker_role"] = role
    await query.edit_message_text(f"You selected {role}. Send your name to complete registration.")


async def registration_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if _is_password_pending(context):
        password = update.message.text.strip()
        manager = store.get_manager_by_password(password)
        if not manager:
            await update.message.reply_text("Invalid manager password. Please try again.")
            return

        context.user_data.pop("awaiting_manager_password", None)
        await _send_manager_role_choices(update, context, manager)
        return

    if not _is_registration_pending(context):
        return

    role = context.user_data.get("pending_worker_role")
    name = update.message.text.strip()
    try:
        worker = store.add_user(
            telegram_id=update.effective_user.id,
            name=name,
            system_role="worker",
            worker_role=role,
        )
    except ValueError as exc:
        await update.message.reply_text(f"Registration failed: {exc}")
        return

    context.user_data.pop("pending_worker_role", None)
    context.user_data.pop("registration_manager_id", None)
    await update.message.reply_text(
        f"Registration complete.\nName: {worker['name']}\nRole: {worker['worker_role']}"
    )
