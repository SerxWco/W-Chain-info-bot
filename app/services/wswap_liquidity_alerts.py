"""
W-Swap Liquidity Alert Service

Monitors all W-Swap pairs for liquidity events (Mint/Burn) by scanning the factory contract.
- 💦 LIQUIDITY ADDED: Mint event on any WCO pair
- 🔥 LIQUIDITY REMOVED: Burn event on any WCO pair
- 🆕 NEW PAIR CREATED: PairCreated event from factory

Uses the factory contract to auto-discover all WCO pairs.
Factory: 0x2A44f013aD7D6a1083d8F499605Cf1148fbaCE31
WWCO: 0xEdB8008031141024d50cA2839A607B2f82C1c045
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from telegram import Bot, ChatMember
from telegram.error import TelegramError

from app.clients.wchain import WChainClient
from app.config import Settings
from app.utils import escape_markdown_v2, format_token_amount, format_usd

logger = logging.getLogger(__name__)

# Zero address used for mint/burn detection
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# Event topic signatures (keccak256 of event signature)
TOPIC_PAIR_CREATED = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"
TOPIC_MINT = "0x4c209b5fc8ad50758f13e2e1088ba56a560dff690a1c6fef26394f4c03821c4f"
TOPIC_BURN = "0xdccd412f0b1252819cb1fd330b93224ca42612892bb3f4f789976e6d81936496"
TOPIC_SWAP = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"
TOPIC_SYNC = "0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1"


class LiquidityEventType(Enum):
    LIQUIDITY_ADDED = "liquidity_added"
    LIQUIDITY_REMOVED = "liquidity_removed"
    NEW_PAIR = "new_pair"


@dataclass(frozen=True)
class PairInfo:
    """Metadata for a W-Swap pair."""

    address: str
    token0_address: str
    token1_address: str
    token0_symbol: str
    token1_symbol: str
    token0_decimals: int
    token1_decimals: int
    has_wco: bool  # True if one of the tokens is WWCO

    @property
    def name(self) -> str:
        return f"{self.token0_symbol}/{self.token1_symbol}"

    @property
    def wco_position(self) -> Optional[int]:
        """Returns 0 or 1 indicating which token is WCO, or None if neither."""
        if not self.has_wco:
            return None
        # WWCO address (lowercase for comparison)
        wwco = "0xedb8008031141024d50ca2839a607b2f82c1c045"
        if self.token0_address.lower() == wwco:
            return 0
        if self.token1_address.lower() == wwco:
            return 1
        return None


@dataclass(frozen=True)
class LiquidityEvent:
    """Represents a liquidity event to alert on."""

    unique_key: str
    tx_hash: str
    block_number: int
    event_type: LiquidityEventType
    pair: PairInfo
    amount0: Decimal
    amount1: Decimal
    wco_amount: Optional[Decimal]
    other_amount: Optional[Decimal]
    other_symbol: Optional[str]
    usd_value: Optional[Decimal]
    provider_address: Optional[str]
    timestamp: Optional[str] = None


class WSwapLiquidityAlertService:
    """
    Real-time alert service for W-Swap liquidity events across all pairs.

    Features:
    - Auto-discovers all pairs from factory contract
    - Monitors Mint (add liquidity) and Burn (remove liquidity) events
    - Alerts on new pair creation
    - Filters by minimum USD value
    """

    def __init__(self, settings: Settings, wchain: WChainClient):
        self.settings = settings
        self.wchain = wchain
        self._lock = asyncio.Lock()

        self._state_path = Path(self.settings.wswap_liquidity_alert_state_path)
        self._processed_event_keys: Set[str] = set()
        self._last_seen_factory_log: Optional[str] = None
        self._last_seen_by_pair: Dict[str, str] = {}
        self._max_processed_cache = 2000
        self._alerts_enabled: bool = True

        # Cache of discovered pairs: address -> PairInfo
        self._pairs_cache: Dict[str, PairInfo] = {}
        self._pairs_last_refresh: float = 0
        self._pairs_refresh_interval = 300  # Refresh every 5 minutes

        # Store job queue reference for auto-delete scheduling
        self._job_queue = None

        self._load_state()

    async def discover_pairs(self, force: bool = False) -> List[PairInfo]:
        """
        Discover all WCO pairs from the factory contract.
        Returns list of pairs that contain WWCO.
        """
        import time

        current_time = time.time()
        if not force and self._pairs_cache and (current_time - self._pairs_last_refresh) < self._pairs_refresh_interval:
            return list(self._pairs_cache.values())

        factory_addr = self.settings.wswap_factory_address
        wwco_addr_lower = self.settings.wwco_token_address.lower()

        # Fetch PairCreated events from factory logs
        payload = await self.wchain.get_address_logs(factory_addr, page_size=100)
        items = (payload or {}).get("items") or []

        discovered_pairs: Dict[str, PairInfo] = {}

        for item in items:
            topics = item.get("topics") or []
            if not topics or topics[0] != TOPIC_PAIR_CREATED:
                continue

            decoded = item.get("decoded") or {}
            params = decoded.get("parameters") or []
            if len(params) < 3:
                continue

            # Extract pair info from PairCreated event
            token0_addr = None
            token1_addr = None
            pair_addr = None

            for param in params:
                name = param.get("name", "")
                value = param.get("value", "")
                if name == "token0":
                    token0_addr = value
                elif name == "token1":
                    token1_addr = value
                elif name == "pair":
                    pair_addr = value

            if not all([token0_addr, token1_addr, pair_addr]):
                continue

            pair_addr_lower = pair_addr.lower()
            if pair_addr_lower in discovered_pairs:
                continue

            # Check if this pair contains WWCO
            has_wco = (
                token0_addr.lower() == wwco_addr_lower
                or token1_addr.lower() == wwco_addr_lower
            )

            # Fetch token info for both tokens
            token0_info = await self.wchain.get_token_info(token0_addr)
            token1_info = await self.wchain.get_token_info(token1_addr)

            token0_symbol = (token0_info or {}).get("symbol", token0_addr[:8])
            token1_symbol = (token1_info or {}).get("symbol", token1_addr[:8])
            token0_decimals = int((token0_info or {}).get("decimals", 18))
            token1_decimals = int((token1_info or {}).get("decimals", 18))

            pair_info = PairInfo(
                address=pair_addr,
                token0_address=token0_addr,
                token1_address=token1_addr,
                token0_symbol=token0_symbol,
                token1_symbol=token1_symbol,
                token0_decimals=token0_decimals,
                token1_decimals=token1_decimals,
                has_wco=has_wco,
            )
            discovered_pairs[pair_addr_lower] = pair_info

        self._pairs_cache = discovered_pairs
        self._pairs_last_refresh = current_time

        wco_pairs = [p for p in discovered_pairs.values() if p.has_wco]
        logger.info(
            "Discovered %d total pairs, %d with WCO.",
            len(discovered_pairs),
            len(wco_pairs),
        )

        return wco_pairs

    async def ensure_initialized(self) -> None:
        """
        On cold start, initialize last_seen markers and discover pairs.
        """
        if not self.settings.wswap_liquidity_alerts_enabled:
            return
        if not self.settings.wswap_liquidity_alert_channel_id:
            return

        # Discover pairs first
        wco_pairs = await self.discover_pairs(force=True)

        # Initialize last_seen for factory
        async with self._lock:
            if self._last_seen_factory_log:
                factory_initialized = True
            else:
                factory_initialized = False

        if not factory_initialized:
            factory_addr = self.settings.wswap_factory_address
            payload = await self.wchain.get_address_logs(factory_addr, page_size=1)
            items = (payload or {}).get("items") or []
            if items:
                latest_key = self._unique_key_from_log(items[0])
                async with self._lock:
                    if not self._last_seen_factory_log and latest_key:
                        self._last_seen_factory_log = latest_key
                        self._save_state()

        # Initialize last_seen for each WCO pair
        for pair in wco_pairs:
            pair_addr_lower = pair.address.lower()
            async with self._lock:
                if pair_addr_lower in self._last_seen_by_pair:
                    continue

            payload = await self.wchain.get_address_logs(pair.address, page_size=1)
            items = (payload or {}).get("items") or []
            if items:
                latest_key = self._unique_key_from_log(items[0])
                if latest_key:
                    async with self._lock:
                        if pair_addr_lower not in self._last_seen_by_pair:
                            self._last_seen_by_pair[pair_addr_lower] = latest_key
                            self._save_state()

        logger.info(
            "W-Swap liquidity alerts initialized with %d WCO pairs.",
            len(wco_pairs),
        )

    async def job_callback(self, context) -> None:
        """Telegram job callback for periodic polling."""
        if context.job_queue and not self._job_queue:
            self._job_queue = context.job_queue
        await self.poll_and_alert(context.bot)

    @property
    def alerts_enabled(self) -> bool:
        """Check if alerts are currently enabled."""
        return self._alerts_enabled

    async def is_admin(self, bot: Bot, chat_id: str | int, user_id: int) -> bool:
        """Check if a user is an admin in the specified chat/channel."""
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            return member.status in (
                ChatMember.ADMINISTRATOR,
                ChatMember.OWNER,
            )
        except TelegramError as e:
            logger.warning("Failed to check admin status: %s", e)
            return False

    async def toggle_alerts(
        self, bot: Bot, user_id: int, enable: Optional[bool] = None
    ) -> Tuple[bool, str]:
        """Toggle alerts on/off. Only admins can do this."""
        channel = self.settings.wswap_liquidity_alert_channel_id
        if not channel:
            return False, "Liquidity alert channel not configured."

        is_admin = await self.is_admin(bot, channel, user_id)
        if not is_admin:
            return False, "⛔ Only channel admins can enable/disable alerts."

        async with self._lock:
            if enable is None:
                self._alerts_enabled = not self._alerts_enabled
            else:
                self._alerts_enabled = enable

            status = "enabled ✅" if self._alerts_enabled else "disabled ❌"
            self._save_state()

        return True, f"W-Swap liquidity alerts {status}"

    async def poll_and_alert(self, bot: Bot) -> None:
        """Main polling loop - check for new liquidity events and send alerts."""
        if not self.settings.wswap_liquidity_alerts_enabled:
            logger.debug("W-Swap liquidity alerts disabled in config, skipping poll.")
            return

        async with self._lock:
            if not self._alerts_enabled:
                logger.debug("W-Swap liquidity alerts disabled by admin, skipping poll.")
                return

        channel = self.settings.wswap_liquidity_alert_channel_id
        if not channel:
            logger.warning("WSWAP_LIQUIDITY_ALERT_CHANNEL_ID not configured, skipping.")
            return

        # Get current WCO price for USD calculations
        wco_price = await self._get_wco_price()

        # Refresh pairs periodically
        wco_pairs = await self.discover_pairs()

        # Poll factory for new pair creation events
        await self._poll_factory_events(bot, channel, wco_price)

        # Poll each WCO pair for liquidity events
        for pair in wco_pairs:
            await self._poll_pair_liquidity(bot, channel, pair, wco_price)

    async def _poll_factory_events(
        self,
        bot: Bot,
        channel: str,
        wco_price: Optional[Decimal],
    ) -> None:
        """Poll factory for new PairCreated events."""
        factory_addr = self.settings.wswap_factory_address

        async with self._lock:
            last_seen = self._last_seen_factory_log

        payload = await self.wchain.get_address_logs(
            factory_addr, page_size=self.settings.wswap_liquidity_poll_page_size
        )
        items = (payload or {}).get("items") or []
        if not items:
            return

        # Collect new items
        new_items: List[Dict[str, Any]] = []
        for item in items:
            key = self._unique_key_from_log(item)
            if not key:
                continue
            if last_seen and key == last_seen:
                break
            new_items.append(item)

        if not new_items:
            return

        newest_key = self._unique_key_from_log(new_items[0])
        new_items.reverse()  # oldest-first
        alerts_sent = 0

        wwco_addr_lower = self.settings.wwco_token_address.lower()

        for item in new_items:
            topics = item.get("topics") or []
            if not topics or topics[0] != TOPIC_PAIR_CREATED:
                continue

            decoded = item.get("decoded") or {}
            params = decoded.get("parameters") or []

            token0_addr = None
            token1_addr = None
            pair_addr = None

            for param in params:
                name = param.get("name", "")
                value = param.get("value", "")
                if name == "token0":
                    token0_addr = value
                elif name == "token1":
                    token1_addr = value
                elif name == "pair":
                    pair_addr = value

            if not all([token0_addr, token1_addr, pair_addr]):
                continue

            # Check if this involves WCO
            has_wco = (
                token0_addr.lower() == wwco_addr_lower
                or token1_addr.lower() == wwco_addr_lower
            )

            if not has_wco:
                continue

            tx_hash = item.get("transaction_hash", "")
            event_key = self._unique_key_from_log(item)

            async with self._lock:
                if event_key in self._processed_event_keys:
                    continue

            # Fetch token info
            token0_info = await self.wchain.get_token_info(token0_addr)
            token1_info = await self.wchain.get_token_info(token1_addr)

            token0_symbol = (token0_info or {}).get("symbol", token0_addr[:8])
            token1_symbol = (token1_info or {}).get("symbol", token1_addr[:8])
            token0_decimals = int((token0_info or {}).get("decimals", 18))
            token1_decimals = int((token1_info or {}).get("decimals", 18))

            pair_info = PairInfo(
                address=pair_addr,
                token0_address=token0_addr,
                token1_address=token1_addr,
                token0_symbol=token0_symbol,
                token1_symbol=token1_symbol,
                token0_decimals=token0_decimals,
                token1_decimals=token1_decimals,
                has_wco=has_wco,
            )

            # Add to cache
            self._pairs_cache[pair_addr.lower()] = pair_info

            # Create and send alert
            event = LiquidityEvent(
                unique_key=event_key or tx_hash,
                tx_hash=tx_hash,
                block_number=item.get("block_number", 0),
                event_type=LiquidityEventType.NEW_PAIR,
                pair=pair_info,
                amount0=Decimal(0),
                amount1=Decimal(0),
                wco_amount=None,
                other_amount=None,
                other_symbol=None,
                usd_value=None,
                provider_address=None,
                timestamp=None,
            )

            text = self._render_alert(event, wco_price)
            await self._send_to_channel(bot, channel, text)
            alerts_sent += 1

            async with self._lock:
                self._mark_processed(event_key or tx_hash)

        if alerts_sent > 0:
            logger.info("Sent %d new pair alert(s) to channel %s.", alerts_sent, channel)

        async with self._lock:
            if newest_key:
                self._last_seen_factory_log = newest_key
            self._save_state()

    async def _poll_pair_liquidity(
        self,
        bot: Bot,
        channel: str,
        pair: PairInfo,
        wco_price: Optional[Decimal],
    ) -> None:
        """Poll a specific pair for Mint/Burn events."""
        pair_addr_lower = pair.address.lower()

        async with self._lock:
            last_seen = self._last_seen_by_pair.get(pair_addr_lower)

        payload = await self.wchain.get_address_logs(
            pair.address, page_size=self.settings.wswap_liquidity_poll_page_size
        )
        items = (payload or {}).get("items") or []
        if not items:
            return

        # Collect new items
        new_items: List[Dict[str, Any]] = []
        for item in items:
            key = self._unique_key_from_log(item)
            if not key:
                continue
            if last_seen and key == last_seen:
                break
            new_items.append(item)

        if not new_items:
            return

        newest_key = self._unique_key_from_log(new_items[0])
        new_items.reverse()  # oldest-first
        alerts_sent = 0
        min_usd = Decimal(str(self.settings.wswap_liquidity_min_usd))

        for item in new_items:
            topics = item.get("topics") or []
            if not topics:
                continue

            topic0 = topics[0]
            if topic0 not in (TOPIC_MINT, TOPIC_BURN):
                continue

            event_type = (
                LiquidityEventType.LIQUIDITY_ADDED
                if topic0 == TOPIC_MINT
                else LiquidityEventType.LIQUIDITY_REMOVED
            )

            decoded = item.get("decoded") or {}
            params = decoded.get("parameters") or []

            amount0_raw = Decimal(0)
            amount1_raw = Decimal(0)
            provider_addr = None

            for param in params:
                name = param.get("name", "")
                value = param.get("value", "")
                if name == "amount0":
                    try:
                        amount0_raw = Decimal(str(value))
                    except (InvalidOperation, TypeError):
                        pass
                elif name == "amount1":
                    try:
                        amount1_raw = Decimal(str(value))
                    except (InvalidOperation, TypeError):
                        pass
                elif name == "sender":
                    provider_addr = value
                elif name == "to" and not provider_addr:
                    provider_addr = value

            # Convert to human-readable amounts
            amount0 = amount0_raw / Decimal(10 ** pair.token0_decimals)
            amount1 = amount1_raw / Decimal(10 ** pair.token1_decimals)

            # Determine WCO amount and other token
            wco_position = pair.wco_position
            if wco_position == 0:
                wco_amount = amount0
                other_amount = amount1
                other_symbol = pair.token1_symbol
            elif wco_position == 1:
                wco_amount = amount1
                other_amount = amount0
                other_symbol = pair.token0_symbol
            else:
                wco_amount = None
                other_amount = None
                other_symbol = None

            # Calculate USD value
            usd_value = None
            if wco_amount is not None and wco_price is not None:
                usd_value = wco_amount * wco_price * 2  # LP is ~50/50

            # Filter by minimum USD value
            if usd_value is not None and usd_value < min_usd:
                logger.debug(
                    "Skipping %s event on %s: $%.2f below threshold $%.2f",
                    event_type.value,
                    pair.name,
                    usd_value,
                    min_usd,
                )
                continue

            tx_hash = item.get("transaction_hash", "")
            event_key = self._unique_key_from_log(item)

            async with self._lock:
                if event_key in self._processed_event_keys:
                    continue

            event = LiquidityEvent(
                unique_key=event_key or tx_hash,
                tx_hash=tx_hash,
                block_number=item.get("block_number", 0),
                event_type=event_type,
                pair=pair,
                amount0=amount0,
                amount1=amount1,
                wco_amount=wco_amount,
                other_amount=other_amount,
                other_symbol=other_symbol,
                usd_value=usd_value,
                provider_address=provider_addr,
                timestamp=None,
            )

            text = self._render_alert(event, wco_price)
            await self._send_to_channel(bot, channel, text)
            alerts_sent += 1

            async with self._lock:
                self._mark_processed(event_key or tx_hash)

        if alerts_sent > 0:
            logger.info(
                "Sent %d liquidity alert(s) for %s to channel %s.",
                alerts_sent,
                pair.name,
                channel,
            )

        async with self._lock:
            if newest_key:
                self._last_seen_by_pair[pair_addr_lower] = newest_key
            self._save_state()

    async def _get_wco_price(self) -> Optional[Decimal]:
        """Fetch current WCO price."""
        try:
            data = await self.wchain.get_wco_price()
            if data and "price" in data:
                return Decimal(str(data["price"]))
        except Exception as exc:
            logger.warning("Failed to fetch WCO price: %s", exc)
        return None

    def _render_alert(self, event: LiquidityEvent, wco_price: Optional[Decimal]) -> str:
        """Render alert message in Telegram MarkdownV2 format."""
        pair_name = escape_markdown_v2(event.pair.name)
        tx_hash = event.tx_hash
        explorer_link = f"https://scan.w-chain.com/tx/{tx_hash}"
        pair_link = f"https://scan.w-chain.com/address/{event.pair.address}"

        if event.event_type == LiquidityEventType.NEW_PAIR:
            # Determine the other token (non-WCO)
            wwco_lower = self.settings.wwco_token_address.lower()
            if event.pair.token0_address.lower() == wwco_lower:
                other_symbol = event.pair.token1_symbol
                other_addr = event.pair.token1_address
            else:
                other_symbol = event.pair.token0_symbol
                other_addr = event.pair.token0_address

            other_symbol_esc = escape_markdown_v2(other_symbol)
            other_link = f"https://scan.w-chain.com/address/{other_addr}"

            return (
                f"🆕 *NEW WCO PAIR CREATED*\n\n"
                f"🏊 *Pair:* [{pair_name}]({pair_link})\n"
                f"🪙 *Token:* [{other_symbol_esc}]({other_link})\n"
                f"🔗 [View Tx]({explorer_link})"
            )

        # Liquidity added or removed
        if event.event_type == LiquidityEventType.LIQUIDITY_ADDED:
            emoji = "💦"
            title = "LIQUIDITY ADDED"
        else:
            emoji = "🔥"
            title = "LIQUIDITY REMOVED"

        # Format amounts
        if event.wco_amount is not None:
            wco_display = escape_markdown_v2(format_token_amount(event.wco_amount))
        else:
            wco_display = "N/A"

        if event.other_amount is not None and event.other_symbol:
            other_display = escape_markdown_v2(
                f"{format_token_amount(event.other_amount)} {event.other_symbol}"
            )
        else:
            other_display = "N/A"

        if event.usd_value is not None:
            usd_display = escape_markdown_v2(format_usd(event.usd_value))
        else:
            usd_display = "N/A"

        if wco_price is not None:
            price_display = escape_markdown_v2(f"${float(wco_price):.6f}")
        else:
            price_display = "N/A"

        provider = event.provider_address or "Unknown"
        provider_short = f"{provider[:10]}...{provider[-8:]}" if len(provider) > 20 else provider

        return (
            f"{emoji} *{title}*\n\n"
            f"🏊 *Pool:* [{pair_name}]({pair_link})\n"
            f"💰 *WCO:* {wco_display}\n"
            f"🪙 *Other:* {other_display}\n"
            f"💵 *Value:* ~{usd_display}\n"
            f"📊 *Price:* {price_display}\n"
            f"👤 *Provider:* `{provider_short}`\n"
            f"🔗 [View Tx]({explorer_link})"
        )

    async def _send_to_channel(self, bot: Bot, channel: str, text: str) -> None:
        """Send alert message to Telegram channel with auto-delete."""
        try:
            message = await bot.send_message(
                chat_id=channel,
                text=text,
                parse_mode="MarkdownV2",
                disable_web_page_preview=True,
            )

            # Schedule auto-delete if configured
            auto_delete_seconds = self.settings.wswap_liquidity_auto_delete_seconds
            if auto_delete_seconds > 0 and self._job_queue:
                self._job_queue.run_once(
                    self._delete_message_callback,
                    when=auto_delete_seconds,
                    data={"chat_id": channel, "message_id": message.message_id},
                    name=f"delete_liq_msg_{message.message_id}",
                )
                logger.debug(
                    "Scheduled auto-delete for liquidity message %s in %d seconds.",
                    message.message_id,
                    auto_delete_seconds,
                )
        except Exception:
            logger.exception("Failed to send liquidity alert to channel=%s", channel)

    async def _delete_message_callback(self, context) -> None:
        """Callback to delete a message after the auto-delete delay."""
        data = context.job.data
        chat_id = data.get("chat_id")
        message_id = data.get("message_id")

        if not chat_id or not message_id:
            return

        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            logger.debug("Auto-deleted liquidity message %s from channel %s.", message_id, chat_id)
        except TelegramError as e:
            logger.debug("Could not delete message %s: %s", message_id, e)

    def _mark_processed(self, key: str) -> None:
        """Mark an event as processed (must be called within lock)."""
        self._processed_event_keys.add(key)
        if len(self._processed_event_keys) > self._max_processed_cache:
            excess = len(self._processed_event_keys) - self._max_processed_cache
            to_remove = list(self._processed_event_keys)[:excess]
            for k in to_remove:
                self._processed_event_keys.discard(k)

    @staticmethod
    def _unique_key_from_log(item: Optional[Dict[str, Any]]) -> Optional[str]:
        """Generate unique key for a log entry."""
        if not item:
            return None
        block = item.get("block_number")
        idx = item.get("index")
        tx_hash = item.get("transaction_hash")
        if block is None or idx is None:
            return str(tx_hash) if tx_hash else None
        return f"{block}:{idx}"

    def _load_state(self) -> None:
        """Load persisted state from file."""
        try:
            raw = self._state_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError:
            logger.exception("Failed to read liquidity alert state from %s", self._state_path)
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Liquidity alert state file is invalid JSON: %s", self._state_path)
            return

        section = (data or {}).get("wswap_liquidity") or {}

        # Load last seen by pair
        last_seen_map = section.get("last_seen_by_pair") or {}
        if isinstance(last_seen_map, dict):
            for k, v in last_seen_map.items():
                if isinstance(k, str) and isinstance(v, str) and k and v:
                    self._last_seen_by_pair[k.lower()] = v

        # Load last seen factory
        last_seen_factory = section.get("last_seen_factory_log")
        if isinstance(last_seen_factory, str) and last_seen_factory:
            self._last_seen_factory_log = last_seen_factory

        # Load alerts enabled state
        alerts_enabled = section.get("alerts_enabled")
        if isinstance(alerts_enabled, bool):
            self._alerts_enabled = alerts_enabled

        # Load processed event keys
        processed = section.get("processed_event_keys") or []
        if isinstance(processed, list):
            for k in processed[-self._max_processed_cache:]:
                if isinstance(k, str) and k:
                    self._processed_event_keys.add(k)

    def _save_state(self) -> None:
        """Persist state to file."""
        data: Dict[str, Any] = {}
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}

        data["wswap_liquidity"] = {
            "last_seen_by_pair": dict(self._last_seen_by_pair),
            "last_seen_factory_log": self._last_seen_factory_log,
            "alerts_enabled": self._alerts_enabled,
            "processed_event_keys": list(self._processed_event_keys)[-self._max_processed_cache:],
            "channel": self.settings.wswap_liquidity_alert_channel_id,
            "factory": self.settings.wswap_factory_address,
        }
        try:
            self._state_path.write_text(
                json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
            )
        except OSError:
            logger.exception("Failed to write liquidity alert state to %s", self._state_path)

    async def get_all_pairs_summary(self) -> str:
        """Get a summary of all discovered WCO pairs for display."""
        pairs = await self.discover_pairs()

        if not pairs:
            return "No WCO pairs found."

        lines = [f"🏊 *W\\-Swap WCO Pairs* \\({len(pairs)}\\):\n"]
        for pair in pairs:
            pair_name = escape_markdown_v2(pair.name)
            pair_link = f"https://scan.w-chain.com/address/{pair.address}"
            lines.append(f"• [{pair_name}]({pair_link})")

        return "\n".join(lines)

    def render_test_message(
        self,
        event_type: str = "add",
        wco_amount: Optional[Decimal] = None,
        other_amount: Optional[Decimal] = None,
        other_symbol: str = "XRP",
    ) -> str:
        """
        Render a test liquidity alert message for debugging.
        """
        if wco_amount is None:
            wco_amount = Decimal("100000")
        if other_amount is None:
            other_amount = Decimal("20")

        wco_price = Decimal("0.0004")
        usd_value = wco_amount * wco_price * 2

        if event_type.lower() in ("remove", "burn"):
            emoji = "🔥"
            title = "LIQUIDITY REMOVED"
        else:
            emoji = "💦"
            title = "LIQUIDITY ADDED"

        wco_display = format_token_amount(wco_amount)
        other_display = f"{format_token_amount(other_amount)} {other_symbol}"
        usd_display = format_usd(usd_value)
        price_display = f"${float(wco_price):.6f}"
        provider_short = "0x1B0f2857...98127AE9"
        tx_hash = "0x0000000000000000000000000000000000000000000000000000000000000000"
        explorer_link = f"https://scan.w-chain.com/tx/{tx_hash}"
        pair_link = "https://scan.w-chain.com/address/0x24F07DE79398f24C9d4dD60a281a29843E43B7FD"
        pair_name = f"{other_symbol}/WWCO"

        return (
            f"{emoji} *{title}* (TEST)\n\n"
            f"🏊 *Pool:* [{pair_name}]({pair_link})\n"
            f"💰 *WCO:* {wco_display}\n"
            f"🪙 *Other:* {other_display}\n"
            f"💵 *Value:* ~{usd_display}\n"
            f"📊 *Price:* {price_display}\n"
            f"👤 *Provider:* `{provider_short}`\n"
            f"🔗 [View Tx]({explorer_link})"
        )

    def get_debug_info(self) -> dict:
        """Return debug information about the service state."""
        return {
            "alerts_enabled": self._alerts_enabled,
            "channel_configured": bool(self.settings.wswap_liquidity_alert_channel_id),
            "channel_id": self.settings.wswap_liquidity_alert_channel_id or "NOT SET",
            "factory_address": self.settings.wswap_factory_address,
            "wwco_address": self.settings.wwco_token_address,
            "pairs_cached": len(self._pairs_cache),
            "last_seen_factory": self._last_seen_factory_log,
            "last_seen_pairs_count": len(self._last_seen_by_pair),
            "processed_keys_count": len(self._processed_event_keys),
            "min_usd_threshold": float(self.settings.wswap_liquidity_min_usd),
            "poll_seconds": self.settings.wswap_liquidity_poll_seconds,
        }
