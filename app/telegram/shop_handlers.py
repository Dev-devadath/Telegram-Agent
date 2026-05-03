"""
Shop Mode — Telegram command and callback handlers.

Handles /shopstart, /shopstatus, /shopbroadcast, task done/delay responses,
and verification confirm/reject callbacks.
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
)
from telegram.constants import ParseMode

from app.shop_store import (
    SHOP_STAFF,
    SHOP_DAILY_TASKS,
    SHOP_TASK_TEMPLATES,
    get_task_by_id,
    get_tasks_for_staff,
    get_templates_for_staff,
    get_automatable_templates,
    now_iso,
    load_shop_tasks,
)
from app.telegram.registry import (
    register_shop_staff,
    get_shop_chat_id,
    get_shop_staff_by_chat,
    get_registered_shop_staff,
    is_shop_owner,
    get_shop_owner_chat_ids,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# /shopstart — Staff self-registration
# ═══════════════════════════════════════════════════════════════════

async def shopstart_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /shopstart — let staff pick their role, greet the owner."""
    chat_id = update.effective_chat.id
    logger.info(f"[SHOP-CMD] /start from chat_id={chat_id} is_owner={is_shop_owner(chat_id)}")

    # Check if this is the owner
    if is_shop_owner(chat_id):
        await update.message.reply_text(
            "👔 *Welcome, Owner!*\n\n"
            "🏪 Shop Mode is active.\n\n"
            "Available commands:\n"
            "• /shopbroadcast — Send morning task summary to all staff\n"
            "• /shopstatus — View all tasks and their status\n",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Check if already registered
    existing = get_shop_staff_by_chat(chat_id)
    if existing:
        staff_name = SHOP_STAFF.get(existing, {}).get("name", existing)
        await update.message.reply_text(
            f"✅ You're already registered as *{staff_name}* (Shop Mode).\n"
            f"Use /shopstatus to see your tasks.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Show staff role picker
    buttons = []
    registered = get_registered_shop_staff()
    for staff_id, staff in SHOP_STAFF.items():
        # Skip staff already registered
        if staff_id in registered:
            continue
        buttons.append([
            InlineKeyboardButton(
                f"{staff['name']} ({staff['role']})",
                callback_data=f"shop_register_{staff_id}",
            )
        ])

    if not buttons:
        await update.message.reply_text(
            "⚠️ All shop staff roles are already registered. "
            "Contact the owner if you need access."
        )
        return

    await update.message.reply_text(
        "🏪 *Shop Mode — Registration*\n\n"
        "Please select your role:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN,
    )


async def shop_register_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle staff selecting their role via inline button."""
    query = update.callback_query
    await query.answer()
    logger.info(f"[SHOP-CB] register callback data={query.data} chat={query.message.chat_id}")

    staff_id = query.data.replace("shop_register_", "")
    chat_id = query.message.chat_id

    success = register_shop_staff(staff_id, chat_id)
    if success:
        staff_name = SHOP_STAFF[staff_id]["name"]
        shop = SHOP_STAFF[staff_id].get("shop", "")
        shop_label = f" (Shop {shop})" if isinstance(shop, int) else ""

        await query.edit_message_text(
            f"✅ *Registered successfully!*\n\n"
            f"You are now: *{staff_name}*{shop_label}\n"
            f"You'll receive task notifications here.\n\n"
            f"Use /shopstatus to check your tasks anytime.",
            parse_mode=ParseMode.MARKDOWN,
        )
        logger.info(f"Shop staff registered: {staff_id} → chat_id {chat_id}")
    else:
        await query.edit_message_text("❌ Registration failed. Invalid role.")


# ═══════════════════════════════════════════════════════════════════
# /shopstatus — View tasks
# ═══════════════════════════════════════════════════════════════════

async def shopstatus_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current shop tasks for a staff member, or overview for owner."""
    chat_id = update.effective_chat.id
    logger.info(f"[SHOP-CMD] /status from chat_id={chat_id} is_owner={is_shop_owner(chat_id)}")

    if is_shop_owner(chat_id):
        # Owner sees full overview
        lines = ["📊 *Shop Mode — Task Status Overview*\n"]

        for staff_id, staff in SHOP_STAFF.items():
            if staff_id == "yousuf":
                continue  # Verifier-only

            tasks = get_tasks_for_staff(staff_id)
            if not tasks:
                lines.append(f"  👤 *{staff['name']}:* No tasks dispatched yet")
                continue

            completed = sum(1 for t in tasks if t["status"] == "completed")
            pending = sum(1 for t in tasks if t["status"] in ("assigned", "in_progress"))
            rejected = sum(1 for t in tasks if t["status"] == "rejected")

            status_parts = []
            if completed:
                status_parts.append(f"✅{completed}")
            if pending:
                status_parts.append(f"🔵{pending}")
            if rejected:
                status_parts.append(f"❌{rejected}")

            lines.append(f"  👤 *{staff['name']}:* {' '.join(status_parts)}")

        # Registered staff count
        registered = get_registered_shop_staff()
        total_staff = len([s for s in SHOP_STAFF if s != "yousuf"])
        lines.append(f"\n📱 Registered: {len(registered)}/{total_staff} staff")

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Staff member sees their own tasks
    staff_id = get_shop_staff_by_chat(chat_id)
    if not staff_id:
        await update.message.reply_text(
            "⚠️ You're not registered for Shop Mode. Use /shopstart to register."
        )
        return

    tasks = get_tasks_for_staff(staff_id)
    staff_name = SHOP_STAFF[staff_id]["name"]

    if not tasks:
        await update.message.reply_text(
            f"📋 *{staff_name}* — No tasks dispatched yet today.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    lines = [f"📋 *{staff_name}* — Today's Tasks:\n"]
    for t in tasks:
        icon = {
            "assigned": "🔵", "in_progress": "🟡",
            "completed": "🟢", "rejected": "🔴",
        }.get(t["status"], "⚪")
        lines.append(f"  {icon} {t['description']} [{t['status']}]")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
    )


# ═══════════════════════════════════════════════════════════════════
# /shopbroadcast — Owner triggers morning broadcast
# ═══════════════════════════════════════════════════════════════════

async def shopbroadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner manually triggers the morning broadcast."""
    chat_id = update.effective_chat.id
    logger.info(f"[SHOP-CMD] /broadcast from chat_id={chat_id}")

    if not is_shop_owner(chat_id):
        await update.message.reply_text("⚠️ Only the owner can use /shopbroadcast.")
        return

    # Ensure templates are loaded
    if not SHOP_TASK_TEMPLATES:
        try:
            load_shop_tasks()
        except Exception as e:
            await update.message.reply_text(f"❌ Failed to load tasks: {e}")
            return

    registered = get_registered_shop_staff()
    if not registered:
        await update.message.reply_text(
            "⚠️ No shop staff registered yet. Staff need to /shopstart first."
        )
        return

    await update.message.reply_text(
        "📤 *Broadcasting morning summary to all staff...*",
        parse_mode=ParseMode.MARKDOWN,
    )

    from app.shop_scheduler import morning_broadcast
    await morning_broadcast(context.bot)

    await update.message.reply_text(
        f"✅ Morning broadcast sent to {len(registered)} registered staff.",
    )


# ═══════════════════════════════════════════════════════════════════
# Task Done — Staff marks task as completed
# ═══════════════════════════════════════════════════════════════════

async def shop_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Staff taps Done on a task — sends to verifier."""
    query = update.callback_query
    await query.answer()

    task_id = query.data.replace("shop_done_", "")
    logger.info(f"[SHOP-CB] done callback task_id={task_id} chat={query.message.chat_id}")
    task = get_task_by_id(task_id)

    if not task:
        await query.edit_message_text("⚠️ Task not found.")
        return

    if task["status"] in ("completed", "rejected"):
        await query.edit_message_text(
            f"ℹ️ This task was already {task['status']}:\n"
            f"📋 {task['description']}"
        )
        return

    # Mark as in_progress (waiting for verification)
    task["status"] = "in_progress"
    task["worker_response"] = True
    task["completed_at"] = now_iso()

    # Update the message
    await query.edit_message_text(
        f"✅ *Marked as done!*\n\n"
        f"📋 {task['description']}\n\n"
        f"_Sent to verifier for confirmation..._",
        parse_mode=ParseMode.MARKDOWN,
    )

    # Send to verifier
    from app.shop_verification import send_verification_request
    await send_verification_request(context.bot, task)


# ═══════════════════════════════════════════════════════════════════
# Task Delay — Staff needs more time
# ═══════════════════════════════════════════════════════════════════

async def shop_delay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Staff taps 'Need More Time' — notifies manager + owner, sets reminder."""
    query = update.callback_query
    await query.answer()

    task_id = query.data.replace("shop_delay_", "")
    logger.info(f"[SHOP-CB] delay callback task_id={task_id} chat={query.message.chat_id}")
    task = get_task_by_id(task_id)

    if not task:
        await query.edit_message_text("⚠️ Task not found.")
        return

    if task["status"] in ("completed", "rejected"):
        await query.edit_message_text(
            f"ℹ️ This task was already {task['status']}."
        )
        return

    # Keep buttons so they can still mark it done later
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=(
            f"⏳ Got it! A reminder will be sent in 30 minutes.\n"
            f"📋 {task['description']}"
        ),
    )

    from app.shop_scheduler import on_task_delayed
    await on_task_delayed(context.bot, task_id, context)


# ═══════════════════════════════════════════════════════════════════
# Verification Confirm/Reject — Verifier responds
# ═══════════════════════════════════════════════════════════════════

async def shop_verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Verifier confirms or rejects a task completion."""
    query = update.callback_query
    await query.answer()

    data = query.data  # "shop_verify_yes_<id>" or "shop_verify_no_<id>"
    logger.info(f"[SHOP-CB] verify callback data={data} chat={query.message.chat_id}")
    confirmed = "shop_verify_yes_" in data
    task_id = data.replace("shop_verify_yes_", "").replace("shop_verify_no_", "")

    from app.shop_verification import process_shop_verification
    result = await process_shop_verification(context.bot, task_id, confirmed)

    # Update the verification message
    icon = "✅" if confirmed else "❌"
    original_text = query.message.text or ""
    await query.edit_message_text(
        f"{original_text}\n\n{icon} *{'Confirmed' if confirmed else 'Rejected'}*",
        parse_mode=ParseMode.MARKDOWN,
    )


# ═══════════════════════════════════════════════════════════════════
# /shoptestmode — Solo testing with one account
# ═══════════════════════════════════════════════════════════════════

async def shoptestmode_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Register the current user as owner + all staff for solo testing.
    Activates test mode: first task in 1 min, then every 2 min."""
    chat_id = update.effective_chat.id
    logger.info(f"[SHOP-CMD] /testmode from chat_id={chat_id}")

    if not is_shop_owner(chat_id):
        await update.message.reply_text("⚠️ Only the owner can enable shop test mode.")
        return

    # Register this chat_id as all staff members
    test_staff = ["sanoof", "favan", "junaid", "haris", "yousuf"]
    registered = []
    for sid in test_staff:
        register_shop_staff(sid, chat_id)
        registered.append(SHOP_STAFF[sid]["name"])

    # Ensure templates are loaded
    if not SHOP_TASK_TEMPLATES:
        try:
            load_shop_tasks()
        except Exception as e:
            await update.message.reply_text(f"❌ Failed to load tasks: {e}")
            return

    # Schedule all tasks using APScheduler (test mode: +1min, +3min, +5min...)
    from app.shop_scheduler import schedule_shop_tasks
    preview = schedule_shop_tasks(context.job_queue, test_mode=True)

    # Build schedule preview (first 10 tasks)
    timed_tasks = [p for p in preview if p["type"] != "sequential"]
    seq_tasks = [p for p in preview if p["type"] == "sequential"]

    preview_lines = []
    for item in timed_tasks[:10]:
        preview_lines.append(
            f"  🕐 {item['fire_at']} — {item['description'][:40]} ({item['staff']})"
        )
    if len(timed_tasks) > 10:
        preview_lines.append(f"  _...and {len(timed_tasks) - 10} more timed tasks_")
    if seq_tasks:
        preview_lines.append(f"  🔗 {len(seq_tasks)} chain-triggered tasks")

    schedule_text = "\n".join(preview_lines) if preview_lines else "  No tasks scheduled"

    await update.message.reply_text(
        f"🧪 *Shop Test Mode enabled!*\n\n"
        f"Your account is now registered as:\n"
        f"  👔 Owner\n"
        f"  👷 {', '.join(registered)}\n\n"
        f"📋 {len(SHOP_TASK_TEMPLATES)} templates loaded\n"
        f"⏰ {len(timed_tasks)} tasks scheduled (1st in 1min, then every 2min)\n\n"
        f"*Upcoming tasks:*\n{schedule_text}\n\n"
        f"_First task arrives in ~1 minute!_",
        parse_mode=ParseMode.MARKDOWN,
    )



# ═══════════════════════════════════════════════════════════════════
# Handler list
# ═══════════════════════════════════════════════════════════════════

def get_shop_handlers() -> list:
    """Return all shop mode handlers to register with the Application.
    Uses standard command names (/start, /status, etc.) since
    BOT_MODE=shop means only shop handlers are loaded."""
    return [
        CommandHandler("start", shopstart_command),
        CommandHandler("status", shopstatus_command),
        CommandHandler("broadcast", shopbroadcast_command),
        CommandHandler("testmode", shoptestmode_command),
        # Callbacks
        CallbackQueryHandler(shop_register_callback, pattern=r"^shop_register_"),
        CallbackQueryHandler(shop_done_callback, pattern=r"^shop_done_"),
        CallbackQueryHandler(shop_delay_callback, pattern=r"^shop_delay_"),
        CallbackQueryHandler(shop_verify_callback, pattern=r"^shop_verify_(yes|no)_"),
    ]

