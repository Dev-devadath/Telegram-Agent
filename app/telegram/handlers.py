"""
Telegram bot command and callback handlers.
Handles: /start (worker registration), /broadcast, /status, /report,
YES/NO task responses, and manager confirmations.
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode

from app.store import WORKERS
from app.telegram.registry import (
    register_worker,
    get_chat_id,
    get_worker_by_chat,
    get_registered_workers,
    get_manager_chat_ids,
    is_manager,
)
from app.telegram import agent_bridge

logger = logging.getLogger(__name__)


def _split_long_text(text: str, max_len: int = 4000) -> list[str]:
    """Split text into chunks that fit within Telegram's message limit."""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + max_len
        chunks.append(text[start:end])
        start = end
    return chunks


# ═══════════════════════════════════════════════════════════════════
# /start — Worker self-registration
# ═══════════════════════════════════════════════════════════════════

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start — let workers pick their role, greet the manager."""
    chat_id = update.effective_chat.id
    logger.info(f"[CMD] /start from chat_id={chat_id}")

    # Check if this is the manager
    if is_manager(chat_id):
        await update.message.reply_text(
            "👔 *Welcome, Manager!*\n\n"
            "Available commands:\n"
            "• /broadcast — Send task updates to all workers\n"
            "• /report — Get performance report\n"
            "• /status — View all workers' registration status\n",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Check if already registered
    existing = get_worker_by_chat(chat_id)
    if existing:
        worker_name = WORKERS.get(existing, {}).get("name", existing)
        await update.message.reply_text(
            f"✅ You're already registered as *{worker_name}*.\n"
            f"Use /status to see your tasks.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Show worker role picker
    buttons = []
    for worker_id, worker in WORKERS.items():
        # Skip workers already registered by someone else
        registered = get_registered_workers()
        if worker_id in registered:
            continue
        buttons.append([
            InlineKeyboardButton(
                f"{worker['name']} ({worker['role']})",
                callback_data=f"register_{worker_id}",
            )
        ])

    if not buttons:
        await update.message.reply_text(
            "⚠️ All worker roles are already registered. "
            "Contact the manager if you need access."
        )
        return

    await update.message.reply_text(
        "👋 *Welcome!* Please select your role:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN,
    )


async def register_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the inline button when a worker picks their role."""
    query = update.callback_query
    await query.answer()

    worker_id = query.data.replace("register_", "")
    chat_id = query.message.chat_id

    success = register_worker(worker_id, chat_id)
    if success:
        worker_name = WORKERS[worker_id]["name"]
        await query.edit_message_text(
            f"✅ *Registered successfully!*\n\n"
            f"You are now: *{worker_name}*\n"
            f"You'll receive task updates here when the manager sends them.\n\n"
            f"Use /status to check your tasks anytime.",
            parse_mode=ParseMode.MARKDOWN,
        )
        logger.info(f"Worker registered: {worker_id} → chat_id {chat_id}")
    else:
        await query.edit_message_text("❌ Registration failed. Invalid role.")


