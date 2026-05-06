import logging

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import BOT_TOKEN
from handlers.admin import admin_callback, admin_panel, admin_text_handler
from handlers.manager import manager_verify_callback, report_callback, report_handler
from handlers.start import (
    REGISTER_ROLE_PREFIX,
    register_role_callback,
    registration_name_handler,
    start_handler,
)
from handlers.worker import (
    no_reason_handler,
    task_response_callback,
)
from scheduler import register_all_jobs
from store import ensure_data_file


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        "Commands:\n"
        "/start - Register or open your workspace\n"
        "/admin - Open admin panel\n"
        "/report - View reports (manager/admin)\n"
        "/help - Show this help"
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled exception: %s", context.error)


def main() -> None:
    if not BOT_TOKEN or BOT_TOKEN == "replace_with_bot_token":
        raise RuntimeError("Set BOT_TOKEN in .env before running the bot.")

    ensure_data_file()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("report", report_handler))
    app.add_handler(CommandHandler("help", help_handler))

    app.add_handler(CallbackQueryHandler(register_role_callback, pattern=f"^{REGISTER_ROLE_PREFIX}"))
    app.add_handler(CallbackQueryHandler(task_response_callback, pattern=r"^task_(yes|no|extend):"))
    app.add_handler(CallbackQueryHandler(manager_verify_callback, pattern=r"^(verify|reject):"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^admin:"))
    app.add_handler(CallbackQueryHandler(report_callback, pattern=r"^report_(role|period):"))

    # Text handlers depend on internal user states, so they safely no-op when inactive.
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, admin_text_handler),
        group=0,
    )
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, no_reason_handler),
        group=1,
    )
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, registration_name_handler),
        group=2,
    )

    app.add_error_handler(error_handler)
    register_all_jobs(app)
    logger.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
