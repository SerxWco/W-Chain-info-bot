import logging
from pathlib import Path

from telegram import Message, Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from app.config import Settings
from app.services import AnalyticsService
from app.services.buyback_alerts import BuybackAlertService
from app.utils import format_percent, format_token_amount, format_usd, humanize_number
from decimal import Decimal, InvalidOperation


logger = logging.getLogger(__name__)
BRAND_IMAGE_PATH = Path(__file__).resolve().parents[2] / "wocean.jpg"
BRAND_CAPTION = "🌊 W-Ocean ecosystem update"
MAX_CAPTION_LENGTH = 1024


class CommandHandlers:
    """Telegram command handlers wired into python-telegram-bot."""

    def __init__(self, analytics: AnalyticsService, settings: Settings, buyback_alerts: BuybackAlertService):
        self.analytics = analytics
        self.settings = settings
        self.buyback_alerts = buyback_alerts

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = await self._ensure_message(update)
        if not message:
            return
        text = (
            "👋 *Welcome to the W-Chain Analytics Bot!*\n\n"
            "I provide real-time token data, on-chain health metrics, and quick references "
            "for the W-Chain ecosystem.\n\n"
            "*Available commands*\n"
            "/start — Quick overview and command list\n"
            "/wco — Comprehensive WCO analytics (price, supply, market cap)\n"
            "/wave — WAVE reward token snapshot\n"
            "/price [symbols] — Multi-token price lookup (defaults to WCO, WAVE, USDT, USDC)\n"
            "/stats — Network throughput, gas, and wallet activity\n"
            "/tokens — Featured W-Chain asset catalog\n"
            "/token <symbol> — Detailed info for a specific token"
        )
        catalog = self._token_reference_section()
        if catalog:
            text = f"{text}\n\n{catalog}"
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
        """Show details for a specific token. Usage: /token <symbol>"""
        message = await self._ensure_message(update)
        if not message:
            return
        
        if not context.args:
            await self._send_branded_message(
                message,
                "🔍 *Token Lookup*\n\nUsage: /token <symbol>\n\nExample: `/token WAVE`",
            )
            return
        
        symbol = context.args[0]
        details = self._get_token_details(symbol)
        
        if not details:
            available = ", ".join(t.symbol for t in self.settings.token_catalog)
            await self._send_branded_message(
                message,
                f"Token '{symbol}' not found.\n\nAvailable: {available}",
                parse_mode=None,
            )
            return
        
        await self._send_branded_message(message, details)

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

    # Token emoji mapping for clean display
    TOKEN_EMOJIS = {
        "WAVE": "🟦",
        "WUSD": "🟩",
        "USDT": "🟧",
        "USDC": "🟧",
        "BUSDT": "🟧",
        "BUSDC": "🟧",
        "OG-88": "🟨",
        "DOGE": "🟪",
        "SOL": "🔵",
        "XRP": "🔴",
        "WWCO": "⚪",
        "WCO": "🟠",
    }

    def _token_reference_section(self) -> str:
        lines = ["🌊 *W-Chain Tokens*\n"]
        
        # Define display order and groupings
        display_order = [
            ("WAVE", None),
            ("WUSD", None),
            ("USDT", "USDC"),  # Group USDT/USDC together
            ("OG-88", None),
            ("DOGE", None),
            ("SOL", None),
            ("XRP", None),
            ("WWCO", None),
        ]
        
        tokens_by_symbol = {t.symbol.upper(): t for t in self.settings.token_catalog}
        
        for symbol, grouped_symbol in display_order:
            token = tokens_by_symbol.get(symbol.upper())
            if not token:
                continue
            emoji = self.TOKEN_EMOJIS.get(symbol, "•")
            
            if grouped_symbol:
                # Group display (e.g., USDT / USDC)
                lines.append(f"{emoji} {symbol} / {grouped_symbol}")
            elif symbol == "WWCO":
                # Special display for Wrapped WCO
                lines.append(f"{emoji} Wrapped WCO ({symbol})")
            else:
                lines.append(f"{emoji} {token.name if token.name != symbol else symbol}")
        
        lines.append("\n🔍 Use /token <symbol> for details")
        return "\n".join(lines)

    def _get_token_details(self, symbol: str) -> str | None:
        """Get detailed info for a specific token."""
        symbol_upper = symbol.upper()
        token = next((t for t in self.settings.token_catalog if t.symbol.upper() == symbol_upper), None)
        if not token:
            return None
        
        emoji = self.TOKEN_EMOJIS.get(symbol_upper, "•")
        lines = [f"{emoji} *{token.name}* ({token.symbol})\n"]
        
        if token.description:
            lines.append(f"{token.description}\n")
        
        if token.contract:
            lines.append(f"📋 Contract: `{token.contract}`")
        
        if token.info_url:
            lines.append(f"🔗 [View on Explorer]({token.info_url})")
        
        return "\n".join(lines)

