from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

DEMO_YES = "demo_yes"
DEMO_NO = "demo_no"
DEMO_VERIFY = "demo_verify"
DEMO_REJECT = "demo_reject"


def _task_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Yes", callback_data=DEMO_YES),
                InlineKeyboardButton("No", callback_data=DEMO_NO),
            ]
        ]
    )


def _verify_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Verified", callback_data=DEMO_VERIFY),
                InlineKeyboardButton("Reject", callback_data=DEMO_REJECT),
            ]
        ]
    )


async def demo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return

    context.user_data.pop("demo_pending_reason", None)
    context.user_data["demo_run"] = {
        "task": "Is the shop open?",
        "response": None,
        "reason": None,
        "started_at": datetime.utcnow().replace(microsecond=0).isoformat(),
    }

    await update.message.reply_text(
        "Welcome to the demo.\n\n"
        "This will show how a worker receives a task, responds, and then a manager verifies it."
    )
    await update.message.reply_text(
        "Demo Worker Task\n\n"
        "Task: Is the shop open?\n\n"
        "Have you done this?",
        reply_markup=_task_markup(),
    )


async def demo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    await query.answer()
    data = query.data

    if data == DEMO_YES:
        demo_run = context.user_data.get("demo_run", {})
        demo_run["response"] = "yes"
        context.user_data["demo_run"] = demo_run
        await query.edit_message_text(
            "Worker response submitted: YES.\n\nSending it to manager for verification..."
        )
        await _send_demo_manager_confirmation(context, query.message.chat_id)
        return

    if data == DEMO_NO:
        context.user_data["demo_pending_reason"] = True
        await query.edit_message_text("Worker response submitted: NO.\n\nPlease send the reason.")
        return

    if data == DEMO_VERIFY:
        await query.edit_message_text(
            "Manager verified the task.\n\nDemo complete: the task is now recorded as completed."
        )
        context.user_data.pop("demo_run", None)
        context.user_data.pop("demo_pending_reason", None)
        return

    if data == DEMO_REJECT:
        await query.edit_message_text(
            "Manager rejected the worker response.\n\nDemo complete: the task is marked as rejected."
        )
        context.user_data.pop("demo_run", None)
        context.user_data.pop("demo_pending_reason", None)
        return


async def demo_reason_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not context.user_data.get("demo_pending_reason"):
        return

    reason = update.message.text.strip()
    demo_run = context.user_data.get("demo_run", {})
    demo_run["response"] = "no"
    demo_run["reason"] = reason
    context.user_data["demo_run"] = demo_run
    context.user_data.pop("demo_pending_reason", None)

    await update.message.reply_text(
        "Reason submitted.\n\nSending it to manager for verification..."
    )
    await _send_demo_manager_confirmation(context, update.effective_chat.id)


async def _send_demo_manager_confirmation(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
) -> None:
    demo_run = context.user_data.get("demo_run", {})
    response = (demo_run.get("response") or "n/a").upper()
    reason = demo_run.get("reason")
    reason_text = f"\nReason: {reason}" if reason else ""

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "Demo Manager Verification\n\n"
            "Worker: Demo Worker\n"
            "Task: Is the shop open?\n"
            f"Worker response: {response}"
            f"{reason_text}\n\n"
            "As the manager, verify this response?"
        ),
        reply_markup=_verify_markup(),
    )
