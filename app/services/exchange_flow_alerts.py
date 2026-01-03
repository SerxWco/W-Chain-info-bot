import asyncio
import json
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Optional

from telegram import Bot

from app.clients.wchain import WChainClient
from app.config import Settings
from app.utils import format_token_amount

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExchangeProfile:
    key: str
    display_name: str
    address: str
    inflow_template: str
    outflow_template: str


class ExchangeFlowAlertService:
    """
    Monitors native WCO flows in/out of configured exchange wallets.

    Alert rule (per exchange, per transaction):
      - inflow  (to exchange)   >= threshold -> inflow alert
      - outflow (from exchange) >= threshold -> outflow alert
    """

    def __init__(self, settings: Settings, wchain: WChainClient):
        self.settings = settings
        self.wchain = wchain
        self._lock = asyncio.Lock()

        self._state_path = Path(self.settings.exchange_flow_alert_state_path)
        self._last_seen_by_exchange: Dict[str, str] = {}
        self._load_state()

        footer = (
            "\n\n📊 Exchange Flow Monitor — WCO Ocean\n"
            "Threshold: ≥ 3,000,000 WCO"
        )
        self._exchanges: list[ExchangeProfile] = [
            ExchangeProfile(
                key="bitrue",
                display_name="Bitrue",
                address="0x6cc8dCbCA746a6E4Fdefb98E1d0DF903b107fd21",
                inflow_template=(
                    "🚨 BITRUE INFLOW ALERT\n"
                    "🐳 {amount} WCO just landed on Bitrue\n\n"
                    "Someone rang the sell bell 🔔\n"
                    "Order books, brace yourselves."
                    + footer
                ),
                outflow_template=(
                    "🚀 BITRUE OUTFLOW ALERT\n"
                    "🐳 {amount} WCO just LEFT Bitrue\n\n"
                    "Coins don’t withdraw themselves…\n"
                    "Someone’s planning ahead 🧠"
                    + footer
                ),
            ),
            ExchangeProfile(
                key="mexc",
                display_name="MEXC",
                address="0x2802E182d5A15DF915FD0363d8F1aDFd2049F9EE",
                inflow_template=(
                    "📥 MEXC DEPOSIT DETECTED\n"
                    "🐋 {amount} WCO moved into MEXC\n\n"
                    "Either a trader woke up…\n"
                    "or someone chose violence 😈"
                    + footer
                ),
                outflow_template=(
                    "📤 MEXC WITHDRAWAL DETECTED\n"
                    "🐋 {amount} WCO pulled from MEXC\n\n"
                    "Less sell pressure, more conviction 💎\n"
                    "Bullish behavior spotted."
                    + footer
                ),
            ),
            ExchangeProfile(
                key="bitmart",
                display_name="Bitmart",
                address="0x430d2ADA8140378989D20EAe6d48ea05BbcE2977",
                inflow_template=(
                    "🚨 BITMART INFLOW ALERT\n"
                    "🧳 {amount} WCO checked into Bitmart\n\n"
                    "Short stay or market dump?\n"
                    "Charts will decide 💀"
                    + footer
                ),
                outflow_template=(
                    "🌊 BITMART OUTFLOW ALERT\n"
                    "🐳 {amount} WCO escaped Bitmart\n\n"
                    "Back to cold storage waters…\n"
                    "The ocean just got deeper 🐋"
                    + footer
                ),
            ),
        ]

    async def ensure_initialized(self) -> None:
        """
        On cold start, set last_seen per exchange to the latest tx so we don't
        spam historical movements.
        """
        if not self.settings.exchange_flow_alerts_enabled:
            return
        if not self.settings.exchange_flow_alert_channel_id:
            return

        async with self._lock:
            missing = [ex for ex in self._exchanges if ex.key not in self._last_seen_by_exchange]
        if not missing:
            return

        for ex in missing:
            payload = await self.wchain.get_address_transactions(ex.address, direction="all", page_size=1)
            items = (payload or {}).get("items") or []
            latest_hash = items[0].get("hash") if items else None
            if not latest_hash:
                continue
            async with self._lock:
                if ex.key not in self._last_seen_by_exchange:
                    self._last_seen_by_exchange[ex.key] = str(latest_hash)
                    self._save_state()

    async def job_callback(self, context) -> None:
        await self.poll_and_alert(context.bot)

    async def poll_and_alert(self, bot: Bot) -> None:
        if not self.settings.exchange_flow_alerts_enabled:
            logger.debug("Exchange flow alerts disabled, skipping poll.")
            return
        channel = self.settings.exchange_flow_alert_channel_id
        if not channel:
            logger.warning("EXCHANGE_FLOW_ALERT_CHANNEL_ID not configured, skipping alerts.")
            return

        threshold = Decimal(str(self.settings.exchange_flow_threshold_wco))

        for ex in self._exchanges:
            async with self._lock:
                last_seen = self._last_seen_by_exchange.get(ex.key)

            payload = await self.wchain.get_address_transactions(
                ex.address,
                direction="all",
                page_size=self.settings.exchange_flow_poll_page_size,
            )
            new_items, newest_hash = self._extract_new_items(payload, last_seen=last_seen)
            if not new_items or not newest_hash:
                logger.debug("No new transactions for exchange %s.", ex.display_name)
                continue
            logger.info("Found %d new transaction(s) for exchange %s.", len(new_items), ex.display_name)

            ex_addr = ex.address.lower()
            alerts_sent = 0
            for item in new_items:
                value = self._parse_wco_amount(item.get("value"))
                if value is None or value <= 0:
                    continue

                from_addr = self._get_hash(item.get("from"))
                to_addr = self._get_hash(item.get("to"))
                if not from_addr or not to_addr:
                    continue

                from_l = from_addr.lower()
                to_l = to_addr.lower()

                # Determine direction relative to this exchange wallet.
                # If it's a self-transfer or ambiguous, skip.
                is_inflow = to_l == ex_addr and from_l != ex_addr
                is_outflow = from_l == ex_addr and to_l != ex_addr
                if not (is_inflow or is_outflow):
                    continue

                if value < threshold:
                    logger.debug("Skipping %s flow: %.2f WCO below threshold %.2f.", ex.display_name, value, threshold)
                    continue

                amount_display = format_token_amount(value)
                template = ex.inflow_template if is_inflow else ex.outflow_template
                text = template.format(amount=amount_display)
                await self._send_to_channel(bot, channel, text)
                alerts_sent += 1
            if alerts_sent > 0:
                logger.info("Sent %d exchange flow alert(s) for %s to channel %s.", alerts_sent, ex.display_name, channel)

            async with self._lock:
                self._last_seen_by_exchange[ex.key] = newest_hash
                self._save_state()

    async def _send_to_channel(self, bot: Bot, channel: str | int, text: str) -> None:
        try:
            await bot.send_message(chat_id=channel, text=text)
        except Exception:
            logger.exception("Failed to send exchange flow alert to channel=%s", channel)

    @staticmethod
    def _extract_new_items(
        payload: Optional[Dict[str, Any]], *, last_seen: Optional[str]
    ) -> tuple[list[Dict[str, Any]], Optional[str]]:
        """
        Returns (items_oldest_first, newest_hash).

        Note: we advance state by tx hash even if tx value is 0, so we don't
        get stuck re-processing contract calls with no native value.
        """
        items = (payload or {}).get("items") or []
        if not items:
            return [], None

        new_items: list[Dict[str, Any]] = []
        for item in items:
            tx_hash = item.get("hash")
            if not tx_hash:
                continue
            tx_hash = str(tx_hash)
            if last_seen and tx_hash == last_seen:
                break
            new_items.append(item)

        if not new_items:
            return [], None

        newest_hash = str(new_items[0].get("hash"))
        new_items.reverse()  # oldest-first
        return new_items, newest_hash

    @staticmethod
    def _get_hash(obj: Any) -> Optional[str]:
        if isinstance(obj, dict):
            h = obj.get("hash")
            return str(h) if h else None
        return None

    @staticmethod
    def _parse_wco_amount(value_wei: Any) -> Optional[Decimal]:
        if value_wei in (None, "", "NaN"):
            return None
        try:
            wei = Decimal(str(value_wei))
        except (InvalidOperation, TypeError, ValueError):
            return None
        if wei <= 0:
            return Decimal(0)
        return wei / Decimal("1000000000000000000")

    def _load_state(self) -> None:
        try:
            raw = self._state_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError:
            logger.exception("Failed to read exchange flow state from %s", self._state_path)
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Exchange flow state file is invalid JSON: %s", self._state_path)
            return

        section = (data or {}).get("exchange_flow") or {}
        last_seen_map = section.get("last_seen_by_exchange") or {}
        if isinstance(last_seen_map, dict):
            parsed: Dict[str, str] = {}
            for k, v in last_seen_map.items():
                if isinstance(k, str) and isinstance(v, str) and k and v:
                    parsed[k] = v
            self._last_seen_by_exchange = parsed

    def _save_state(self) -> None:
        data: Dict[str, Any] = {}
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}

        data["exchange_flow"] = {
            "last_seen_by_exchange": dict(self._last_seen_by_exchange),
            "channel": self.settings.exchange_flow_alert_channel_id,
            "threshold_wco": self.settings.exchange_flow_threshold_wco,
            "exchanges": {ex.key: ex.address for ex in self._exchanges},
        }
        try:
            self._state_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        except OSError:
            logger.exception("Failed to write exchange flow state to %s", self._state_path)

