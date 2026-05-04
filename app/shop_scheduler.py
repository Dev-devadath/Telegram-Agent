"""
Shop Mode — Task Scheduler (APScheduler-based).

Each task gets its own APScheduler job instead of a polling tick loop.
- Normal mode: run_daily jobs at CSV trigger times
- Test mode: run_once jobs at +1min, +3min, +5min, ...
- Chain triggers: dependent tasks scheduled on-the-fly when parent completes
"""

import logging
from datetime import datetime, time, timedelta
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.shop_store import (
    SHOP_STAFF,
    SHOP_TASK_TEMPLATES,
    SHOP_COMPLETED_TASK_NUMBERS,
    SHOP_DISPATCHED_TASK_NUMBERS,
    IST,
    now_ist,
    get_automatable_templates,
    get_fixed_time_templates,
    get_dependents,
    get_templates_for_staff,
    create_daily_task,
    get_task_by_id,
    reset_daily_state,
    load_shop_tasks,
    ShopTaskTemplate,
)

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────

def _get_shop_staff_chat_id(staff_id: str) -> int | None:
    """Get Telegram chat_id for a shop staff member."""
    from app.telegram.registry import get_shop_chat_id
    return get_shop_chat_id(staff_id)


def _get_owner_chat_ids() -> list[int]:
    """Get shop owner chat IDs."""
    from app.telegram.registry import get_shop_owner_chat_ids
    return get_shop_owner_chat_ids()


def _should_run_today(template: ShopTaskTemplate) -> bool:
    """Check if a recurring task should run today."""
    today = now_ist()

    if template.repeat == "daily":
        return True
    elif template.repeat == "monthly":
        return today.day == (template.repeat_day or 1)
    elif template.repeat == "weekly":
        return today.weekday() == 0
    elif template.repeat == "quarterly":
        return today.day == 1 and today.month in (1, 4, 7, 10)

    return True


# ── APScheduler Job Callback ────────────────────────────────────────

async def _dispatch_task_job(context: ContextTypes.DEFAULT_TYPE):
    """
    APScheduler callback — dispatches a single task by its template number.
    This is fired by run_once (test mode) or run_daily (normal mode).
    """
    task_number = context.job.data["task_number"]

    # Find the template
    template = next(
        (t for t in SHOP_TASK_TEMPLATES if t.task_number == task_number), None
    )

    if not template:
        logger.warning(f"Task job fired but template #{task_number} not found")
        return

    if not _should_run_today(template):
        logger.info(f"Task #{task_number} skipped — not scheduled for today")
        return

    logger.info(
        f"⏰ APScheduler firing T{task_number}: "
        f"{template.description[:40]} → {template.staff_id}"
    )
    await dispatch_task(context.bot, template)


# ── Schedule All Tasks ───────────────────────────────────────────────

def schedule_shop_tasks(job_queue, test_mode: bool = False) -> list[dict]:
    """
    Schedule all shop tasks as individual APScheduler jobs.

    Normal mode: run_daily at CSV trigger times
    Test mode: run_once at +1min, +3min, +5min, +7min, ...

    Returns a preview list of scheduled items.
    """
    # Clear existing shop task jobs
    for job in job_queue.jobs():
        if job.name and job.name.startswith("shop_task_"):
            job.schedule_removal()

    SHOP_DISPATCHED_TASK_NUMBERS.clear()

    automatable = get_automatable_templates()

    # Sort: fixed_time first (by time), then event/manual, then sequential
    def sort_key(t):
        if t.trigger_type == "fixed_time" and t.trigger_time:
            return (0, t.trigger_time)
        if t.trigger_type == "sequential":
            return (2, str(t.depends_on or 0).zfill(5))
        return (1, t.description)

    sorted_templates = sorted(automatable, key=sort_key)
    preview = []

    if test_mode:
        # ── Test Mode: +1min first, then +2min intervals ──────────
        offset = 1  # First task at +1 min
        now = now_ist()
        scheduled = 0

        for template in sorted_templates:
            if template.trigger_type == "sequential":
                # Sequential tasks fire via chain trigger, not scheduled
                preview.append({
                    "task_number": template.task_number,
                    "description": template.description,
                    "staff": SHOP_STAFF.get(template.staff_id, {}).get("name", template.staff_id),
                    "fire_at": f"after T{template.depends_on}",
                    "type": "sequential",
                })
                continue

            fire_time = now + timedelta(minutes=offset)
            fire_str = fire_time.strftime("%H:%M")

            job_queue.run_once(
                _dispatch_task_job,
                when=timedelta(minutes=offset),
                data={"task_number": template.task_number},
                name=f"shop_task_{template.task_number}",
            )

            preview.append({
                "task_number": template.task_number,
                "description": template.description,
                "staff": SHOP_STAFF.get(template.staff_id, {}).get("name", template.staff_id),
                "fire_at": fire_str,
                "type": "timed (test)",
            })

            scheduled += 1
            offset += 2  # +2 min intervals after first

        logger.info(
            f"🧪 Test mode: {scheduled} tasks scheduled, "
            f"first fires in 1 min ({(now + timedelta(minutes=1)).strftime('%H:%M')})"
        )

    else:
        # ── Normal Mode: run_daily at actual CSV times ────────────
        now = now_ist()
        scheduled = 0

        for template in sorted_templates:
            if template.trigger_type != "fixed_time" or not template.trigger_time:
                continue
            if not _should_run_today(template):
                continue

            try:
                h, m = map(int, template.trigger_time.split(":"))
                task_time = time(h, m, tzinfo=IST)
            except (ValueError, IndexError):
                logger.warning(f"Invalid time '{template.trigger_time}' for T{template.task_number}")
                continue

            job_queue.run_daily(
                _dispatch_task_job,
                time=task_time,
                data={"task_number": template.task_number},
                name=f"shop_task_{template.task_number}",
            )

            preview.append({
                "task_number": template.task_number,
                "description": template.description,
                "staff": SHOP_STAFF.get(template.staff_id, {}).get("name", template.staff_id),
                "fire_at": template.trigger_time,
                "type": "daily",
            })
            scheduled += 1

        logger.info(f"🏪 Normal mode: {scheduled} daily task jobs scheduled")

    return preview


