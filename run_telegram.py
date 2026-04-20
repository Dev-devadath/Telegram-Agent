"""
Standalone entry point for the Telegram bot.

Supports two modes:
  - Webhook mode (for Render/Heroku): python run_telegram.py
    Requires RENDER_EXTERNAL_URL or WEBHOOK_URL in env.
  - Polling mode (for local dev): python run_telegram.py --poll
"""

import os
import sys
import logging
import secrets
from dotenv import load_dotenv

# Load env first — must happen before any app imports
load_dotenv()

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def main():
    """Start the Telegram bot."""
    from telegram import Update
    from app.telegram.bot import build_application
    from app.telegram.registry import get_manager_chat_ids

    # Validation
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("❌ TELEGRAM_BOT_TOKEN not set in .env")
        return

    manager_ids = get_manager_chat_ids()
    if not manager_ids:
        logger.warning("⚠️  MANAGER_CHAT_ID not set in .env")

    use_polling = "--poll" in sys.argv

    logger.info("═" * 50)
    logger.info("🤖 AI Household Staff Manager — Telegram Bot")
    logger.info("═" * 50)
    logger.info(
        f"Manager chat ID(s): {', '.join(str(i) for i in manager_ids) or 'NOT SET'}"
    )
    logger.info(f"Mode: {'POLLING (local)' if use_polling else 'WEBHOOK (production)'}")
    logger.info("═" * 50)

    if use_polling:
        # ── Local development: polling mode ─────────────────────
        app = build_application()
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    else:
        # ── Production: webhook mode (Render / Heroku) ──────────
        port = int(os.environ.get("PORT", "10000"))

        # Render sets RENDER_EXTERNAL_URL automatically
        webhook_url = os.environ.get(
            "WEBHOOK_URL",
            os.environ.get("RENDER_EXTERNAL_URL", ""),
        )

        if not webhook_url:
            logger.error("❌ No webhook URL found.")
            logger.error("   Set WEBHOOK_URL or RENDER_EXTERNAL_URL in env.")
            logger.error("   Or use --poll for local development.")
            return

        # Generate a secret token for webhook security
        secret_token = os.environ.get(
            "WEBHOOK_SECRET", secrets.token_urlsafe(32)
        )

        webhook_path = "/webhook"
        full_webhook_url = f"{webhook_url}{webhook_path}"

        logger.info(f"Webhook URL: {full_webhook_url}")
        logger.info(f"Listening on port: {port}")

        app = build_application()
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=webhook_path,
            secret_token=secret_token,
            webhook_url=full_webhook_url,
            allowed_updates=Update.ALL_TYPES,
        )


if __name__ == "__main__":
    main()
