import asyncio
import logging
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackContext

import db_async
import store
from config import TASK_REMINDER_MINUTES, TIMEZONE
from performance import OperationTimer


TASK_JOB_PREFIX = "task_daily:"
EXTEND_JOB_PREFIX = "task_extend:"
REMINDER_JOB_PREFIX = "task_reminder:"
logger = logging.getLogger(__name__)


def _get_scheduler_tz():
    if TIMEZONE:
        try:
            return ZoneInfo(TIMEZONE)
        except Exception:
            logger.warning("Invalid TIMEZONE=%s, falling back to local timezone.", TIMEZONE)
    return datetime.now().astimezone().tzinfo


def _parse_time(value: str) -> time:
    hour, minute = value.split(":")
    return time(hour=int(hour), minute=int(minute), tzinfo=_get_scheduler_tz())


def _next_run_datetime(value: str) -> datetime:
    parsed_time = _parse_time(value)
    now = datetime.now(_get_scheduler_tz())
    run_at = datetime.combine(now.date(), parsed_time, tzinfo=_get_scheduler_tz())
    if run_at <= now:
        run_at += timedelta(days=1)
    return run_at


def _run_datetime_for_task(task: dict) -> datetime:
    if task.get("recurrence") == "once" and task.get("scheduled_date"):
        parsed_time = _parse_time(task["time"])
        run_date = datetime.strptime(task["scheduled_date"], "%Y-%m-%d").date()
        return datetime.combine(run_date, parsed_time, tzinfo=_get_scheduler_tz())
    return _next_run_datetime(task["time"])


def _task_keyboard(run_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Yes", callback_data=f"task_yes:{run_id}"),
                InlineKeyboardButton("No", callback_data=f"task_no:{run_id}"),
            ],
            [
                InlineKeyboardButton("Note", callback_data=f"task_note:{run_id}"),
                InlineKeyboardButton("Extend", callback_data=f"task_extend:{run_id}"),
            ],
        ]
    )


def clear_all_task_jobs(application: Application) -> None:
    for job in application.job_queue.jobs():
        if (
            job.name.startswith(TASK_JOB_PREFIX)
            or job.name.startswith(EXTEND_JOB_PREFIX)
            or job.name.startswith(REMINDER_JOB_PREFIX)
        ):
            job.schedule_removal()


def schedule_task_job(application: Application, task: dict) -> None:
    for existing in application.job_queue.get_jobs_by_name(f"{TASK_JOB_PREFIX}{task['id']}"):
        existing.schedule_removal()
    recurrence = task.get("recurrence", "daily")
    if recurrence == "after_task":
        logger.info("Task %s is dependency-based and has no clock schedule.", task["id"])
        return

    run_time = _parse_time(task["time"])
    if recurrence == "once":
        application.job_queue.run_once(
            daily_task_callback,
            when=_run_datetime_for_task(task),
            data={"task_id": task["id"]},
            name=f"{TASK_JOB_PREFIX}{task['id']}",
        )
    else:
        application.job_queue.run_daily(
            daily_task_callback,
            time=run_time,
            data={"task_id": task["id"]},
            name=f"{TASK_JOB_PREFIX}{task['id']}",
        )
    logger.info(
        "Scheduled task job task_id=%s at %s recurrence=%s (tz=%s)",
        task["id"],
        task["time"],
        recurrence,
        run_time.tzinfo,
    )


def register_all_jobs(application: Application) -> None:
    clear_all_task_jobs(application)
    for task in store.list_active_tasks():
        schedule_task_job(application, task)


def schedule_extension_for_run(application: Application, run_id: str, minutes: int) -> None:
    application.job_queue.run_once(
        extension_task_callback,
        when=minutes * 60,
        data={"run_id": run_id, "minutes": minutes},
        name=f"{EXTEND_JOB_PREFIX}{run_id}:{datetime.utcnow().timestamp()}",
    )


def schedule_no_response_reminder(application: Application, run_id: str) -> None:
    if TASK_REMINDER_MINUTES <= 0:
        return
    application.job_queue.run_once(
        no_response_reminder_callback,
        when=TASK_REMINDER_MINUTES * 60,
        data={"run_id": run_id},
        name=f"{REMINDER_JOB_PREFIX}{run_id}",
    )


async def _send_delivery_message(
    context: CallbackContext,
    delivery: dict,
    is_reminder: bool = False,
) -> None:
    run = delivery["run"]
    task = delivery["task"]
    chat_id = delivery.get("chat_id")
    if not chat_id:
        logger.warning("Run %s not delivered: target chat_id missing.", run.get("id"))
        return

    title_prefix = "Task Reminder" if is_reminder else "Task Assigned"
    text = (
        f"{title_prefix}\n"
        f"Role: {run['worker_role']}\n"
        f"Task: {task['title']}\n"
        f"Description: {task['description']}\n\n"
        "Have you done this?"
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=_task_keyboard(run["id"]),
    )
    logger.info("Delivered run_id=%s to chat_id=%s", run.get("id"), chat_id)