# ── Task Dispatch ────────────────────────────────────────────────────

async def dispatch_task(bot: Bot, template: ShopTaskTemplate) -> dict | None:
    """
    Create a live task instance and send it to the staff member via Telegram.
    Returns the created task dict, or None if sending failed.
    """
    # Guard: don't dispatch twice
    if template.task_number in SHOP_DISPATCHED_TASK_NUMBERS:
        logger.info(f"  T{template.task_number} already dispatched today, skipping")
        return None

    staff_chat_id = _get_shop_staff_chat_id(template.staff_id)
    if not staff_chat_id:
        logger.warning(f"Cannot dispatch T{template.task_number}: "
                       f"{template.staff_id} not registered on Telegram")
        return None

    # Create instance
    task = create_daily_task(template)
    SHOP_DISPATCHED_TASK_NUMBERS.add(template.task_number)

    # Build message
    staff_name = SHOP_STAFF.get(template.staff_id, {}).get("name", template.staff_id)
    time_str = f" ({template.trigger_time})" if template.trigger_time else ""

    text = (
        f"🏪 *{staff_name}*, time for your task!\n\n"
        f"📋 {template.description}{time_str}\n\n"
        f"_Tap below when done:_"
    )

    buttons = [[
        InlineKeyboardButton("✅ Done", callback_data=f"shop_done_{task['id']}"),
        InlineKeyboardButton("⏳ Need More Time", callback_data=f"shop_delay_{task['id']}"),
    ]]

    try:
        await bot.send_message(
            chat_id=staff_chat_id,
            text=text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.MARKDOWN,
        )
        logger.info(f"✅ Dispatched T{template.task_number} to {template.staff_id}: "
                     f"{template.description[:40]}")
        return task
    except Exception as e:
        logger.error(f"Failed to dispatch T{template.task_number}: {e}")
        return None


# ── Chain Trigger ────────────────────────────────────────────────────

async def on_task_completed(bot: Bot, task_number: int):
    """
    Called when a task is confirmed complete.
    Fires any dependent tasks (AFTER T* pattern).
    """
    SHOP_COMPLETED_TASK_NUMBERS.add(task_number)
    logger.info(f"Task #{task_number} completed — checking for dependents")

    dependents = get_dependents(task_number)
    for dep_template in dependents:
        if _should_run_today(dep_template):
            logger.info(f"🔗 Chain-firing T{dep_template.task_number} "
                         f"(depends on T{task_number})")
            await dispatch_task(bot, dep_template)


# ── Delay Handling ───────────────────────────────────────────────────

