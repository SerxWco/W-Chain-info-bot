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
class WhaleBuyEvent:
    unique_key: str  # internal_tx unique key: "{tx_hash}:{internal_index}"
    tx_hash: str
    buyer_wallet: str
    amount_wco: Decimal
    timestamp: Optional[str] = None


class WCOWhaleAlert:
    """
    Polls the configured router for outgoing *native WCO* internal transfers.

    Heuristic for "WCO buy":
      - internal transfer is from router -> user EOA (to.is_contract == False)
      - value > 0 (native coin movement)
    """

    MINI_MIN = Decimal("500000")
    MEGA_MIN = Decimal("1000000")
    ULTRA_MIN = Decimal("5000000")

    def __init__(self, settings: Settings, wchain: WChainClient):
        self.settings = settings
        self.wchain = wchain
        self._lock = asyncio.Lock()

        self._state_path = Path(self.settings.whale_alert_state_path)
        self._last_seen_key: Optional[str] = None
        self._load_state()

    async def ensure_initialized(self) -> None:
        """
        On cold start, set last_seen to the latest router internal tx so we don't
        spam historical whale buys.
        """
        if not self.settings.whale_alerts_enabled:
            return
        if not self.settings.whale_router_address or not self.settings.whale_alert_channel_id:
            return

        async with self._lock:
            if self._last_seen_key:
                return

        payload = await self.wchain.get_address_internal_transactions(
            self.settings.whale_router_address,
            page_size=1,
        )
        items = (payload or {}).get("items") or []
        latest = items[0] if items else None
        latest_key = self._unique_key(latest) if latest else None

        async with self._lock:
            if not self._last_seen_key and latest_key:
                self._last_seen_key = latest_key
                self._save_state()

    async def job_callback(self, context) -> None:
        await self.poll_and_alert(context.bot)

    async def poll_and_alert(self, bot: Bot) -> None:
        if not self.settings.whale_alerts_enabled:
            logger.debug("Whale alerts disabled, skipping poll.")
            return
        if not self.settings.whale_router_address:
            logger.warning("WHALE_ROUTER_ADDRESS not configured, skipping alerts.")
            return
        channel = self.settings.whale_alert_channel_id
        if not channel:
            logger.warning("WHALE_ALERT_CHANNEL_ID not configured, skipping alerts.")
            return

        async with self._lock:
            last_seen = self._last_seen_key

        payload = await self.wchain.get_address_internal_transactions(
            self.settings.whale_router_address,
            page_size=self.settings.whale_poll_page_size,
        )
        events = self._extract_new_whale_buys(payload, last_seen=last_seen)
        if not events:
            logger.debug("No new whale buy events detected.")
            return
        logger.info("Detected %d new whale buy event(s) to process.", len(events))

        newest_key = events[-1].unique_key
        alerts_sent = 0
        for event in events:
            # Tier filter: only alert at/above MINI_MIN
            if event.amount_wco < self.MINI_MIN:
                logger.debug("Skipping whale event %s: amount %.2f below threshold.", event.tx_hash, event.amount_wco)
                continue
            text = self._render_message(event)
            await self._send_to_channel(bot, channel, text)
            alerts_sent += 1
        if alerts_sent > 0:
            logger.info("Sent %d whale alert(s) to channel %s.", alerts_sent, channel)

        async with self._lock:
            self._last_seen_key = newest_key
            self._save_state()

    def _render_message(self, event: WhaleBuyEvent) -> str:
        # Requirement: commas + 2 decimals.
        amount_display = format_token_amount(event.amount_wco)

        if self.MINI_MIN <= event.amount_wco < self.MEGA_MIN:
            return (
                "🐳 WCO WHALE ALERT 🐳\n"
                f"💰 {amount_display} WCO purchased\n"
                "⚡ Market pressure incoming"
            )

        tx_hash = event.tx_hash
        if self.MEGA_MIN <= event.amount_wco < self.ULTRA_MIN:
            return (
                "🚨 WHALE SIGHTED 🚨\n"
                f"💰 {amount_display} WCO just hit the market\n"
                "🌊 The tide has shifted…\n"
                f"🔗 Tx: {tx_hash}"
            )

        # Ultra whales: include buyer wallet (optional requirement; we include it).
        return (
            "💥 MEGA BUY 💥\n"
            f"🧲 {amount_display} WCO absorbed\n"
            "📊 Not retail — smart money in action\n"
            "🐳 Brace yourselves!\n"
            f"🔗 Tx: {tx_hash}\n"
            f"📦 Buyer: {event.buyer_wallet}"
        )

    async def _send_to_channel(self, bot: Bot, channel: str | int, text: str) -> None:
        try:
            # Use plain text to avoid markdown escaping issues with hashes/addresses.
            await bot.send_message(chat_id=channel, text=text)
        except Exception:
            logger.exception("Failed to send whale alert to channel=%s", channel)

    def _extract_new_whale_buys(
        self, payload: Optional[Dict[str, Any]], *, last_seen: Optional[str]
    ) -> list[WhaleBuyEvent]:
        items = (payload or {}).get("items") or []
        if not items:
            return []

        # Items are newest-first; collect until we reach last_seen.
        new_items: list[Dict[str, Any]] = []
        for item in items:
            key = self._unique_key(item)
            if not key:
                continue
            if last_seen and key == last_seen:
                break
            new_items.append(item)

        if not new_items:
            return []

        new_items.reverse()
        router = self.settings.whale_router_address.lower()
        events: list[WhaleBuyEvent] = []
        for item in new_items:
            from_addr = ((item.get("from") or {}) if isinstance(item.get("from"), dict) else {}).get("hash")
            to_obj = (item.get("to") or {}) if isinstance(item.get("to"), dict) else {}
            to_addr = to_obj.get("hash")

            if not from_addr or not to_addr:
                continue

            # Requirement: trigger on BUY transactions only (router -> user wallet).
            if str(from_addr).lower() != router:
                continue
            if str(to_addr).lower() == router:
                continue

            # Heuristic for "user wallet": internal transfer destination is not a contract.
            if to_obj.get("is_contract") is True:
                continue

            amount = self._parse_wco_amount(item.get("value"))
            if amount is None or amount <= 0:
                continue

            key = self._unique_key(item)
            if not key:
                continue

            tx_hash = str(item.get("transaction_hash") or "")
            if not tx_hash:
                continue

            timestamp = item.get("timestamp")
            events.append(
                WhaleBuyEvent(
                    unique_key=key,
                    tx_hash=tx_hash,
                    buyer_wallet=str(to_addr),
                    amount_wco=amount,
                    timestamp=str(timestamp) if timestamp else None,
                )
            )
        return events

    @staticmethod
    def _unique_key(item: Optional[Dict[str, Any]]) -> Optional[str]:
        if not item:
            return None
        tx_hash = item.get("transaction_hash")
        idx = item.get("index")
        if not tx_hash or idx is None:
            return None
        return f"{str(tx_hash)}:{str(idx)}"

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
            logger.exception("Failed to read whale alert state from %s", self._state_path)
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Whale alert state file is invalid JSON: %s", self._state_path)
            return

        whale = (data or {}).get("whale") or {}
        last_seen = whale.get("last_seen_key")
        if isinstance(last_seen, str) and last_seen:
            self._last_seen_key = last_seen

    def _save_state(self) -> None:
        data: Dict[str, Any] = {}
        # Preserve other sections if the state file is shared (e.g., buyback).
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}

        data["whale"] = {
            "last_seen_key": self._last_seen_key,
            "router": self.settings.whale_router_address,
            "channel": self.settings.whale_alert_channel_id,
        }
        try:
            self._state_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        except OSError:
            logger.exception("Failed to write whale alert state to %s", self._state_path)