async def fire_task_now(
    context: CallbackContext,
    task: dict,
    triggered_by_run_id: str | None = None,
) -> dict | None:
    if not task or not task.get("active", True):
        return None
    scheduled_for = datetime.utcnow().replace(microsecond=0).isoformat()
    logger.info(
        "Firing task_id=%s scheduled_for=%s triggered_by_run_id=%s",
        task["id"],
        scheduled_for,
        triggered_by_run_id,
    )
    with OperationTimer("scheduler.fire_task_now", task_id=task["id"]):
        delivery = await db_async.db_call(
            store.create_task_run_with_delivery_context,
            task,
            scheduled_for,
        )
        if not delivery:
            return None
        await _send_delivery_message(context, delivery)
        schedule_no_response_reminder(context.application, delivery["run"]["id"])
        return delivery["run"]


async def fire_dependent_tasks_background(
    context: CallbackContext,
    dependent_tasks: list[dict],
    parent_run_id: str,
) -> int:
    fired = 0
    semaphore = asyncio.Semaphore(3)

    async def _fire_one(dependent_task: dict) -> bool:
        async with semaphore:
            try:
                child_run = await fire_task_now(
                    context,
                    dependent_task,
                    triggered_by_run_id=parent_run_id,
                )
                return child_run is not None
            except Exception:
                logger.exception(
                    "Failed to fire dependent task task_id=%s parent_run_id=%s",
                    dependent_task.get("id"),
                    parent_run_id,
                )
                return False

    if not dependent_tasks:
        return 0

    results = await asyncio.gather(*(_fire_one(task) for task in dependent_tasks))
    fired = sum(1 for result in results if result)
    logger.info(
        "Background dependent task firing complete parent_run_id=%s fired=%s",
        parent_run_id,
        fired,
    )
    return fired


async def daily_task_callback(context: CallbackContext) -> None:
    task_id = context.job.data["task_id"]
    with OperationTimer("scheduler.daily_task_callback", task_id=task_id):
        task = await db_async.db_call(store.get_task_by_id, task_id)
        if not task or not task.get("active", True):
            logger.info("Skipped firing task_id=%s (missing/inactive).", task_id)
            return
        if task.get("recurrence") == "weekly":
            expected_weekday = task.get("weekday")
            current_weekday = datetime.now(_get_scheduler_tz()).weekday()
            if expected_weekday is not None and expected_weekday != current_weekday:
                logger.info(
                    "Skipped weekly task_id=%s on weekday=%s expected=%s",
                    task_id,
                    current_weekday,
                    expected_weekday,
                )
                return
        await fire_task_now(context, task)
        if task.get("recurrence") == "once":
            await db_async.db_call(store.update_task, task_id, {"active": False})


async def extension_task_callback(context: CallbackContext) -> None:
    run_id = context.job.data["run_id"]
    with OperationTimer("scheduler.extension_task_callback", run_id=run_id):
        run = await db_async.db_call(store.get_task_run, run_id)
        if not run:
            return
        await db_async.db_call(
            store.update_task_run,
            run_id,
            {
                "status": "sent_to_worker",
                "scheduled_for": datetime.utcnow().replace(microsecond=0).isoformat(),
            },
        )
        delivery = await db_async.db_call(store.get_run_delivery_context, run_id)
        if not delivery:
            logger.info("Extension reminder skipped for run_id=%s", run_id)
            return
        await _send_delivery_message(
            context,
            {
                "run": delivery["run"],
                "task": {
                    "title": delivery["task_title"],
                    "description": delivery["task_description"],
                },
                "chat_id": delivery["chat_id"],
            },
            is_reminder=True,
        )
        schedule_no_response_reminder(context.application, run_id)


async def no_response_reminder_callback(context: CallbackContext) -> None:
    run_id = context.job.data["run_id"]
    with OperationTimer("scheduler.no_response_reminder_callback", run_id=run_id):
        run = await db_async.db_call(store.get_task_run, run_id)
        if not run or (run.get("worker_response") and run.get("status") != "sent_to_worker"):
            return
        delivery = await db_async.db_call(store.get_run_delivery_context, run_id)
        if not delivery:
            logger.info("No-response reminder skipped for run_id=%s", run_id)
            return
        await _send_delivery_message(
            context,
            {
                "run": delivery["run"],
                "task": {
                    "title": delivery["task_title"],
                    "description": delivery["task_description"],
                },
                "chat_id": delivery["chat_id"],
            },
            is_reminder=True,
        )
