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

# Single source of truth for command menu and registration order.
COMMAND_SPECS = [
    ("start", "start", "Welcome message and command list"),
    ("help", "start", "Quick reminder of available commands"),
    ("wco", "wco", "WCO price and supply analytics"),
    ("wave", "wave", "WAVE token snapshot"),
    ("price", "price", "Multi-token price lookup"),
    ("token", "token", "Token details lookup (e.g. /token SOL)"),
    ("tokens", "tokens", "Key W-Chain ecosystem assets"),
    ("stats", "stats", "Network throughput and gas metrics"),
    ("dailyreport", "dailyreport", "Trigger daily metrics report manually"),
    ("buybackstatus", "buybackstatus", "Show buyback alert status"),
    ("buybackalerts", "buybackalerts", "Toggle buyback alerts in this chat"),
    ("buybacktest", "buybacktest", "Send a test buyback alert message"),
    ("flowstatus", "flowstatus", "Show exchange flow alert status"),
    ("flowalerts", "flowalerts", "Toggle exchange flow alerts (admin only)"),
    ("dexstatus", "dexstatus", "Show WCO DEX alert status"),
    ("dexalerts", "dexalerts", "Toggle WCO DEX alerts (admin only)"),
    ("liqstatus", "liqstatus", "Show liquidity alert status"),
    ("liqalerts", "liqalerts", "Toggle liquidity alerts (admin only)"),
    ("pairs", "pairs", "List all WCO pairs on W-Swap"),
]
COMMAND_MENU = [BotCommand(command, description) for command, _, description in COMMAND_SPECS]


def _register_command_handlers(application: Application, command_handlers: CommandHandlers) -> None:
    for command, handler_name, _ in COMMAND_SPECS:
        application.add_handler(CommandHandler(command, getattr(command_handlers, handler_name)))


def _schedule_job_queue_jobs(
    application: Application,
    settings: Settings,
    buyback_alerts: BuybackAlertService,
    whale_alerts: WCOWhaleAlert,
    exchange_flow_alerts: ExchangeFlowAlertService,
    wco_dex_alerts: WCODexAlertService,
    wswap_liquidity_alerts: WSwapLiquidityAlertService,
    daily_report: DailyReportService,
) -> None:
    job_queue = application.job_queue
    if not job_queue:
        logger.warning("JobQueue not available; scheduled alert watchers and daily report will not run.")
        return

    # Always-on jobs
    job_queue.run_repeating(
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

    # Schedule daily report at configured time (default 23:00 UTC)
    report_time = time(
        hour=settings.daily_report_hour,
        minute=settings.daily_report_minute,
    )
    job_queue.run_daily(
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

    if not settings.movement_alerts_enabled:
        return

    # Optional movement watchers
    movement_jobs = [
        (
            whale_alerts.job_callback,
            settings.whale_poll_seconds,
            5,
            "wco_whale_alerts",
            "WCO whale watcher enabled (router=%s interval=%ss channel=%s).",
            (
                settings.whale_router_address,
                settings.whale_poll_seconds,
                settings.whale_alert_channel_id or "unset",
            ),
        ),
        (
            exchange_flow_alerts.job_callback,
            settings.exchange_flow_poll_seconds,
            5,
            "exchange_flow_alerts",
            "Exchange flow watcher enabled (interval=%ss channel=%s threshold=%s WCO).",
            (
                settings.exchange_flow_poll_seconds,
                settings.exchange_flow_alert_channel_id or "unset",
                settings.exchange_flow_threshold_wco,
            ),
        ),
        (
            wco_dex_alerts.job_callback,
            settings.wco_dex_poll_seconds,
            10,
            "wco_dex_alerts",
            "WCO DEX watcher enabled (interval=%ss channel=%s).",
            (
                settings.wco_dex_poll_seconds,
                settings.wco_dex_alert_channel_id or "unset",
            ),
        ),
        (
            wswap_liquidity_alerts.job_callback,
            settings.wswap_liquidity_poll_seconds,
            15,
            "wswap_liquidity_alerts",
            "W-Swap liquidity watcher enabled (factory=%s interval=%ss channel=%s).",
            (
                settings.wswap_factory_address,
                settings.wswap_liquidity_poll_seconds,
                settings.wswap_liquidity_alert_channel_id or "unset",
            ),
        ),
    ]
    for callback, interval, first, name, message, args in movement_jobs:
        job_queue.run_repeating(
            callback,
            interval=interval,
            first=first,
            name=name,
        )
        logger.info(message, *args)


def build_application(settings: Settings) -> Application:
    analytics = AnalyticsService(settings)
    buyback_alerts = BuybackAlertService(settings, analytics.wchain)
    whale_alerts = WCOWhaleAlert(settings, analytics.wchain)
    exchange_flow_alerts = ExchangeFlowAlertService(settings, analytics.wchain)
    wco_dex_alerts = WCODexAlertService(settings, analytics.wchain)
    wswap_liquidity_alerts = WSwapLiquidityAlertService(settings, analytics.wchain)
    daily_report = DailyReportService(settings, analytics.wchain)
    command_handlers = CommandHandlers(
        analytics,
        settings,
        buyback_alerts,
        exchange_flow_alerts,
        wco_dex_alerts,
        wswap_liquidity_alerts,
        daily_report,
    )

    async def _post_init(application: Application) -> None:
        await application.bot.set_my_commands(COMMAND_MENU)

        application.bot_data["buyback_alerts"] = buyback_alerts
        await buyback_alerts.ensure_initialized()
        logger.info("Buyback alert service initialized.")

        application.bot_data["daily_report"] = daily_report
        await daily_report.ensure_initialized()
        logger.info("Daily report service initialized.")

        if settings.movement_alerts_enabled:
            application.bot_data["whale_alerts"] = whale_alerts
            await whale_alerts.ensure_initialized()

            application.bot_data["exchange_flow_alerts"] = exchange_flow_alerts
            await exchange_flow_alerts.ensure_initialized()

            application.bot_data["wco_dex_alerts"] = wco_dex_alerts
            await wco_dex_alerts.ensure_initialized()

            application.bot_data["wswap_liquidity_alerts"] = wswap_liquidity_alerts
            await wswap_liquidity_alerts.ensure_initialized()
        else:
            logger.info(
                "Movement alert system disabled (MOVEMENT_ALERTS_ENABLED=false); skipping whale/flow/dex/liquidity watchers."
            )

        _schedule_job_queue_jobs(
            application=application,
            settings=settings,
            buyback_alerts=buyback_alerts,
            whale_alerts=whale_alerts,
            exchange_flow_alerts=exchange_flow_alerts,
            wco_dex_alerts=wco_dex_alerts,
            wswap_liquidity_alerts=wswap_liquidity_alerts,
            daily_report=daily_report,
        )

    application = (
        Application.builder()
        .token(settings.telegram_token)
        .post_init(_post_init)
        .build()
    )

    _register_command_handlers(application, command_handlers)

    logger.info("Telegram application wired with command handlers.")
    return application