# ═══════════════════════════════════════════════════════════════════
# /status — Check tasks
# ═══════════════════════════════════════════════════════════════════

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current tasks for a worker, or all registrations for manager."""
    chat_id = update.effective_chat.id
    logger.info(f"[CMD] /status from chat_id={chat_id}")

    if is_manager(chat_id):
        # Show registration status
        registered = get_registered_workers()
        lines = ["📊 *Worker Registration Status:*\n"]
        for worker_id, worker in WORKERS.items():
            if worker_id in registered:
                lines.append(f"  ✅ {worker['name']} — Registered")
            else:
                lines.append(f"  ⬜ {worker['name']} — Not registered")
        await update.message.reply_text(
            "\n".join(lines), parse_mode=ParseMode.MARKDOWN
        )
        return

    worker_id = get_worker_by_chat(chat_id)
    if not worker_id:
        await update.message.reply_text(
            "⚠️ You're not registered. Use /start to register."
        )
        return

    tasks = agent_bridge.get_worker_daily_tasks(worker_id)
    worker_name = WORKERS[worker_id]["name"]

    if not tasks:
        await update.message.reply_text(
            f"📋 *{worker_name}* — No pending tasks right now.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    lines = [f"📋 *{worker_name}* — Your Tasks:\n"]
    for t in tasks:
        icon = {"assigned": "🔵", "in_progress": "🟡", "completed": "🟢", "rejected": "🔴"}.get(t["status"], "⚪")
        lines.append(f"  {icon} {t['description']} [{t['status']}]")
    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.MARKDOWN
    )


# ═══════════════════════════════════════════════════════════════════
# /broadcast — Manager triggers task updates to all workers
# ═══════════════════════════════════════════════════════════════════

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manager triggers task broadcast to all registered workers."""
    chat_id = update.effective_chat.id

    if not is_manager(chat_id):
        await update.message.reply_text("⚠️ Only the manager can broadcast.")
        return

    registered = get_registered_workers()
    if not registered:
        await update.message.reply_text(
            "⚠️ No workers registered yet. Workers need to /start the bot first."
        )
        return

    await update.message.reply_text("📤 *Broadcasting task updates...*", parse_mode=ParseMode.MARKDOWN)

    # Prepare broadcast data
    broadcast_data = agent_bridge.prepare_broadcast()
    sent_count = 0

    for worker_id, tasks in broadcast_data.items():
        worker_chat_id = registered.get(worker_id)
        if not worker_chat_id:
            continue

        worker_name = WORKERS[worker_id]["name"]

        # Build message with inline YES/NO buttons for each task
        text = f"🌅 *Good morning, {worker_name}!*\n\nHere are your tasks for today:\n"
        for i, task in enumerate(tasks, 1):
            text += f"\n{i}. {task['description']}"

        text += "\n\n_Please confirm each task below:_"

        # Create buttons for each task
        buttons = []
        for task in tasks:
            buttons.append([
                InlineKeyboardButton(f"✅ {task['description']}", callback_data=f"task_yes_{task['id']}"),
                InlineKeyboardButton(f"❌", callback_data=f"task_no_{task['id']}"),
            ])

        try:
            await context.bot.send_message(
                chat_id=worker_chat_id,
                text=text,
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode=ParseMode.MARKDOWN,
            )
            sent_count += 1
        except Exception as e:
            logger.error(f"Failed to send to {worker_id}: {e}")

    await update.message.reply_text(
        f"✅ Broadcast sent to *{sent_count}/{len(registered)}* registered workers.",
        parse_mode=ParseMode.MARKDOWN,
    )


# ═══════════════════════════════════════════════════════════════════
# Task YES/NO — Worker responds to broadcast
# ═══════════════════════════════════════════════════════════════════

