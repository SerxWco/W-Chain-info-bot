import asyncio
import json
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from telegram import Bot

from app.clients.wchain import WChainClient
from app.config import Settings
from app.utils import format_token_amount

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BuybackEvent:
    tx_hash: str
    amount_wco: Decimal
    from_address: Optional[str] = None
    timestamp: Optional[str] = None


class BuybackAlertService:
    """
    Watches a single wallet for incoming native coin transfers (WCO) and broadcasts
    an alert message to subscribed Telegram chats.
    """

    def __init__(self, settings: Settings, wchain: WChainClient):
        self.settings = settings
        self.wchain = wchain
        self._lock = asyncio.Lock()

        self._state_path = Path(self.settings.buyback_alert_state_path)
        self._subscribers: Set[int] = set()
        self._last_seen_tx_hash: Optional[str] = None

        self._load_state()

    def is_subscribed(self, chat_id: int) -> bool:
        return chat_id in self._subscribers

    async def toggle_subscription(self, chat_id: int) -> bool:
        async with self._lock:
            if chat_id in self._subscribers:
                self._subscribers.remove(chat_id)
                subscribed = False
            else:
                self._subscribers.add(chat_id)
                subscribed = True
            self._save_state()
            return subscribed

    async def ensure_initialized(self) -> None:
        """
        On cold start, set last_seen to the latest incoming tx so we don't spam
        historical transfers.
        """
        async with self._lock:
            if self._last_seen_tx_hash:
                return

        payload = await self.wchain.get_address_transactions(
            self.settings.buyback_wallet_address,
            direction="to",
            page_size=1,
        )
        items = (payload or {}).get("items") or []
        latest_hash = items[0].get("hash") if items else None

        async with self._lock:
            if not self._last_seen_tx_hash and latest_hash:
                self._last_seen_tx_hash = str(latest_hash)
                self._save_state()

    async def poll_and_broadcast(self, bot: Bot) -> None:
        if not self.settings.buyback_alerts_enabled:
            return

        async with self._lock:
            subscribers = set(self._subscribers)
            last_seen = self._last_seen_tx_hash

        if not subscribers:
            return

        payload = await self.wchain.get_address_transactions(
            self.settings.buyback_wallet_address,
            direction="to",
            page_size=self.settings.buyback_poll_page_size,
        )
        events = self._extract_new_events(payload, last_seen=last_seen)
        if not events:
            return

        # Send oldest -> newest, and only advance last_seen after send attempts.
        newest_hash = events[-1].tx_hash
        for event in events:
            if event.amount_wco < Decimal(str(self.settings.buyback_min_amount_wco)):
                continue
            text = self._render_message(event.amount_wco)
            await self._broadcast(bot, subscribers, text)

        async with self._lock:
            self._last_seen_tx_hash = newest_hash
            self._save_state()

    async def job_callback(self, context) -> None:
        await self.poll_and_broadcast(context.bot)

    def _render_message(self, amount_wco: Decimal) -> str:
        # Reuse existing formatter for consistent thousands separators.
        amount_display = format_token_amount(float(amount_wco))
        return (
            "💸 *BUYBACK EXECUTED*\n\n"
            "🧠 Smart money at work\n"
            f"💰 {amount_display} WCO absorbed from the market\n\n"
            "🧲 Supply ↓\n"
            "📈 Pressure ↑"
        )

    async def _broadcast(self, bot: Bot, chat_ids: Iterable[int], text: str) -> None:
        failures: List[int] = []
        for chat_id in chat_ids:
            try:
                await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
            except Exception:
                logger.exception("Failed to send buyback alert to chat_id=%s", chat_id)
                failures.append(chat_id)

        if failures:
            async with self._lock:
                changed = False
                for chat_id in failures:
                    if chat_id in self._subscribers:
                        self._subscribers.remove(chat_id)
                        changed = True
                if changed:
                    self._save_state()

    def _extract_new_events(self, payload: Optional[Dict[str, Any]], *, last_seen: Optional[str]) -> List[BuybackEvent]:
        items = (payload or {}).get("items") or []
        if not items:
            return []

        new_items: List[Dict[str, Any]] = []
        for item in items:
            tx_hash = item.get("hash")
            if not tx_hash:
                continue
            tx_hash = str(tx_hash)
            if last_seen and tx_hash == last_seen:
                break
            new_items.append(item)

        if not new_items:
            return []

        # Items come newest-first; reverse so we emit oldest-first.
        new_items.reverse()

        events: List[BuybackEvent] = []
        for item in new_items:
            amount = self._parse_wco_amount(item.get("value"))
            if amount is None:
                continue
            if amount <= 0:
                continue

            from_addr = None
            from_obj = item.get("from") or {}
            if isinstance(from_obj, dict):
                from_addr = from_obj.get("hash")

            timestamp = item.get("timestamp") or item.get("block_timestamp")
            events.append(
                BuybackEvent(
                    tx_hash=str(item.get("hash")),
                    amount_wco=amount,
                    from_address=str(from_addr) if from_addr else None,
                    timestamp=str(timestamp) if timestamp else None,
                )
            )
        return events

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
            logger.exception("Failed to read buyback alert state from %s", self._state_path)
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Buyback alert state file is invalid JSON: %s", self._state_path)
            return

        buyback = (data or {}).get("buyback") or {}
        subs = buyback.get("subscribers") or []
        if isinstance(subs, list):
            for chat_id in subs:
                try:
                    self._subscribers.add(int(chat_id))
                except (TypeError, ValueError):
                    continue

        last_seen = buyback.get("last_seen_tx_hash")
        if isinstance(last_seen, str) and last_seen:
            self._last_seen_tx_hash = last_seen

    def _save_state(self) -> None:
        data = {
            "buyback": {
                "subscribers": sorted(self._subscribers),
                "last_seen_tx_hash": self._last_seen_tx_hash,
                "wallet": self.settings.buyback_wallet_address,
            }
        }
        try:
            self._state_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        except OSError:
            logger.exception("Failed to write buyback alert state to %s", self._state_path)

