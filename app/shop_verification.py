"""
Shop Mode — Per-task verification routing.

Each task has a designated verifier. When staff marks a task done,
the confirmation request goes to that specific verifier (not a single manager).
"""

import logging
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from app.shop_store import (
    SHOP_STAFF,
    SHOP_DAILY_TASKS,
    get_task_by_id,
    now_iso,
)

logger = logging.getLogger(__name__)


def _get_shop_staff_chat_id(staff_id: str) -> int | None:
    """Get Telegram chat_id for a shop staff member."""
    from app.telegram.registry import get_shop_chat_id
    return get_shop_chat_id(staff_id)


def _get_owner_chat_ids() -> list[int]:
    """Get shop owner chat IDs."""
    from app.telegram.registry import get_shop_owner_chat_ids
    return get_shop_owner_chat_ids()


async def send_verification_request(bot: Bot, task: dict):
    """
    Send a verification request to the designated verifier for a task.

    The verifier is determined by the task template's verifier_id field,
    which comes from the VERIFIER column in the CSV.
    """
    verifier_id = task.get("verifier_id", "owner")

    # Determine verifier chat and name
    if verifier_id == "owner":
        owner_chats = _get_owner_chat_ids()
        if not owner_chats:
            logger.error(f"No owner available for verification of task {task['id']}")
            return
        verifier_chat = owner_chats[0]
        verifier_name = "Owner"
    else:
        verifier_chat = _get_shop_staff_chat_id(verifier_id)
        if not verifier_chat:
            logger.warning(f"Verifier {verifier_id} not registered, "
                           f"falling back to owner for task {task['id']}")
            owner_chats = _get_owner_chat_ids()
            if not owner_chats:
                logger.error(f"No verifier or owner available for task {task['id']}")
                return
            verifier_chat = owner_chats[0]
        verifier_name = SHOP_STAFF.get(verifier_id, {}).get("name", verifier_id)

    staff_name = SHOP_STAFF.get(task["staff_id"], {}).get("name", task["staff_id"])

    completed_time = task.get("completed_at")
    time_str = ""
    if completed_time:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(completed_time)
            time_str = f"\n⏰ Marked done at {dt.strftime('%I:%M %p')}"
        except (ValueError, TypeError):
            pass

    text = (
        f"🔍 *Verification Request*\n\n"
        f"{staff_name} says they completed:\n"
        f"📋 \"{task['description']}\"{time_str}\n\n"
        f"_Please verify, {verifier_name}:_"
    )

    buttons = [[
        InlineKeyboardButton("✅ Confirm", callback_data=f"shop_verify_yes_{task['id']}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"shop_verify_no_{task['id']}"),
    ]]

    try:
        await bot.send_message(
            chat_id=verifier_chat,
            text=text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.MARKDOWN,
        )
        logger.info(f"Verification request sent to {verifier_id} for task {task['id']}")
    except Exception as e:
        logger.error(f"Failed to send verification to {verifier_id}: {e}")


async def process_shop_verification(bot: Bot, task_id: str, confirmed: bool) -> str:
    """
    Process a verifier's response to a verification request.

    Returns a status message string.
    """
    task = get_task_by_id(task_id)
    if not task:
        return "Task not found"

    staff_name = SHOP_STAFF.get(task["staff_id"], {}).get("name", task["staff_id"])

    if confirmed:
        task["status"] = "completed"
        task["completed_at"] = now_iso()
        task["verifier_response"] = True

        # Trigger chain (fire dependent tasks)
        from app.shop_scheduler import on_task_completed
        await on_task_completed(bot, task["task_number"])

        result = f"✅ Confirmed: {staff_name}'s task \"{task['description']}\""
    else:
        task["status"] = "rejected"
        task["verifier_response"] = False
        result = f"❌ Rejected: {staff_name}'s task \"{task['description']}\""

    # Notify the staff member
    staff_chat = _get_shop_staff_chat_id(task["staff_id"])
    if staff_chat:
        icon = "✅" if confirmed else "❌"
        status_word = "confirmed" if confirmed else "rejected"
        try:
            await bot.send_message(
                chat_id=staff_chat,
                text=(
                    f"{icon} Your task has been *{status_word}*:\n"
                    f"📋 {task['description']}"
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.error(f"Failed to notify staff {task['staff_id']}: {e}")

    # FYI to Owner
    for owner_chat in _get_owner_chat_ids():
        icon = "✅" if confirmed else "❌"
        try:
            await bot.send_message(
                chat_id=owner_chat,
                text=(
                    f"{icon} *Verification Update*\n\n"
                    f"{staff_name}: {task['description']}\n"
                    f"Status: {'Confirmed' if confirmed else 'Rejected'}"
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.error(f"Failed to notify owner: {e}")

    return result
