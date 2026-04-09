"""
Telegram Application builder.
Constructs the python-telegram-bot Application with all handlers.
"""

import os
import logging
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

    app = Application.builder().token(token).build()

    # Register all handlers
    for handler in get_all_handlers():
        app.add_handler(handler)

    logger.info("Telegram bot application built successfully.")
    return app
