from datetime import datetime
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import scheduler
import store

TASK_PREFIX = "task_"
YES_PREFIX = "task_yes:"
YES_NOTE_PREFIX = "task_yes_note:"
NO_PREFIX = "task_no:"
EXTEND_PREFIX = "task_extend:"

VERIFY_PREFIX = "verify:"
REJECT_PREFIX = "reject:"
logger = logging.getLogger(__name__)


def _completion_message(prefix: str = "Marked as done.") -> str:
    return (
        f"{prefix} Great work! 🎉✅\n"
        "Thanks for completing the task. Sent to manager for verification."
    )


def _parse_extension_minutes(value: str) -> int | None:
    match = re.fullmatch(
        r"\s*(\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)\s*",
        value,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2).lower()
    if amount <= 0:
        return None
    if unit in {"m", "min", "mins", "minute", "minutes"}:
        return amount
    if unit in {"h", "hr", "hrs", "hour", "hours"}:
        return amount * 60
    if unit in {"d", "day", "days"}:
        return amount * 24 * 60
    return None


def _format_extension(minutes: int) -> str:
    if minutes % (24 * 60) == 0:
        days = minutes // (24 * 60)
        return f"{days} day{'s' if days != 1 else ''}"
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


def _is_worker(telegram_id: int) -> bool:
    if store.telegram_has_role(telegram_id, "worker"):
        return True
    settings = store.get_settings()
    return bool(
        settings.get("test_mode") and settings.get("test_telegram_id") == telegram_id
    )


async def task_response_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return
    await query.answer()

    if not _is_worker(query.from_user.id):
        await query.edit_message_text("Only workers can respond to tasks.")
        return

    data = query.data
    run_id = data.split(":", maxsplit=1)[1]
    run = store.get_task_run(run_id)
    if not run:
        await query.edit_message_text("Task run not found.")
        return

    if data.startswith(YES_PREFIX):
        store.update_task_run(
            run_id,
            {
                "status": "worker_done",
                "worker_response": "yes",
                "completed_at": datetime.utcnow().replace(microsecond=0).isoformat(),
            },
        )
        await query.edit_message_text(_completion_message())
        await _notify_manager_for_verification(context, run_id)
        return

    if data.startswith(YES_NOTE_PREFIX):
        context.user_data["pending_yes_note_run_id"] = run_id
        await query.edit_message_text("Please send the note for this completed task.")
        return

    if data.startswith(NO_PREFIX):
        context.user_data["pending_no_reason_run_id"] = run_id
        await query.edit_message_text("Please send the reason for NO.")
        return

    if data.startswith(EXTEND_PREFIX):
        context.user_data["pending_extension_run_id"] = run_id
        await query.edit_message_text(
            "How long do you need to extend this task?\n"
            "Send a duration like 2 hours, 1 day, 45 minutes, 3h, or 2d."
        )
        return


async def no_reason_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not _is_worker(update.effective_user.id):
        return

    extension_run_id = context.user_data.get("pending_extension_run_id")
    if extension_run_id:
        minutes = _parse_extension_minutes(update.message.text)
        if minutes is None:
            await update.message.reply_text(
                "Invalid duration. Send a value like 2 hours, 1 day, 45 minutes, 3h, or 2d."
            )
            return

        scheduler.schedule_extension_for_run(context.application, extension_run_id, minutes)
        store.update_task_run(
            extension_run_id,
            {
                "status": "extended",
                "worker_response": "extend",
            },
        )
        context.user_data.pop("pending_extension_run_id", None)
        await update.message.reply_text(
            f"Task extended by {_format_extension(minutes)}. ⏰"
        )
        return

    note_run_id = context.user_data.get("pending_yes_note_run_id")
    if note_run_id:
        note = update.message.text.strip()
        store.update_task_run(
            note_run_id,
            {
                "status": "worker_done",
                "worker_response": "yes",
                "worker_note": note,
                "completed_at": datetime.utcnow().replace(microsecond=0).isoformat(),
            },
        )
        context.user_data.pop("pending_yes_note_run_id", None)
        await update.message.reply_text(_completion_message("Note submitted."))
        logger.info("Worker YES note captured for run_id=%s", note_run_id)
        await _notify_manager_for_verification(context, note_run_id)
        return

    run_id = context.user_data.get("pending_no_reason_run_id")
    if not run_id:
        return

    reason = update.message.text.strip()
    store.update_task_run(
        run_id,
        {
            "status": "worker_not_done",
            "worker_response": "no",
            "reason": reason,
            "completed_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        },
    )
    context.user_data.pop("pending_no_reason_run_id", None)
    await update.message.reply_text("Reason submitted. Sent to manager for verification.")
    logger.info("Worker NO reason captured for run_id=%s", run_id)
    await _notify_manager_for_verification(context, run_id)


async def _notify_manager_for_verification(
    context: ContextTypes.DEFAULT_TYPE,
    run_id: str,
) -> None:
    run = store.get_task_run(run_id)
    if not run:
        return
    task = store.get_task_by_id(run["task_id"])
    manager = store.get_user_by_id(run["manager_id"])
    worker = store.get_user_by_role(run["worker_role"])
    if not task or not manager:
        logger.warning(
            "Cannot notify manager for run_id=%s (task_found=%s manager_found=%s)",
            run_id,
            bool(task),
            bool(manager),
        )
        return

    reason_text = f"\nReason: {run.get('reason')}" if run.get("reason") else ""
    note_text = f"\nNote: {run.get('worker_note')}" if run.get("worker_note") else ""
    worker_name = worker["name"] if worker else run["worker_role"]
    text = (
        f"Worker update received.\n"
        f"Role: {run['worker_role']} ({worker_name})\n"
        f"Task: {task['title']}\n"
        f"Response: {run.get('worker_response', 'n/a').upper()}"
        f"{reason_text}"
        f"{note_text}\n\nVerify?"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Verified", callback_data=f"{VERIFY_PREFIX}{run_id}"),
                InlineKeyboardButton("Reject", callback_data=f"{REJECT_PREFIX}{run_id}"),
            ]
        ]
    )
    await context.bot.send_message(
        chat_id=manager["telegram_id"],
        text=text,
        reply_markup=markup,
    )
    logger.info(
        "Manager verification request sent for run_id=%s to manager_chat_id=%s",
        run_id,
        manager["telegram_id"],
    )
