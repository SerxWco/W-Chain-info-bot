import logging
from datetime import time

from telegram import BotCommand
from telegram.ext import Application, CommandHandler

from app.config import Settings
from app.handlers.commands import CommandHandlers
from app.services import AnalyticsService, DailyReportService
from app.services.buyback_alerts import BuybackAlertService
from app.services.exchange_flow_alerts import ExchangeFlowAlertService
from app.services.wco_dex_alerts import WCODexAlertService
from app.services.wco_whale_alert import WCOWhaleAlert
from app.services.wswap_liquidity_alerts import WSwapLiquidityAlertService

logger = logging.getLogger(__name__)
COMMAND_MENU = [
    BotCommand("start", "Welcome message and command list"),
    BotCommand("help", "Quick reminder of available commands"),
    BotCommand("wco", "WCO price and supply analytics"),
    BotCommand("wave", "WAVE token snapshot"),
    BotCommand("price", "Multi-token price lookup"),
    BotCommand("stats", "Network throughput and gas metrics"),
    BotCommand("tokens", "Key W-Chain ecosystem assets"),
    BotCommand("token", "Token details lookup (e.g. /token SOL)"),
    BotCommand("buybackalerts", "Toggle buyback alerts in this chat"),
    BotCommand("buybackstatus", "Show buyback alert status"),
    BotCommand("buybacktest", "Send a test buyback alert message"),
    BotCommand("dexalerts", "Toggle WCO DEX alerts (admin only)"),
    BotCommand("dexstatus", "Show WCO DEX alert status"),
    BotCommand("liqalerts", "Toggle liquidity alerts (admin only)"),
    BotCommand("liqstatus", "Show liquidity alert status"),
    BotCommand("pairs", "List all WCO pairs on W-Swap"),
    BotCommand("dailyreport", "Trigger daily metrics report manually"),
]


def build_application(settings: Settings) -> Application:
    analytics = AnalyticsService(settings)
    buyback_alerts = BuybackAlertService(settings, analytics.wchain)
    whale_alerts = WCOWhaleAlert(settings, analytics.wchain)
    exchange_flow_alerts = ExchangeFlowAlertService(settings, analytics.wchain)
    wco_dex_alerts = WCODexAlertService(settings, analytics.wchain)
    wswap_liquidity_alerts = WSwapLiquidityAlertService(settings, analytics.wchain)
    daily_report = DailyReportService(settings, analytics.wchain)
    command_handlers = CommandHandlers(
        analytics, settings, buyback_alerts, wco_dex_alerts, wswap_liquidity_alerts, daily_report
    )

    async def _post_init(application: Application) -> None:
        await application.bot.set_my_commands(COMMAND_MENU)

        application.bot_data["buyback_alerts"] = buyback_alerts
        await buyback_alerts.ensure_initialized()

        application.bot_data["whale_alerts"] = whale_alerts
        await whale_alerts.ensure_initialized()

        application.bot_data["exchange_flow_alerts"] = exchange_flow_alerts
        await exchange_flow_alerts.ensure_initialized()

        application.bot_data["wco_dex_alerts"] = wco_dex_alerts
        await wco_dex_alerts.ensure_initialized()

        application.bot_data["wswap_liquidity_alerts"] = wswap_liquidity_alerts
        await wswap_liquidity_alerts.ensure_initialized()

        application.bot_data["daily_report"] = daily_report
        await daily_report.ensure_initialized()

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

            application.job_queue.run_repeating(
                wco_dex_alerts.job_callback,
                interval=settings.wco_dex_poll_seconds,
                first=10,
                name="wco_dex_alerts",
            )
            logger.info(
                "WCO DEX watcher enabled (interval=%ss channel=%s).",
                settings.wco_dex_poll_seconds,
                settings.wco_dex_alert_channel_id or "unset",
            )

            application.job_queue.run_repeating(
                wswap_liquidity_alerts.job_callback,
                interval=settings.wswap_liquidity_poll_seconds,
                first=15,
                name="wswap_liquidity_alerts",
            )
            logger.info(
                "W-Swap liquidity watcher enabled (factory=%s interval=%ss channel=%s).",
                settings.wswap_factory_address,
                settings.wswap_liquidity_poll_seconds,
                settings.wswap_liquidity_alert_channel_id or "unset",
            )

            # Schedule daily report at configured time (default 22:00 UTC)
            report_time = time(
                hour=settings.daily_report_hour,
                minute=settings.daily_report_minute,
            )
            application.job_queue.run_daily(
                daily_report.job_callback,
                time=report_time,
                name="daily_report",
            )
            logger.info(
                "Daily report scheduled at %02d:%02d UTC (channel=%s).",
                settings.daily_report_hour,
                settings.daily_report_minute,
                settings.daily_report_channel_id or "unset",
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
    application.add_handler(CommandHandler("dexalerts", command_handlers.dexalerts))
    application.add_handler(CommandHandler("dexstatus", command_handlers.dexstatus))
    application.add_handler(CommandHandler("liqalerts", command_handlers.liqalerts))
    application.add_handler(CommandHandler("liqstatus", command_handlers.liqstatus))
    application.add_handler(CommandHandler("pairs", command_handlers.pairs))
    application.add_handler(CommandHandler("dailyreport", command_handlers.dailyreport))

    logger.info("Telegram application wired with command handlers.")
    return application

