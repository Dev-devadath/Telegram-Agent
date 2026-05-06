from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import store


REGISTER_ROLE_PREFIX = "register_role:"


def _is_registration_pending(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(context.user_data.get("pending_worker_role"))


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user:
        return

    user = store.get_user_by_telegram(update.effective_user.id)
    if user:
        if user["role"] == "worker":
            await update.message.reply_text(
                f"Welcome back. You are registered as {user['worker_role']}."
            )
        else:
            await update.message.reply_text(f"Welcome back, {user['role'].title()}.")
        return

    unclaimed_roles = store.get_unclaimed_roles()
    if not unclaimed_roles:
        await update.message.reply_text(
            "No worker roles are currently available. Please contact admin."
        )
        return

    keyboard = [
        [InlineKeyboardButton(role, callback_data=f"{REGISTER_ROLE_PREFIX}{role}")]
        for role in unclaimed_roles
    ]
    await update.message.reply_text(
        "Select your role to register:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def register_role_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return

    await query.answer()
    role = query.data.replace(REGISTER_ROLE_PREFIX, "", 1)
    if role not in store.get_unclaimed_roles():
        await query.edit_message_text("This role is already claimed. Please choose another.")
        return

    context.user_data["pending_worker_role"] = role
    await query.edit_message_text(f"You selected {role}. Send your name to complete registration.")


async def registration_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
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
    await update.message.reply_text(
        f"Registration complete.\nName: {worker['name']}\nRole: {worker['worker_role']}"
    )
