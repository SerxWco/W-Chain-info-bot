import logging
from pathlib import Path

from telegram import Message, Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from app.config import Settings
from app.services import AnalyticsService, DailyReportService
from app.services.buyback_alerts import BuybackAlertService
from app.services.wco_dex_alerts import WCODexAlertService
from app.services.wswap_liquidity_alerts import WSwapLiquidityAlertService
from app.utils import format_percent, format_token_amount, format_usd, humanize_number
from decimal import Decimal, InvalidOperation


logger = logging.getLogger(__name__)
BRAND_IMAGE_PATH = Path(__file__).resolve().parents[2] / "wocean.jpg"
BRAND_CAPTION = "🌊 W-Ocean ecosystem update"
MAX_CAPTION_LENGTH = 1024


class CommandHandlers:
    """Telegram command handlers wired into python-telegram-bot."""

    def __init__(
        self,
        analytics: AnalyticsService,
        settings: Settings,
        buyback_alerts: BuybackAlertService,
        wco_dex_alerts: WCODexAlertService | None = None,
        wswap_liquidity_alerts: WSwapLiquidityAlertService | None = None,
        daily_report: DailyReportService | None = None,
    ):
        self.analytics = analytics
        self.settings = settings
        self.buyback_alerts = buyback_alerts
        self.wco_dex_alerts = wco_dex_alerts
        self.wswap_liquidity_alerts = wswap_liquidity_alerts
        self.daily_report = daily_report

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = await self._ensure_message(update)
        if not message:
            return
        text = (
            "👋 Welcome to *Bubbles* 🌊\n"
            "W-Chain Analytics Bot\n\n"
            "Real-time token data, on-chain health metrics,\n"
            "and fast insights for the W-Chain ecosystem.\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📌 COMMANDS\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🌊 /wco\n"
            "WCO overview\n"
            "(price • supply • market cap)\n\n"
            "🟦 /wave\n"
            "WAVE reward token snapshot\n\n"
            "💱 /price <symbols>\n"
            "Multi-token price lookup\n"
            "(default: WCO, WAVE, USDT, USDC)\n\n"
            "🪙 /token <symbol>\n"
            "Detailed token analytics\n"
            "(e.g. /token OG88)\n\n"
            "📊 /stats\n"
            "Network activity & wallet health\n\n"
            "📦 /tokens\n"
            "Featured W-Chain assets\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🪙 FEATURED TOKENS\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🟦 WAVE\n"
            "🟩 WUSD\n"
            "🟧 USDT / USDC\n"
            "🟨 OG-88\n"
            "🟪 DOGE\n"
            "🔵 SOL\n"
            "🔴 XRP\n"
            "⚪ Wrapped WCO (WWCO)\n\n"
            "🔍 Tip: use */token <symbol>* for full details\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🌐 scan.w-chain.com"
        )
        await self._send_branded_message(message, text)

    async def wco(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = await self._ensure_message(update)
        if not message:
            return
        data = await self.analytics.build_wco_overview()
        if not data:
            await self._send_branded_message(
                message, "Unable to load WCO analytics right now. Please try again shortly.", parse_mode=None
            )
            return

        distribution = data.get("distribution") or {}
        text = (
            "🟠 *WCO Analytics*\n\n"
            f"• Price: {format_usd(data.get('price'))}\n"
            f"• Market Cap: {format_usd(data.get('market_cap'))}\n"
            f"• Circulating: {format_token_amount(data.get('circulating'))} WCO\n"
            f"• Locked: {format_token_amount(data.get('locked'))} WCO\n"
            f"• Burned: {format_token_amount(data.get('burned'))} WCO\n"
            f"• Total Supply: {format_token_amount(data.get('total'))} WCO\n\n"
            "*Distribution*\n"
            f"• Circulating: {format_percent(distribution.get('circulating'))}\n"
            f"• Locked: {format_percent(distribution.get('locked'))}\n"
            f"• Burned: {format_percent(distribution.get('burned'))}\n"
        )
        await self._send_branded_message(message, text)

    async def wave(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = await self._ensure_message(update)
        if not message:
            return
        data = await self.analytics.build_wave_overview()
        counters = data.get("counters") or {}
        text = (
            "🌊 *WAVE Token Overview*\n\n"
            f"• Price: {format_usd(data.get('price_usd'))}\n"
            f"• Price (WCO): {format_token_amount(data.get('price_wco'))} WCO\n"
            f"• Holders: {humanize_number(counters.get('token_holders_count'))}\n"
            f"• Transfers: {humanize_number(counters.get('transfers_count'))}\n"
            "\nWAVE fuels W-Swap incentives, liquidity mining, and community rewards across the W-Chain DEX stack."
        )
        await self._send_branded_message(message, text)

    async def price(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = await self._ensure_message(update)
        if not message:
            return
        requested = context.args if context.args else None
        prices = await self.analytics.price_lookup(requested)
        if not prices:
            await self._send_branded_message(
                message, "No prices available right now, please retry shortly.", parse_mode=None
            )
            return
        lines = ["💹 *Token Prices*"]
        for symbol, value in prices.items():
            display = format_usd(value) if value is not None else "N/A"
            lines.append(f"{symbol}: {display}")
        lines.append("\nPowered by W-Chain Oracle & CoinGecko reference feeds.")
        await self._send_branded_message(message, "\n".join(lines))

    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = await self._ensure_message(update)
        if not message:
            return
        try:
            data = await self.analytics.network_stats()
        except Exception:
            logger.exception("Failed to load network stats.")
            await self._send_branded_message(
                message, "Unable to load network stats right now. Please try again shortly.", parse_mode=None
            )
            return
        if not data:
            await self._send_branded_message(
                message, "Network stats are unavailable at the moment. Please try again soon.", parse_mode=None
            )
            return
        lines = [
            "📡 *Network Stats*",
            f"• Last Block: {int(data.get('last_block')) if data.get('last_block') else 'N/A'}",
            f"• Total Transactions: {humanize_number(data.get('tx_count'))}",
            f"• Active Wallets: {humanize_number(data.get('wallets'))}",
            f"• Average Gas: {humanize_number(data.get('gas'), 4)} Gwei",
        ]
        await self._send_branded_message(message, "\n".join(lines))

    async def tokens(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = await self._ensure_message(update)
        if not message:
            return
        catalog = self._token_reference_section()
        if not catalog:
            await self._send_branded_message(
                message, "No token references configured yet.", parse_mode=None
            )
            return
        await self._send_branded_message(message, catalog)

    async def token(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show detailed info for a specific token. Usage: /token <symbol>"""
        message = await self._ensure_message(update)
        if not message:
            return

        if not context.args:
            # List available tokens when no argument provided
            available = [t.symbol for t in self.settings.token_catalog]
            text = (
                "🔍 *Token Lookup*\n\n"
                f"Usage: `/token <symbol>`\n\n"
                f"Available: {', '.join(available)}"
            )
            await self._send_branded_message(message, text)
            return

        symbol = context.args[0].upper()
        data = await self.analytics.build_token_overview(symbol)

        if not data:
            available = [t.symbol for t in self.settings.token_catalog]
            text = (
                f"❌ Token `{symbol}` not found.\n\n"
                f"Available tokens: {', '.join(available)}"
            )
            await self._send_branded_message(message, text)
            return

        counters = data.get("counters") or {}
        lines = [
            f"🪙 *{data['name']}* ({data['symbol']})\n",
            f"_{data['description']}_\n",
            f"• Price: {format_usd(data.get('price_usd'))}",
        ]

        if counters.get("token_holders_count"):
            lines.append(f"• Holders: {humanize_number(counters.get('token_holders_count'))}")
        if counters.get("transfers_count"):
            lines.append(f"• Transfers: {humanize_number(counters.get('transfers_count'))}")

        if data.get("contract"):
            lines.append(f"\n📋 Contract: `{data['contract']}`")
        if data.get("info_url"):
            lines.append(f"🔗 [More Info]({data['info_url']})")

        await self._send_branded_message(message, "\n".join(lines))

    async def buybackalerts(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = await self._ensure_message(update)
        if not message:
            return
        chat_id = message.chat_id
        subscribed = await self.buyback_alerts.toggle_subscription(chat_id)
        if subscribed:
            text = (
                "✅ *Buyback alerts enabled for this chat*\n\n"
                f"Watching: `{self.settings.buyback_wallet_address}`\n"
                "You’ll receive an alert whenever this wallet receives WCO."
            )
        else:
            text = "🛑 *Buyback alerts disabled for this chat*"
        await self._send_branded_message(message, text)

    async def buybackstatus(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = await self._ensure_message(update)
        if not message:
            return
        enabled = self.settings.buyback_alerts_enabled
        subscribed = self.buyback_alerts.is_subscribed(message.chat_id)
        text = (
            "💸 *Buyback Alert Status*\n\n"
            f"• Alerts enabled (bot): {'Yes' if enabled else 'No'}\n"
            f"• Subscribed (this chat): {'Yes' if subscribed else 'No'}\n"
            f"• Wallet watched: `{self.settings.buyback_wallet_address}`\n"
            f"• Poll interval: {self.settings.buyback_poll_seconds}s\n\n"
            "Use /buybackalerts to toggle alerts in this chat."
        )
        await self._send_branded_message(message, text)

    async def buybacktest(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Sends a test buyback alert message (no on-chain transfer required).
        Usage:
          /buybacktest
          /buybacktest 123.45
        """
        message = await self._ensure_message(update)
        if not message:
            return

        # Optional amount override for formatting validation.
        amount = Decimal("1")
        if context.args:
            try:
                amount = Decimal(str(context.args[0]))
            except (InvalidOperation, TypeError, ValueError):
                amount = Decimal("1")

        if amount <= 0:
            amount = Decimal("1")

        text = self.buyback_alerts.render_test_message(amount)
        await self._send_branded_message(message, text)

    async def dexalerts(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Toggle WCO DEX alerts on/off. Admin only.
        Usage: /dexalerts [on|off]
        """
        message = await self._ensure_message(update)
        if not message:
            return

        if not self.wco_dex_alerts:
            await message.reply_text("WCO DEX alerts service not configured.")
            return

        user = update.effective_user
        if not user:
            await message.reply_text("Unable to identify user.")
            return

        # Determine if enabling or disabling
        enable: bool | None = None
        if context.args:
            arg = context.args[0].lower()
            if arg in ("on", "enable", "1", "true", "yes"):
                enable = True
            elif arg in ("off", "disable", "0", "false", "no"):
                enable = False

        success, result_msg = await self.wco_dex_alerts.toggle_alerts(
            context.bot, user.id, enable=enable
        )
        await message.reply_text(result_msg)

    async def dexstatus(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Show WCO DEX alert status.
        """
        message = await self._ensure_message(update)
        if not message:
            return

        if not self.wco_dex_alerts:
            await message.reply_text("WCO DEX alerts service not configured.")
            return

        enabled = self.wco_dex_alerts.alerts_enabled
        channel = self.settings.wco_dex_alert_channel_id or "Not set"
        auto_delete = self.settings.wco_dex_auto_delete_seconds

        text = (
            "📊 *WCO DEX Alert Status*\n\n"
            f"• Alerts: {'✅ Enabled' if enabled else '❌ Disabled'}\n"
            f"• Channel: `{channel}`\n"
            f"• Auto-delete: {auto_delete}s ({auto_delete // 60} min)\n"
            f"• Buy threshold: {format_token_amount(self.settings.wco_dex_min_buy_wco)} WCO\n"
            f"• Sell threshold: {format_token_amount(self.settings.wco_dex_min_sell_wco)} WCO\n"
            f"• Liquidity threshold: {format_token_amount(self.settings.wco_dex_min_liquidity_wco)} WCO\n"
            f"• Whale threshold: {format_token_amount(self.settings.wco_dex_whale_threshold_wco)} WCO\n\n"
            "Use /dexalerts [on|off] to toggle (admin only)."
        )
        await self._send_branded_message(message, text)

    async def liqalerts(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Toggle W-Swap liquidity alerts on/off. Admin only.
        Usage: /liqalerts [on|off]
        """
        message = await self._ensure_message(update)
        if not message:
            return

        if not self.wswap_liquidity_alerts:
            await message.reply_text("W-Swap liquidity alerts service not configured.")
            return

        user = update.effective_user
        if not user:
            await message.reply_text("Unable to identify user.")
            return

        # Determine if enabling or disabling
        enable: bool | None = None
        if context.args:
            arg = context.args[0].lower()
            if arg in ("on", "enable", "1", "true", "yes"):
                enable = True
            elif arg in ("off", "disable", "0", "false", "no"):
                enable = False

        success, result_msg = await self.wswap_liquidity_alerts.toggle_alerts(
            context.bot, user.id, enable=enable
        )
        await message.reply_text(result_msg)

    async def liqstatus(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Show W-Swap liquidity alert status.
        """
        message = await self._ensure_message(update)
        if not message:
            return

        if not self.wswap_liquidity_alerts:
            await message.reply_text("W-Swap liquidity alerts service not configured.")
            return

        enabled = self.wswap_liquidity_alerts.alerts_enabled
        channel = self.settings.wswap_liquidity_alert_channel_id or "Not set"
        auto_delete = self.settings.wswap_liquidity_auto_delete_seconds
        min_usd = self.settings.wswap_liquidity_min_usd
        factory = self.settings.wswap_factory_address

        # Get pair count
        pairs = await self.wswap_liquidity_alerts.discover_pairs()
        pair_count = len(pairs)

        text = (
            "💧 *W-Swap Liquidity Alert Status*\n\n"
            f"• Alerts: {'✅ Enabled' if enabled else '❌ Disabled'}\n"
            f"• Channel: `{channel}`\n"
            f"• WCO Pairs: {pair_count}\n"
            f"• Min USD: ${min_usd:,.0f}\n"
            f"• Auto-delete: {auto_delete}s ({auto_delete // 60} min)\n"
            f"• Factory: `{factory[:20]}...`\n\n"
            "Use /liqalerts [on|off] to toggle (admin only).\n"
            "Use /pairs to see all WCO pairs."
        )
        await self._send_branded_message(message, text)

    async def pairs(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        List all WCO pairs discovered from W-Swap factory.
        """
        message = await self._ensure_message(update)
        if not message:
            return

        if not self.wswap_liquidity_alerts:
            await message.reply_text("W-Swap liquidity service not configured.")
            return

        summary = await self.wswap_liquidity_alerts.get_all_pairs_summary()
        await message.reply_text(summary, parse_mode="MarkdownV2", disable_web_page_preview=True)

    async def dailyreport(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Manually trigger the daily report. Admin only.
        Usage: /dailyreport
        """
        message = await self._ensure_message(update)
        if not message:
            return

        if not self.daily_report:
            await message.reply_text("Daily report service not configured.")
            return

        await message.reply_text("📊 Generating daily report...")

        try:
            await self.daily_report.send_daily_report(context.bot)
            await message.reply_text("✅ Daily report sent successfully!")
        except Exception as e:
            logger.exception("Failed to send manual daily report")
            await message.reply_text(f"❌ Failed to send daily report: {e}")

    async def _ensure_message(self, update: Update):
        if not update.message:
            return None
        return update.message

    async def _send_branded_message(self, message: Message, text: str, parse_mode: str | None = "Markdown") -> None:
        send_text = True
        if BRAND_IMAGE_PATH.exists():
            try:
                if len(text) <= MAX_CAPTION_LENGTH:
                    with BRAND_IMAGE_PATH.open("rb") as photo:
                        await message.reply_photo(photo=photo, caption=text, parse_mode=parse_mode)
                    send_text = False
                else:
                    with BRAND_IMAGE_PATH.open("rb") as photo:
                        await message.reply_photo(photo=photo, caption=BRAND_CAPTION, parse_mode="Markdown")
            except TelegramError:
                logger.exception("Unable to send branding image, falling back to text.")
        if send_text:
            await message.reply_text(text, parse_mode=parse_mode)

    def _token_reference_section(self) -> str:
        # Fixed display order with emoji and label
        token_display = [
            ("🟦", "WAVE"),
            ("🟩", "WUSD"),
            ("🟧", "USDT / USDC"),
            ("🟨", "OG-88"),
            ("🟪", "DOGE"),
            ("🔵", "SOL"),
            ("🔴", "XRP"),
            ("⚪", "Wrapped WCO (WWCO)"),
        ]
        
        lines = ["🌊 *W-Chain Tokens*\n"]
        for emoji, label in token_display:
            lines.append(f"{emoji} {label}")
        lines.append("\n🔍 Use /token <symbol> for details")
        return "\n".join(lines)