async def task_response_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle worker tapping YES/NO on a task."""
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id

    data: str = query.data or ""  # "task_yes_<id>" or "task_no_<id>"
    accepted = data.startswith("task_yes_")
    task_id = data.replace("task_yes_", "").replace("task_no_", "")

    # Look up worker from task_id (handles test mode where one chat maps to many workers)
    worker_id = agent_bridge.get_worker_by_task_id(task_id)
    if not worker_id:
        # Fallback to chat_id lookup
        worker_id = get_worker_by_chat(chat_id)
    if not worker_id:
        await query.edit_message_text("⚠️ You're not registered.")
        return

    # Record the response
    result = agent_bridge.record_worker_response(worker_id, task_id, accepted)

    # Send acknowledgment to worker
    icon = "✅" if accepted else "❌"
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"{icon} Response recorded: {result}",
    )

    # Check if worker is done with all tasks
    if agent_bridge.is_worker_done_responding(worker_id):
        summary = agent_bridge.get_worker_response_summary(worker_id)

        # Notify all managers
        buttons = [
            [
                InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_{worker_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_{worker_id}"),
            ]
        ]
        for manager_chat in get_manager_chat_ids():
            await context.bot.send_message(
                chat_id=manager_chat,
                text=summary,
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode=ParseMode.MARKDOWN,
            )

        await context.bot.send_message(
            chat_id=chat_id,
            text="📨 Your responses have been sent to the manager for confirmation.",
        )


# ═══════════════════════════════════════════════════════════════════
# Manager CONFIRM/REJECT — Confirms worker batches
# ═══════════════════════════════════════════════════════════════════

async def manager_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle manager confirming or rejecting a worker's task batch."""
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    if not is_manager(chat_id):
        return

    data = query.data  # "confirm_<worker_id>" or "reject_<worker_id>"
    confirmed = data.startswith("confirm_")
    worker_id = data.replace("confirm_", "").replace("reject_", "")

    result = agent_bridge.record_manager_confirmation(worker_id, confirmed)

    # Edit the original message to show the decision
    icon = "✅" if confirmed else "❌"
    original_text = query.message.text or ""
    await query.edit_message_text(
        f"{original_text}\n\n{icon} *{result}*",
        parse_mode=ParseMode.MARKDOWN,
    )

    # Notify the worker
    worker_chat = get_chat_id(worker_id)
    if worker_chat:
        worker_name = WORKERS.get(worker_id, {}).get("name", worker_id)
        status = "✅ confirmed" if confirmed else "❌ rejected"
        await context.bot.send_message(
            chat_id=worker_chat,
            text=f"📢 The manager has {status} your tasks for today.",
        )

    # Check if all workers are confirmed — if so, offer performance report
    pending = agent_bridge.get_workers_pending_confirmation()
    if not pending:
        await context.bot.send_message(
            chat_id=chat_id,
            text="🎉 All workers confirmed! Use /report to see the performance summary.",
        )


# ═══════════════════════════════════════════════════════════════════
# /report — Performance report
# ═══════════════════════════════════════════════════════════════════

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate and send a performance report to the manager."""
    chat_id = update.effective_chat.id

    if not is_manager(chat_id):
        await update.message.reply_text("⚠️ Only the manager can request reports.")
        return

    await update.message.reply_text("📊 *Generating performance report...*", parse_mode=ParseMode.MARKDOWN)

    try:
        report: str = await agent_bridge.generate_performance_report()
        # Telegram has a 4096 char limit — split if needed
        for chunk in _split_long_text(report):
            await update.message.reply_text(chunk)
    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        await update.message.reply_text(f"❌ Error generating report: {e}")


# ═══════════════════════════════════════════════════════════════════
# Natural language from manager (catch-all)
# ═══════════════════════════════════════════════════════════════════

async def manager_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle free-text messages from the manager — route to ADK agent."""
    import time as _time
    chat_id = update.effective_chat.id
    msg_text = (update.message.text or "")[:60]

    logger.info(f"[HANDLER] ── message_handler ENTER ── chat_id={chat_id} text='{msg_text}...'")

    if not is_manager(chat_id):
        # Non-registered users or workers sending text
        worker_id = get_worker_by_chat(chat_id)
        if not worker_id:
            await update.message.reply_text("⚠️ Use /start to register first.")
        logger.info(f"[HANDLER] Non-manager message from chat_id={chat_id}, skipping agent")
        return

    user_text = update.message.text.strip().lower()

    # Check if manager wants to broadcast
    broadcast_keywords = ["send updates", "broadcast", "send tasks", "notify workers", "trigger updates"]
    if any(kw in user_text for kw in broadcast_keywords):
        logger.info(f"[HANDLER] Broadcast keyword detected, delegating to broadcast_command")
        await broadcast_command(update, context)
        return

    # Otherwise, send to ADK agent
    logger.info(f"[HANDLER] Routing to ADK agent...")
    await update.message.reply_text("🤔 _Processing..._", parse_mode=ParseMode.MARKDOWN)

    # Snapshot task count before agent runs
    from app.store import TASKS
    tasks_before = len(TASKS)

    t0 = _time.monotonic()
    try:
        logger.info(f"[HANDLER] Calling agent_bridge.ask_agent('manager_tg', ...)...")
        response: str = await agent_bridge.ask_agent("manager_tg", update.message.text)
        elapsed = _time.monotonic() - t0
        logger.info(f"[HANDLER] agent returned in {elapsed:.1f}s, response={len(response)}ch")

        for chunk in _split_long_text(response):
            await update.message.reply_text(chunk)

        # Check if the agent assigned new tasks — notify workers via Telegram
        new_tasks = TASKS[tasks_before:]
        for task in new_tasks:
            worker_chat = get_chat_id(task["worker_id"])
            if worker_chat:
                await context.bot.send_message(
                    chat_id=worker_chat,
                    text=f"📋 *New Task Assigned:*\n{task['description']}",
                    parse_mode=ParseMode.MARKDOWN,
                )
        logger.info(f"[HANDLER] ── message_handler DONE ── {elapsed:.1f}s")
    except Exception as e:
        elapsed = _time.monotonic() - t0
        logger.error(f"[HANDLER] ── message_handler EXCEPTION after {elapsed:.1f}s ── {type(e).__name__}: {e}")
        await update.message.reply_text(f"❌ Error: {e}")


