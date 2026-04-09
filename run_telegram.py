"""
Standalone entry point for the Telegram bot.
Run with: python run_telegram.py
"""

import os
import logging
from dotenv import load_dotenv

# Load env first — must happen before any app imports
load_dotenv()

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
# Silence noisy HTTP logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def main():
    """Start the Telegram bot."""
    from app.telegram.bot import build_application
    from app.telegram.registry import get_manager_chat_id

    # Validation
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("❌ TELEGRAM_BOT_TOKEN not set in .env")
        logger.error("   Create a bot via @BotFather and add the token.")
        return

    manager_id = get_manager_chat_id()
    if not manager_id:
        logger.warning("⚠️  MANAGER_CHAT_ID not set in .env")
        logger.warning("   The manager won't be recognized until this is set.")
        logger.warning("   Tip: Send /start to your bot, then check the logs for your chat_id.")

    logger.info("═" * 50)
    logger.info("🤖 AI Household Staff Manager — Telegram Bot")
    logger.info("═" * 50)
    logger.info(f"Manager chat ID: {manager_id or 'NOT SET'}")
    logger.info("Bot starting... Press Ctrl+C to stop.")
    logger.info("═" * 50)

    from telegram import Update

    app = build_application()
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
