"""
Standalone entry point for the Telegram bot.

Supports two modes:
  - Webhook mode (for Render/Heroku): python run_telegram.py
    Requires RENDER_EXTERNAL_URL or WEBHOOK_URL in env.
  - Polling mode (for local dev): python run_telegram.py --poll
"""

import os
import sys
import hashlib
import hmac
import logging
import traceback
from datetime import datetime, timezone
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

# ── Track boot time for health checks ───────────────────────────────
_boot_time: datetime | None = None
_error_count: int = 0


def _derive_webhook_secret(token: str) -> str:
    """
    Derive a deterministic webhook secret from the bot token.
    This ensures the SAME secret survives process restarts on Render,
    so Telegram's webhook calls never get a 403 mismatch.
    """
    return hmac.new(
        key=b"tg-webhook-secret",
        msg=token.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()[:43]  # URL-safe length, matches token_urlsafe(32)


def main():
    """Start the Telegram bot."""
    global _boot_time, _error_count

    from telegram import Update
    from telegram.ext import Application
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
        # Add global error handler for polling mode too
        async def _polling_error_handler(update, context):
            global _error_count
            _error_count += 1
            logger.error(
                f"Exception in handler (total errors: {_error_count}): "
                f"{context.error}",
                exc_info=context.error,
            )
        app.add_error_handler(_polling_error_handler)
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

        # Deterministic secret: survives restarts without WEBHOOK_SECRET env var
        secret_token = os.environ.get(
            "WEBHOOK_SECRET",
            _derive_webhook_secret(token),
        )

        webhook_path = "/webhook"
        full_webhook_url = f"{webhook_url}{webhook_path}"

        logger.info(f"Webhook URL: {full_webhook_url}")
        logger.info(f"Listening on port: {port}")
        logger.info(f"Webhook secret: {'(from env)' if os.environ.get('WEBHOOK_SECRET') else '(derived from token — deterministic)'}")

        import uvicorn
        from fastapi import FastAPI, Request, Response
        from contextlib import asynccontextmanager

        app_ptb = build_application()

        # ── Global error handler: prevents silent crashes ───────
        async def _error_handler(update, context):
            global _error_count
            _error_count += 1
            logger.error(
                f"Exception in handler (total errors: {_error_count}): "
                f"{context.error}",
                exc_info=context.error,
            )
            # Try to notify the user that something went wrong
            if update and update.effective_chat:
                try:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text="⚠️ Something went wrong processing your request. Please try again.",
                    )
                except Exception:
                    pass  # Don't let error notification crash the error handler

        app_ptb.add_error_handler(_error_handler)

        @asynccontextmanager
        async def lifespan(_app: FastAPI):
            global _boot_time
            _boot_time = datetime.now(timezone.utc)

            # Always (re-)set webhook on startup — ensures secret matches
            logger.info("Setting webhook on Telegram...")
            await app_ptb.bot.set_webhook(
                url=full_webhook_url,
                secret_token=secret_token,
                allowed_updates=Update.ALL_TYPES,
            )
            logger.info("✅ Webhook set successfully")

            # Start the PTB application so it can process the update queue
            async with app_ptb:
                await app_ptb.start()
                logger.info("✅ PTB Application started — ready to process updates")
                yield
                logger.info("Shutting down PTB Application...")
                await app_ptb.stop()
                # NOTE: Do NOT call delete_webhook() here!
                # On Render rolling deploys, the old process shuts down AFTER
                # the new one starts. Deleting the webhook here would nuke the
                # webhook that the new process just registered, killing the bot.

        fastapi_app = FastAPI(lifespan=lifespan)

        @fastapi_app.post(webhook_path)
        async def telegram_webhook(request: Request):
            # Verify secret token
            secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
            if secret_header != secret_token:
                got = (secret_header or "None")[:8]
                logger.warning(
                    f"Webhook 403: secret mismatch "
                    f"(got '{got}...' expected '{secret_token[:8]}...')"
                )
                return Response(status_code=403)

            try:
                data = await request.json()
                update = Update.de_json(data=data, bot=app_ptb.bot)

                # ── Debug: log every incoming update ──
                update_type = "unknown"
                chat_id = None
                text_preview = ""
                if update.message:
                    update_type = "message"
                    chat_id = update.message.chat_id
                    text_preview = (update.message.text or "")[:40]
                elif update.callback_query:
                    update_type = "callback"
                    chat_id = update.callback_query.message.chat_id if update.callback_query.message else None
                    text_preview = update.callback_query.data or ""

                queue_size = app_ptb.update_queue.qsize()
                logger.info(
                    f"[WEBHOOK] update_id={update.update_id} type={update_type} "
                    f"chat={chat_id} text='{text_preview}' queue_size={queue_size}"
                )

                await app_ptb.update_queue.put(update)
                return Response(status_code=200)
            except Exception as e:
                logger.error(f"Failed to process webhook update: {e}")
                traceback.print_exc()
                return Response(status_code=200)  # Return 200 to avoid Telegram retries

        @fastapi_app.get("/status")
        @fastapi_app.get("/wake")
        async def wake_status():
            """Enhanced health endpoint with PTB state info."""
            uptime = None
            if _boot_time:
                delta = datetime.now(timezone.utc) - _boot_time
                uptime = str(delta).split(".")[0]  # Remove microseconds

            return {
                "status": "awake",
                "message": "Server is up and running.",
                "boot_time": _boot_time.isoformat() if _boot_time else None,
                "uptime": uptime,
                "errors_since_boot": _error_count,
                "ptb_running": app_ptb.running,
                "update_queue_size": app_ptb.update_queue.qsize()
                    if hasattr(app_ptb, "update_queue") else None,
            }

        logger.info(f"Starting custom FastAPI server on port {port}")
        uvicorn.run(fastapi_app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
