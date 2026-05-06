import logging
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackContext

import store
from config import TIMEZONE


TASK_JOB_PREFIX = "task_daily:"
EXTEND_JOB_PREFIX = "task_extend:"
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


def _task_keyboard(run_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Yes", callback_data=f"task_yes:{run_id}"),
                InlineKeyboardButton("No", callback_data=f"task_no:{run_id}"),
                InlineKeyboardButton("Extend 30 mins", callback_data=f"task_extend:{run_id}"),
            ]
        ]
    )


def clear_all_task_jobs(application: Application) -> None:
    for job in application.job_queue.jobs():
        if job.name.startswith(TASK_JOB_PREFIX) or job.name.startswith(EXTEND_JOB_PREFIX):
            job.schedule_removal()


def schedule_task_job(application: Application, task: dict) -> None:
    run_time = _parse_time(task["time"])
    for existing in application.job_queue.get_jobs_by_name(f"{TASK_JOB_PREFIX}{task['id']}"):
        existing.schedule_removal()
    application.job_queue.run_daily(
        daily_task_callback,
        time=run_time,
        data={"task_id": task["id"]},
        name=f"{TASK_JOB_PREFIX}{task['id']}",
    )
    logger.info(
        "Scheduled task job task_id=%s at %s (tz=%s)",
        task["id"],
        task["time"],
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
        data={"run_id": run_id},
        name=f"{EXTEND_JOB_PREFIX}{run_id}:{datetime.utcnow().timestamp()}",
    )


async def daily_task_callback(context: CallbackContext) -> None:
    task_id = context.job.data["task_id"]
    task = store.get_task_by_id(task_id)
    if not task or not task.get("active", True):
        logger.info("Skipped firing task_id=%s (missing/inactive).", task_id)
        return
    scheduled_for = datetime.utcnow().replace(microsecond=0).isoformat()
    logger.info("Firing task_id=%s scheduled_for=%s", task_id, scheduled_for)
    run = store.add_task_run(task, scheduled_for=scheduled_for)
    await _send_run_to_worker(context, run)


async def extension_task_callback(context: CallbackContext) -> None:
    run_id = context.job.data["run_id"]
    run = store.get_task_run(run_id)
    if not run:
        return
    store.update_task_run(
        run_id,
        {
            "status": "sent_to_worker",
            "scheduled_for": (datetime.utcnow() + timedelta(minutes=30))
            .replace(microsecond=0)
            .isoformat(),
        },
    )
    run = store.get_task_run(run_id)
    await _send_run_to_worker(context, run, is_reminder=True)


async def _send_run_to_worker(
    context: CallbackContext,
    run: dict,
    is_reminder: bool = False,
) -> None:
    task = store.get_task_by_id(run["task_id"])
    worker = store.get_user_by_role(run["worker_role"])
    if not task:
        logger.warning("Run %s has missing task %s", run.get("id"), run.get("task_id"))
        return
    if not worker and not store.get_settings().get("test_mode"):
        logger.info(
            "Run %s not delivered: no worker mapped to role=%s and test mode off.",
            run.get("id"),
            run.get("worker_role"),
        )
        return

    settings = store.get_settings()
    chat_id = (
        settings.get("test_telegram_id")
        if settings.get("test_mode")
        else worker["telegram_id"]
    )
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