async def on_task_delayed(bot: Bot, task_id: str, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle when staff taps 'Need More Time'.
    1. Notify HARIS (operational manager) + Owner immediately
    2. Schedule auto-reminder in 30 minutes
    """
    task = get_task_by_id(task_id)
    if not task:
        return

    staff_name = SHOP_STAFF.get(task["staff_id"], {}).get("name", task["staff_id"])

    # Notify Owner
    for owner_chat in _get_owner_chat_ids():
        await bot.send_message(
            chat_id=owner_chat,
            text=(
                f"⏳ *Delay Notification*\n\n"
                f"{staff_name} needs more time for:\n"
                f"📋 {task['description']}"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

    # Schedule auto-reminder in 30 minutes
    context.job_queue.run_once(
        _send_delay_reminder,
        when=timedelta(minutes=30),
        data={"task_id": task_id, "staff_id": task["staff_id"]},
        name=f"reminder_{task_id}",
    )

    logger.info(f"Delay recorded for task {task_id}, reminder scheduled in 30 min")


async def _send_delay_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Send a reminder to the staff member after 30 minutes."""
    data = context.job.data
    task_id = data["task_id"]
    staff_id = data["staff_id"]

    task = get_task_by_id(task_id)
    if not task or task["status"] in ("completed", "rejected"):
        return  # Already resolved

    staff_chat = _get_shop_staff_chat_id(staff_id)
    staff_name = SHOP_STAFF.get(staff_id, {}).get("name", staff_id)

    if staff_chat:
        buttons = [[
            InlineKeyboardButton("✅ Done", callback_data=f"shop_done_{task_id}"),
            InlineKeyboardButton("⏳ Need More Time", callback_data=f"shop_delay_{task_id}"),
        ]]

        await context.bot.send_message(
            chat_id=staff_chat,
            text=(
                f"🔔 *Reminder, {staff_name}!*\n\n"
                f"This task is still pending:\n"
                f"📋 {task['description']}\n\n"
                f"_30 minutes have passed since you requested more time._"
            ),
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.MARKDOWN,
        )

    # Notify Owner again
    for owner_chat in _get_owner_chat_ids():
        await context.bot.send_message(
            chat_id=owner_chat,
            text=(
                f"🔔 *Reminder Alert*\n\n"
                f"{staff_name}'s task is still pending after 30 min:\n"
                f"📋 {task['description']}"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )


# ── Morning Broadcast ────────────────────────────────────────────────

async def morning_broadcast(bot: Bot):
    """
    Send each staff member a summary of their day's schedule.
    This is informational only — individual tasks are dispatched at trigger time.
    """
    for staff_id, staff in SHOP_STAFF.items():

        staff_chat = _get_shop_staff_chat_id(staff_id)
        if not staff_chat:
            continue

        templates = get_templates_for_staff(staff_id)
        if not templates:
            continue

        # Filter to today's tasks
        today_templates = [t for t in templates if _should_run_today(t)]
        if not today_templates:
            continue

        # Sort by time (fixed time first, then sequential, then others)
        def sort_key(t: ShopTaskTemplate):
            if t.trigger_time:
                return (0, t.trigger_time)
            if t.trigger_type == "sequential":
                return (1, str(t.depends_on or 0).zfill(5))
            return (2, "")

        today_templates.sort(key=sort_key)

        lines = [f"🌅 *Good morning, {staff['name']}!*\n", "📋 *Today's Schedule:*\n"]

        for i, t in enumerate(today_templates, 1):
            if t.trigger_time:
                icon = "🕐"
                time_label = f" ({t.trigger_time})"
            elif t.trigger_type == "sequential":
                icon = "🔗"
                time_label = f" (after Task {t.depends_on})"
            else:
                icon = "📌"
                time_label = ""

            lines.append(f"  {i}. {icon} {t.description}{time_label}")

        lines.append(f"\n_You have {len(today_templates)} tasks today. Good luck!_ 💪")

        try:
            await bot.send_message(
                chat_id=staff_chat,
                text="\n".join(lines),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.error(f"Morning broadcast to {staff_id} failed: {e}")

    # Notify owner
    for owner_chat in _get_owner_chat_ids():
        total = len([t for t in get_automatable_templates() if _should_run_today(t)])
        staff_count = len(SHOP_STAFF)
        try:
            await bot.send_message(
                chat_id=owner_chat,
                text=(
                    f"🌅 *Good Morning, Owner!*\n\n"
                    f"📊 Today's overview:\n"
                    f"  👥 {staff_count} active staff members\n"
                    f"  📋 {total} tasks scheduled\n\n"
                    f"_Use /shopstatus to see detailed status._"
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.error(f"Morning broadcast to owner failed: {e}")


async def morning_broadcast_job(context: ContextTypes.DEFAULT_TYPE):
    """JobQueue wrapper for morning broadcast + reschedule daily tasks."""
    # Reset daily state at start of each day
    reset_daily_state()

    # Reload tasks (in case CSV was updated)
    try:
        load_shop_tasks()
    except Exception as e:
        logger.error(f"Failed to reload shop tasks: {e}")

    # Reschedule today's tasks
    schedule_shop_tasks(context.job_queue, test_mode=False)

    await morning_broadcast(context.bot)


# ── Daily Reset Job ──────────────────────────────────────────────────

async def daily_reset_job(context: ContextTypes.DEFAULT_TYPE):
    """Reset daily state — runs at midnight."""
    reset_daily_state()
    logger.info("Shop mode: daily state reset")
