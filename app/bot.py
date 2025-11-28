import logging

from telegram.ext import Application, CommandHandler

from app.config import Settings
from app.handlers.commands import CommandHandlers
from app.services import AnalyticsService

logger = logging.getLogger(__name__)


def build_application(settings: Settings) -> Application:
    analytics = AnalyticsService(settings)
    command_handlers = CommandHandlers(analytics, settings)

    application = Application.builder().token(settings.telegram_token).build()

    application.add_handler(CommandHandler("start", command_handlers.start))
    application.add_handler(CommandHandler("help", command_handlers.start))
    application.add_handler(CommandHandler("wco", command_handlers.wco))
    application.add_handler(CommandHandler("wave", command_handlers.wave))
    application.add_handler(CommandHandler("tokens", command_handlers.tokens))
    application.add_handler(CommandHandler("price", command_handlers.price))
    application.add_handler(CommandHandler("stats", command_handlers.stats))

    logger.info("Telegram application wired with command handlers.")
    return application

