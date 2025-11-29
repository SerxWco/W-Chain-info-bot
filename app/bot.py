import logging

from telegram import BotCommand
from telegram.ext import Application, CommandHandler

from app.config import Settings
from app.handlers.commands import CommandHandlers
from app.services import AnalyticsService

logger = logging.getLogger(__name__)
COMMAND_MENU = [
    BotCommand("start", "Welcome message and command list"),
    BotCommand("help", "Quick reminder of available commands"),
    BotCommand("wco", "WCO price and supply analytics"),
    BotCommand("wave", "WAVE token snapshot"),
    BotCommand("price", "Multi-token price lookup"),
    BotCommand("stats", "Network throughput and gas metrics"),
]


async def _register_bot_commands(application: Application) -> None:
    await application.bot.set_my_commands(COMMAND_MENU)


def build_application(settings: Settings) -> Application:
    analytics = AnalyticsService(settings)
    command_handlers = CommandHandlers(analytics, settings)

    application = (
        Application.builder()
        .token(settings.telegram_token)
        .post_init(_register_bot_commands)
        .build()
    )

    application.add_handler(CommandHandler("start", command_handlers.start))
    application.add_handler(CommandHandler("help", command_handlers.start))
    application.add_handler(CommandHandler("wco", command_handlers.wco))
    application.add_handler(CommandHandler("wave", command_handlers.wave))
    application.add_handler(CommandHandler("price", command_handlers.price))
    application.add_handler(CommandHandler("stats", command_handlers.stats))

    logger.info("Telegram application wired with command handlers.")
    return application

