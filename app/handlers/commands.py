import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.config import Settings
from app.services import AnalyticsService
from app.utils import format_percent, format_token_amount, format_usd, humanize_number


logger = logging.getLogger(__name__)


class CommandHandlers:
    """Telegram command handlers wired into python-telegram-bot."""

    def __init__(self, analytics: AnalyticsService, settings: Settings):
        self.analytics = analytics
        self.settings = settings

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        message = (
            "👋 *Welcome to the W-Chain Analytics Bot!*\n\n"
            "I provide real-time token data, on-chain health metrics, and quick references "
            "for the W-Chain ecosystem.\n\n"
            "*Available commands*\n"
            "/start — Quick overview and command list\n"
            "/wco — Comprehensive WCO analytics (price, supply, market cap)\n"
            "/wave — WAVE reward token snapshot\n"
            "/price [symbols] — Multi-token price lookup (defaults to WCO, WAVE, USDT, USDC)\n"
            "/stats — Network throughput, gas, and wallet activity\n"
        )
        await update.message.reply_text(message, parse_mode="Markdown")

    async def wco(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = await self._ensure_message(update)
        if not message:
            return
        data = await self.analytics.build_wco_overview()
        if not data:
            await message.reply_text("Unable to load WCO analytics right now. Please try again shortly.")
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
        await message.reply_text(text, parse_mode="Markdown")

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
        await message.reply_text(text, parse_mode="Markdown")

    async def price(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = await self._ensure_message(update)
        if not message:
            return
        requested = context.args if context.args else None
        prices = await self.analytics.price_lookup(requested)
        if not prices:
            await message.reply_text("No prices available right now, please retry shortly.")
            return
        lines = ["💹 *Token Prices*"]
        for symbol, value in prices.items():
            display = format_usd(value) if value is not None else "N/A"
            lines.append(f"{symbol}: {display}")
        lines.append("\nPowered by W-Chain Oracle & CoinGecko reference feeds.")
        await message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = await self._ensure_message(update)
        if not message:
            return
        try:
            data = await self.analytics.network_stats()
        except Exception:
            logger.exception("Failed to load network stats.")
            await message.reply_text("Unable to load network stats right now. Please try again shortly.")
            return
        if not data:
            await message.reply_text("Network stats are unavailable at the moment. Please try again soon.")
            return
        lines = [
            "📡 *Network Stats*",
            f"• Last Block: {int(data.get('last_block')) if data.get('last_block') else 'N/A'}",
            f"• Total Transactions: {humanize_number(data.get('tx_count'))}",
            f"• Active Wallets: {humanize_number(data.get('wallets'))}",
            f"• Average Gas: {humanize_number(data.get('gas'), 4)} Gwei",
        ]
        await message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _ensure_message(self, update: Update):
        if not update.message:
            return None
        return update.message

