import logging

from telegram import BotCommand
from telegram.ext import Application, CommandHandler

from app.config import Settings
from app.handlers.commands import CommandHandlers
from app.services import AnalyticsService
from app.services.buyback_alerts import BuybackAlertService
from app.services.exchange_flow_alerts import ExchangeFlowAlertService
from app.services.wco_whale_alert import WCOWhaleAlert

logger = logging.getLogger(__name__)
COMMAND_MENU = [
    BotCommand("start", "Welcome message and command list"),
    BotCommand("help", "Quick reminder of available commands"),
    BotCommand("wco", "WCO price and supply analytics"),
    BotCommand("wave", "WAVE token snapshot"),
    BotCommand("price", "Multi-token price lookup"),
    BotCommand("stats", "Network throughput and gas metrics"),
    BotCommand("tokens", "Key W-Chain ecosystem assets"),
    BotCommand("token", "Token details - /token <symbol>"),
    BotCommand("buybackalerts", "Toggle buyback alerts in this chat"),
    BotCommand("buybackstatus", "Show buyback alert status"),
    BotCommand("buybacktest", "Send a test buyback alert message"),
]


def build_application(settings: Settings) -> Application:
    analytics = AnalyticsService(settings)
    buyback_alerts = BuybackAlertService(settings, analytics.wchain)
    whale_alerts = WCOWhaleAlert(settings, analytics.wchain)
    exchange_flow_alerts = ExchangeFlowAlertService(settings, analytics.wchain)
    command_handlers = CommandHandlers(analytics, settings, buyback_alerts)

    async def _post_init(application: Application) -> None:
        await application.bot.set_my_commands(COMMAND_MENU)

        application.bot_data["buyback_alerts"] = buyback_alerts
        await buyback_alerts.ensure_initialized()

        application.bot_data["whale_alerts"] = whale_alerts
        await whale_alerts.ensure_initialized()

        application.bot_data["exchange_flow_alerts"] = exchange_flow_alerts
        await exchange_flow_alerts.ensure_initialized()

        if application.job_queue:
            application.job_queue.run_repeating(
                buyback_alerts.job_callback,
                interval=settings.buyback_poll_seconds,
                first=5,
                name="buyback_alerts",
            )
            logger.info(
                "Buyback watcher enabled (wallet=%s interval=%ss).",
                settings.buyback_wallet_address,
                settings.buyback_poll_seconds,
            )

            application.job_queue.run_repeating(
                whale_alerts.job_callback,
                interval=settings.whale_poll_seconds,
                first=5,
                name="wco_whale_alerts",
            )
            logger.info(
                "WCO whale watcher enabled (router=%s interval=%ss channel=%s).",
                settings.whale_router_address,
                settings.whale_poll_seconds,
                settings.whale_alert_channel_id or "unset",
            )

            application.job_queue.run_repeating(
                exchange_flow_alerts.job_callback,
                interval=settings.exchange_flow_poll_seconds,
                first=5,
                name="exchange_flow_alerts",
            )
            logger.info(
                "Exchange flow watcher enabled (interval=%ss channel=%s threshold=%s WCO).",
                settings.exchange_flow_poll_seconds,
                settings.exchange_flow_alert_channel_id or "unset",
                settings.exchange_flow_threshold_wco,
            )
        else:
            logger.warning("JobQueue not available; buyback alerts will not run.")

    application = (
        Application.builder()
        .token(settings.telegram_token)
        .post_init(_post_init)
        .build()
    )

    application.add_handler(CommandHandler("start", command_handlers.start))
    application.add_handler(CommandHandler("help", command_handlers.start))
    application.add_handler(CommandHandler("wco", command_handlers.wco))
    application.add_handler(CommandHandler("wave", command_handlers.wave))
    application.add_handler(CommandHandler("price", command_handlers.price))
    application.add_handler(CommandHandler("stats", command_handlers.stats))
    application.add_handler(CommandHandler("tokens", command_handlers.tokens))
    application.add_handler(CommandHandler("token", command_handlers.token))
    application.add_handler(CommandHandler("buybackalerts", command_handlers.buybackalerts))
    application.add_handler(CommandHandler("buybackstatus", command_handlers.buybackstatus))
    application.add_handler(CommandHandler("buybacktest", command_handlers.buybacktest))

    logger.info("Telegram application wired with command handlers.")
    return application

