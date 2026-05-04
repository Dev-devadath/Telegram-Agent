"""
Telegram Application builder.
Constructs the python-telegram-bot Application with all handlers.
Integrates the Shop Mode scheduler with the JobQueue.
"""

import os
import logging
from datetime import time
from telegram.ext import Application
from app.telegram.handlers import get_all_handlers

logger = logging.getLogger(__name__)


def build_application() -> Application:
    """Build and return the Telegram Application with all handlers registered."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN not set. "
            "Create a bot via @BotFather and add the token to .env"
        )

    bot_mode = os.environ.get("BOT_MODE", "resort").strip().lower()

    app = Application.builder().token(token).build()

    # Register handlers based on mode
    for handler in get_all_handlers():
        app.add_handler(handler)

    if bot_mode == "shop":
        _setup_shop_scheduler(app)
        logger.info("🏪 Bot Mode: SHOP")
    else:
        logger.info("🏨 Bot Mode: RESORT (default)")

    logger.info("Telegram bot application built successfully.")
    return app


def _setup_shop_scheduler(app: Application):
    """Set up shop mode scheduler jobs."""
    try:
        from app.shop_store import load_shop_tasks, IST
        from app.shop_scheduler import schedule_shop_tasks, morning_broadcast_job, daily_reset_job

        # Load task templates
        try:
            templates = load_shop_tasks()
            logger.info(f"🏪 Shop Mode: Loaded {len(templates)} task templates")
        except FileNotFoundError:
            logger.warning("🏪 Shop Mode: Task definitions not found, tasks not loaded")
            return
        except Exception as e:
            logger.error(f"🏪 Shop Mode: Failed to load tasks: {e}")
            return

        # Schedule individual task jobs at their trigger times (normal mode)
        preview = schedule_shop_tasks(app.job_queue, test_mode=False)
        logger.info(f"🏪 Shop Mode: {len(preview)} task jobs scheduled")

        # Schedule morning broadcast at 7:55 AM IST daily
        app.job_queue.run_daily(
            morning_broadcast_job,
            time=time(7, 55, tzinfo=IST),
            name="shop_morning_broadcast",
        )

        # Schedule daily reset at midnight IST
        app.job_queue.run_daily(
            daily_reset_job,
            time=time(0, 0, tzinfo=IST),
            name="shop_daily_reset",
        )

        logger.info("🏪 Shop Mode: All scheduler jobs registered")

    except ImportError as e:
        logger.warning(f"🏪 Shop Mode: Could not set up scheduler: {e}")
    except Exception as e:
        logger.error(f"🏪 Shop Mode: Scheduler setup failed: {e}")

