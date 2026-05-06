from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import store

VERIFY_PREFIX = "verify:"
REJECT_PREFIX = "reject:"

REPORT_ROLE_PREFIX = "report_role:"
REPORT_PERIOD_PREFIX = "report_period:"


def _can_view_reports(telegram_id: int) -> bool:
    return store.telegram_has_role(telegram_id, "admin") or store.telegram_has_role(
        telegram_id, "manager"
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