# ═══════════════════════════════════════════════════════════════════
# /testmode — Solo testing with one account
# ═══════════════════════════════════════════════════════════════════

async def testmode_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Register the current user as manager + 2 workers for solo testing."""
    chat_id = update.effective_chat.id

    if not is_manager(chat_id):
        await update.message.reply_text("⚠️ Only the manager can enable test mode.")
        return

    # Register this chat_id as driver-1 and cook
    test_workers = ["driver-1", "cook"]
    registered = []
    for wid in test_workers:
        register_worker(wid, chat_id)
        registered.append(WORKERS[wid]["name"])

    names = ", ".join(registered)
    await update.message.reply_text(
        f"🧪 *Test mode enabled!*\n\n"
        f"Your account is now registered as:\n"
        f"  👔 Manager\n"
        f"  👷 {registered[0]}\n"
        f"  👷 {registered[1]}\n\n"
        f"Try these commands:\n"
        f"1. /broadcast — send tasks to yourself\n"
        f"2. Tap ✅/❌ on tasks\n"
        f"3. CONFIRM/REJECT worker batches\n"
        f"4. /report — see performance summary",
        parse_mode=ParseMode.MARKDOWN,
    )


# ═══════════════════════════════════════════════════════════════════
# Handler registration helper
# ═══════════════════════════════════════════════════════════════════

def get_all_handlers() -> list:
    """Return all handlers to register with the Application."""
    import os
    bot_mode = os.environ.get("BOT_MODE", "resort").strip().lower()

    if bot_mode == "shop":
        from app.telegram.shop_handlers import get_shop_handlers
        handlers = get_shop_handlers()
        logger.info(f"[INIT] Shop mode: {len(handlers)} handlers registered")
    else:
        handlers = [
            CommandHandler("start", start_command),
            CommandHandler("status", status_command),
            CommandHandler("broadcast", broadcast_command),
            CommandHandler("report", report_command),
            CommandHandler("testmode", testmode_command),
            # Callback queries
            CallbackQueryHandler(register_callback, pattern=r"^register_"),
            CallbackQueryHandler(task_response_callback, pattern=r"^task_(yes|no)_"),
            CallbackQueryHandler(manager_confirm_callback, pattern=r"^(confirm|reject)_"),
        ]

    # Catch-all text handler — ONLY for resort mode (uses ADK agent / Groq).
    # Shop mode has no ADK agent, so text messages should be ignored.
    import os
    bot_mode = os.environ.get("BOT_MODE", "resort").strip().lower()
    if bot_mode != "shop":
        handlers.append(
            MessageHandler(filters.TEXT & ~filters.COMMAND, manager_message_handler),
        )
        logger.info("[INIT] Resort mode: catch-all agent handler registered")
    else:
        logger.info("[INIT] Shop mode: catch-all agent handler SKIPPED (no ADK agent)")

    return handlers

