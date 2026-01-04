"""
WCO DEX Alert Service

Monitors W-Swap pools for native WCO transactions and broadcasts alerts:
- 🟢 BUY: WCO leaves pool (pool is sender)
- 🔴 SELL: WCO enters pool (pool is receiver)
- 💦 LIQUIDITY ADDED: WCO sent to LP pair + LP tokens minted
- 🔥 LIQUIDITY REMOVED: WCO received from LP pair + LP tokens burned
- 🐋 WHALE MOVE: Large transfers not involving pool addresses
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from telegram import Bot, ChatMember
from telegram.error import TelegramError

from app.clients.wchain import WChainClient
from app.config import Settings
from app.utils import escape_markdown_v2, format_token_amount, format_usd

logger = logging.getLogger(__name__)

# Zero address used for mint/burn detection
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


class AlertType(Enum):
    BUY = "buy"
    SELL = "sell"
    LIQUIDITY_ADDED = "liquidity_added"
    LIQUIDITY_REMOVED = "liquidity_removed"
    WHALE_MOVE = "whale_move"


@dataclass(frozen=True)
class PoolInfo:
    """Metadata for a known W-Swap pool."""

    address: str
    name: str
    lp_token_address: Optional[str] = None


@dataclass(frozen=True)
class WCODexEvent:
    """Represents a WCO DEX event to alert on."""

    unique_key: str
    tx_hash: str
    alert_type: AlertType
    amount_wco: Decimal
    usd_value: Optional[Decimal]
    price_wco: Optional[Decimal]
    from_address: str
    to_address: str
    pool_name: Optional[str] = None
    timestamp: Optional[str] = None


class WCODexAlertService:
    """
    Real-time alert service for WCO native coin transactions on W-Swap.

    Monitors:
    - Pool addresses for buys/sells
    - Liquidity add/remove events
    - Whale transfers not involving pools
    """

    # Known W-Swap pools involving WCO
    DEFAULT_POOLS: List[PoolInfo] = [
        PoolInfo(
            address="0xEdB8008031141024d50cA2839A607B2f82C1c045",
            name="WWCO",
            lp_token_address="0xEdB8008031141024d50cA2839A607B2f82C1c045",
        ),
    ]

    def __init__(self, settings: Settings, wchain: WChainClient):
        self.settings = settings
        self.wchain = wchain
        self._lock = asyncio.Lock()

        self._state_path = Path(self.settings.wco_dex_alert_state_path)
        self._processed_tx_hashes: Set[str] = set()
        self._last_seen_by_pool: Dict[str, str] = {}
        self._last_seen_router: Optional[str] = None
        self._last_seen_whale_tx: Optional[str] = None
        self._max_processed_cache = 1000
        self._alerts_enabled: bool = True  # Can be toggled by admins

        # Also track exchange addresses to exclude from whale alerts
        self._exchange_addresses_lower: Set[str] = {
            "0x6cc8dcbca746a6e4fdefb98e1d0df903b107fd21",  # Bitrue
            "0x2802e182d5a15df915fd0363d8f1adfd2049f9ee",  # MEXC
            "0x430d2ada8140378989d20eae6d48ea05bbce2977",  # Bitmart
        }

        # Store job queue reference for auto-delete scheduling
        self._job_queue = None

        # Build pool registry from config + defaults
        self._pools = self._build_pool_registry()
        self._pool_addresses_lower = {p.address.lower() for p in self._pools}

        self._load_state()

    def _build_pool_registry(self) -> List[PoolInfo]:
        """Build pool registry from config and defaults."""
        pools: Dict[str, PoolInfo] = {}

        # Add defaults
        for pool in self.DEFAULT_POOLS:
            pools[pool.address.lower()] = pool

        # Add from config (may override defaults)
        for addr in self.settings.wco_dex_pool_addresses:
            addr_lower = addr.lower()
            if addr_lower not in pools:
                pools[addr_lower] = PoolInfo(
                    address=addr,
                    name=f"Pool_{addr[:8]}",
                )

        return list(pools.values())

    async def ensure_initialized(self) -> None:
        """
        On cold start, initialize last_seen markers to avoid spamming historical txs.
        """
        if not self.settings.wco_dex_alerts_enabled:
            return
        if not self.settings.wco_dex_alert_channel_id:
            return

        # Initialize last_seen for router
        async with self._lock:
            if self._last_seen_router:
                router_initialized = True
            else:
                router_initialized = False

        if not router_initialized:
            router = self.settings.wswap_router_address
            if router:
                payload = await self.wchain.get_address_internal_transactions(
                    router, page_size=1
                )
                items = (payload or {}).get("items") or []
                if items:
                    latest_key = self._unique_key_internal(items[0])
                    async with self._lock:
                        if not self._last_seen_router and latest_key:
                            self._last_seen_router = latest_key
                            self._save_state()

        # Initialize last_seen for whale transfers
        async with self._lock:
            if self._last_seen_whale_tx:
                whale_initialized = True
            else:
                whale_initialized = False

        if not whale_initialized:
            payload = await self.wchain.get_recent_transactions(page_size=1, filter_type="validated")
            items = (payload or {}).get("items") or []
            if items:
                latest_hash = items[0].get("hash")
                async with self._lock:
                    if not self._last_seen_whale_tx and latest_hash:
                        self._last_seen_whale_tx = str(latest_hash)
                        self._save_state()

        # Initialize last_seen for each pool
        for pool in self._pools:
            async with self._lock:
                if pool.address.lower() in self._last_seen_by_pool:
                    continue

            payload = await self.wchain.get_address_transactions(
                pool.address, direction="all", page_size=1
            )
            items = (payload or {}).get("items") or []
            if items:
                latest_hash = items[0].get("hash")
                if latest_hash:
                    async with self._lock:
                        if pool.address.lower() not in self._last_seen_by_pool:
                            self._last_seen_by_pool[pool.address.lower()] = str(
                                latest_hash
                            )
                            self._save_state()

        logger.info(
            "WCO DEX alerts initialized with %d pools.", len(self._pools)
        )

    async def job_callback(self, context) -> None:
        """Telegram job callback for periodic polling."""
        # Store job queue reference for auto-delete scheduling
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

    async def toggle_alerts(self, bot: Bot, user_id: int, enable: Optional[bool] = None) -> tuple[bool, str]:
        """
        Toggle alerts on/off. Only admins can do this.
        
        Args:
            bot: Telegram bot instance
            user_id: User attempting to toggle
            enable: If None, toggle current state. If bool, set to that value.
            
        Returns:
            Tuple of (success, message)
        """
        channel = self.settings.wco_dex_alert_channel_id
        if not channel:
            return False, "Alert channel not configured."

        # Check if user is admin
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
            
        return True, f"WCO DEX alerts {status}"

    async def enable_alerts(self, bot: Bot, user_id: int) -> tuple[bool, str]:
        """Enable alerts (admin only)."""
        return await self.toggle_alerts(bot, user_id, enable=True)

    async def disable_alerts(self, bot: Bot, user_id: int) -> tuple[bool, str]:
        """Disable alerts (admin only)."""
        return await self.toggle_alerts(bot, user_id, enable=False)

    async def poll_and_alert(self, bot: Bot) -> None:
        """Main polling loop - check for new events and send alerts."""
        if not self.settings.wco_dex_alerts_enabled:
            logger.debug("WCO DEX alerts disabled in config, skipping poll.")
            return

        async with self._lock:
            if not self._alerts_enabled:
                logger.debug("WCO DEX alerts disabled by admin, skipping poll.")
                return

        channel = self.settings.wco_dex_alert_channel_id
        if not channel:
            logger.warning("WCO_DEX_ALERT_CHANNEL_ID not configured, skipping.")
            return

        # Get current WCO price for USD calculations
        wco_price = await self._get_wco_price()

        # Poll router for internal transactions (buys via swaps)
        await self._poll_router_buys(bot, channel, wco_price)

        # Poll each pool for direct transfers
        for pool in self._pools:
            await self._poll_pool(bot, channel, pool, wco_price)

        # Poll for whale transfers (large transfers not involving pools)
        await self._poll_whale_transfers(bot, channel, wco_price)

    async def _poll_router_buys(
        self,
        bot: Bot,
        channel: str,
        wco_price: Optional[Decimal],
    ) -> None:
        """
        Poll router for outgoing native WCO internal transactions.
        When router sends WCO to a user, it's a BUY.
        """
        router = self.settings.wswap_router_address
        if not router:
            return

        async with self._lock:
            last_seen = self._last_seen_router

        payload = await self.wchain.get_address_internal_transactions(
            router, page_size=self.settings.wco_dex_poll_page_size
        )
        items = (payload or {}).get("items") or []
        if not items:
            return

        # Process newest-first, collect until last_seen
        new_items: List[Dict[str, Any]] = []
        for item in items:
            key = self._unique_key_internal(item)
            if not key:
                continue
            if last_seen and key == last_seen:
                break
            new_items.append(item)

        if not new_items:
            return

        # Newest key to update state
        newest_key = self._unique_key_internal(new_items[0])

        # Process oldest-first for chronological alerts
        new_items.reverse()
        router_lower = router.lower()
        alerts_sent = 0

        for item in new_items:
            tx_hash = str(item.get("transaction_hash") or "")
            if not tx_hash:
                continue

            # Skip if already processed
            async with self._lock:
                if tx_hash in self._processed_tx_hashes:
                    continue

            from_obj = item.get("from") or {}
            to_obj = item.get("to") or {}
            from_addr = from_obj.get("hash", "") if isinstance(from_obj, dict) else ""
            to_addr = to_obj.get("hash", "") if isinstance(to_obj, dict) else ""

            if not from_addr or not to_addr:
                continue

            # BUY: router sends WCO to user (not a contract)
            if str(from_addr).lower() == router_lower:
                # Skip if sending to a contract (not a user buy)
                if to_obj.get("is_contract") is True:
                    continue

                amount = self._parse_wco_amount(item.get("value"))
                if amount is None or amount <= 0:
                    continue

                # Check minimum threshold
                if amount < Decimal(str(self.settings.wco_dex_min_buy_wco)):
                    continue

                usd_value = amount * wco_price if wco_price else None
                event = WCODexEvent(
                    unique_key=self._unique_key_internal(item) or tx_hash,
                    tx_hash=tx_hash,
                    alert_type=AlertType.BUY,
                    amount_wco=amount,
                    usd_value=usd_value,
                    price_wco=wco_price,
                    from_address=str(from_addr),
                    to_address=str(to_addr),
                    pool_name="W-Swap Router",
                    timestamp=item.get("timestamp"),
                )
                text = self._render_alert(event)
                await self._send_to_channel(bot, channel, text)
                alerts_sent += 1

                async with self._lock:
                    self._mark_processed(tx_hash)

        if alerts_sent > 0:
            logger.info("Sent %d router buy alert(s) to channel %s.", alerts_sent, channel)

        async with self._lock:
            if newest_key:
                self._last_seen_router = newest_key
            self._save_state()

    async def _poll_pool(
        self,
        bot: Bot,
        channel: str,
        pool: PoolInfo,
        wco_price: Optional[Decimal],
    ) -> None:
        """Poll a specific pool for WCO transactions."""
        pool_addr_lower = pool.address.lower()

        async with self._lock:
            last_seen = self._last_seen_by_pool.get(pool_addr_lower)

        payload = await self.wchain.get_address_transactions(
            pool.address,
            direction="all",
            page_size=self.settings.wco_dex_poll_page_size,
        )
        items = (payload or {}).get("items") or []
        if not items:
            return

        # Collect new items
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
            return

        newest_hash = str(new_items[0].get("hash"))
        new_items.reverse()  # oldest-first
        alerts_sent = 0

        for item in new_items:
            tx_hash = str(item.get("hash") or "")
            if not tx_hash:
                continue

            async with self._lock:
                if tx_hash in self._processed_tx_hashes:
                    continue

            amount = self._parse_wco_amount(item.get("value"))
            if amount is None or amount <= 0:
                continue

            from_obj = item.get("from") or {}
            to_obj = item.get("to") or {}
            from_addr = from_obj.get("hash", "") if isinstance(from_obj, dict) else ""
            to_addr = to_obj.get("hash", "") if isinstance(to_obj, dict) else ""

            if not from_addr or not to_addr:
                continue

            from_lower = str(from_addr).lower()
            to_lower = str(to_addr).lower()

            # Determine event type
            event_type: Optional[AlertType] = None
            min_threshold: Decimal = Decimal(0)

            if to_lower == pool_addr_lower and from_lower != pool_addr_lower:
                # WCO entering pool
                # Check if this is liquidity add (LP tokens minted) or sell
                is_liquidity = await self._check_liquidity_mint(tx_hash, pool)
                if is_liquidity:
                    event_type = AlertType.LIQUIDITY_ADDED
                    min_threshold = Decimal(str(self.settings.wco_dex_min_liquidity_wco))
                else:
                    event_type = AlertType.SELL
                    min_threshold = Decimal(str(self.settings.wco_dex_min_sell_wco))

            elif from_lower == pool_addr_lower and to_lower != pool_addr_lower:
                # WCO leaving pool
                # Check if this is liquidity remove (LP tokens burned) or buy
                is_liquidity = await self._check_liquidity_burn(tx_hash, pool)
                if is_liquidity:
                    event_type = AlertType.LIQUIDITY_REMOVED
                    min_threshold = Decimal(str(self.settings.wco_dex_min_liquidity_wco))
                else:
                    event_type = AlertType.BUY
                    min_threshold = Decimal(str(self.settings.wco_dex_min_buy_wco))

            if event_type is None:
                continue

            if amount < min_threshold:
                logger.debug(
                    "Skipping %s event: %.2f WCO below threshold %.2f",
                    event_type.value,
                    amount,
                    min_threshold,
                )
                continue

            usd_value = amount * wco_price if wco_price else None

            # Determine the wallet (user) address
            wallet_addr = from_addr if event_type in (AlertType.SELL, AlertType.LIQUIDITY_ADDED) else to_addr

            event = WCODexEvent(
                unique_key=tx_hash,
                tx_hash=tx_hash,
                alert_type=event_type,
                amount_wco=amount,
                usd_value=usd_value,
                price_wco=wco_price,
                from_address=str(from_addr),
                to_address=str(to_addr),
                pool_name=pool.name,
                timestamp=item.get("timestamp"),
            )
            text = self._render_alert(event)
            await self._send_to_channel(bot, channel, text)
            alerts_sent += 1

            async with self._lock:
                self._mark_processed(tx_hash)

        if alerts_sent > 0:
            logger.info(
                "Sent %d %s alert(s) to channel %s.",
                alerts_sent,
                pool.name,
                channel,
            )

        async with self._lock:
            self._last_seen_by_pool[pool_addr_lower] = newest_hash
            self._save_state()

    async def _poll_whale_transfers(
        self,
        bot: Bot,
        channel: str,
        wco_price: Optional[Decimal],
    ) -> None:
        """
        Poll recent transactions for large native WCO transfers
        that do NOT involve any known pool or exchange addresses.
        """
        async with self._lock:
            last_seen = self._last_seen_whale_tx

        payload = await self.wchain.get_recent_transactions(
            page_size=self.settings.wco_dex_poll_page_size,
            filter_type="validated",
        )
        items = (payload or {}).get("items") or []
        if not items:
            return

        # Collect new items
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
            return

        newest_hash = str(new_items[0].get("hash"))
        new_items.reverse()  # oldest-first
        alerts_sent = 0
        whale_threshold = Decimal(str(self.settings.wco_dex_whale_threshold_wco))

        # Combine excluded addresses (pools + exchanges + router)
        excluded_addresses = (
            self._pool_addresses_lower
            | self._exchange_addresses_lower
            | {self.settings.wswap_router_address.lower()}
        )

        for item in new_items:
            tx_hash = str(item.get("hash") or "")
            if not tx_hash:
                continue

            async with self._lock:
                if tx_hash in self._processed_tx_hashes:
                    continue

            # Only process transactions with native value transfer
            amount = self._parse_wco_amount(item.get("value"))
            if amount is None or amount <= 0:
                continue

            # Must be above whale threshold
            if amount < whale_threshold:
                continue

            from_obj = item.get("from") or {}
            to_obj = item.get("to") or {}
            from_addr = from_obj.get("hash", "") if isinstance(from_obj, dict) else ""
            to_addr = to_obj.get("hash", "") if isinstance(to_obj, dict) else ""

            if not from_addr or not to_addr:
                continue

            from_lower = str(from_addr).lower()
            to_lower = str(to_addr).lower()

            # Skip if either address is a pool, exchange, or router
            if from_lower in excluded_addresses or to_lower in excluded_addresses:
                continue

            # Skip contract calls that might be swaps (check tx_types or method)
            tx_types = item.get("tx_types") or []
            if "contract_call" in tx_types:
                # This might be a DEX swap, skip for whale alerts
                continue

            # This is a whale transfer
            usd_value = amount * wco_price if wco_price else None

            event = WCODexEvent(
                unique_key=tx_hash,
                tx_hash=tx_hash,
                alert_type=AlertType.WHALE_MOVE,
                amount_wco=amount,
                usd_value=usd_value,
                price_wco=wco_price,
                from_address=str(from_addr),
                to_address=str(to_addr),
                pool_name=None,
                timestamp=item.get("timestamp"),
            )
            text = self._render_alert(event)
            await self._send_to_channel(bot, channel, text)
            alerts_sent += 1

            async with self._lock:
                self._mark_processed(tx_hash)

        if alerts_sent > 0:
            logger.info("Sent %d whale transfer alert(s) to channel %s.", alerts_sent, channel)

        async with self._lock:
            self._last_seen_whale_tx = newest_hash
            self._save_state()

    async def _check_liquidity_mint(self, tx_hash: str, pool: PoolInfo) -> bool:
        """
        Check if LP tokens were minted in this transaction.
        LP mint = transfer from 0x0 address.
        """
        if not pool.lp_token_address:
            return False

        payload = await self.wchain.get_transaction_token_transfers(tx_hash)
        items = (payload or {}).get("items") or []

        lp_addr_lower = pool.lp_token_address.lower()
        for transfer in items:
            token = transfer.get("token") or {}
            token_addr = token.get("address", "")
            if str(token_addr).lower() != lp_addr_lower:
                continue

            from_obj = transfer.get("from") or {}
            from_addr = from_obj.get("hash", "") if isinstance(from_obj, dict) else ""
            if str(from_addr).lower() == ZERO_ADDRESS:
                return True

        return False

    async def _check_liquidity_burn(self, tx_hash: str, pool: PoolInfo) -> bool:
        """
        Check if LP tokens were burned in this transaction.
        LP burn = transfer to 0x0 address.
        """
        if not pool.lp_token_address:
            return False

        payload = await self.wchain.get_transaction_token_transfers(tx_hash)
        items = (payload or {}).get("items") or []

        lp_addr_lower = pool.lp_token_address.lower()
        for transfer in items:
            token = transfer.get("token") or {}
            token_addr = token.get("address", "")
            if str(token_addr).lower() != lp_addr_lower:
                continue

            to_obj = transfer.get("to") or {}
            to_addr = to_obj.get("hash", "") if isinstance(to_obj, dict) else ""
            if str(to_addr).lower() == ZERO_ADDRESS:
                return True

        return False

    async def _get_wco_price(self) -> Optional[Decimal]:
        """Fetch current WCO price."""
        try:
            data = await self.wchain.get_wco_price()
            if data and "price" in data:
                return Decimal(str(data["price"]))
        except Exception as exc:
            logger.warning("Failed to fetch WCO price: %s", exc)
        return None

    def _render_alert(self, event: WCODexEvent) -> str:
        """Render alert message in Telegram MarkdownV2 format."""
        amount_display = escape_markdown_v2(format_token_amount(event.amount_wco))

        if event.usd_value is not None:
            usd_display = escape_markdown_v2(format_usd(event.usd_value))
        else:
            usd_display = "N/A"

        if event.price_wco is not None:
            price_display = escape_markdown_v2(f"${float(event.price_wco):.6f}")
        else:
            price_display = "N/A"

        pool_name = escape_markdown_v2(event.pool_name or "Unknown Pool")
        tx_hash = event.tx_hash
        tx_hash_short = escape_markdown_v2(f"{tx_hash[:10]}...{tx_hash[-8:]}")
        explorer_link = f"https://scan.w-chain.com/tx/{tx_hash}"

        if event.alert_type == AlertType.BUY:
            wallet = escape_markdown_v2(event.to_address)
            return (
                f"🟢 *WCO BUY*\n\n"
                f"💰 *Amount:* {amount_display} WCO\n"
                f"💵 *Value:* {usd_display}\n"
                f"📊 *Price:* {price_display}\n"
                f"👤 *Buyer:* `{wallet[:10]}...{wallet[-8:]}`\n"
                f"🏊 *Pool:* {pool_name}\n"
                f"🔗 [View Tx]({explorer_link})"
            )

        elif event.alert_type == AlertType.SELL:
            wallet = escape_markdown_v2(event.from_address)
            return (
                f"🔴 *WCO SELL*\n\n"
                f"💰 *Amount:* {amount_display} WCO\n"
                f"💵 *Value:* {usd_display}\n"
                f"📊 *Price:* {price_display}\n"
                f"👤 *Seller:* `{wallet[:10]}...{wallet[-8:]}`\n"
                f"🏊 *Pool:* {pool_name}\n"
                f"🔗 [View Tx]({explorer_link})"
            )

        elif event.alert_type == AlertType.LIQUIDITY_ADDED:
            wallet = escape_markdown_v2(event.from_address)
            return (
                f"💦 *LIQUIDITY ADDED*\n\n"
                f"💰 *WCO Added:* {amount_display} WCO\n"
                f"💵 *Value:* {usd_display}\n"
                f"👤 *Provider:* `{wallet[:10]}...{wallet[-8:]}`\n"
                f"🏊 *Pool:* {pool_name}\n"
                f"🔗 [View Tx]({explorer_link})"
            )

        elif event.alert_type == AlertType.LIQUIDITY_REMOVED:
            wallet = escape_markdown_v2(event.to_address)
            return (
                f"🔥 *LIQUIDITY REMOVED*\n\n"
                f"💰 *WCO Removed:* {amount_display} WCO\n"
                f"💵 *Value:* {usd_display}\n"
                f"👤 *Provider:* `{wallet[:10]}...{wallet[-8:]}`\n"
                f"🏊 *Pool:* {pool_name}\n"
                f"🔗 [View Tx]({explorer_link})"
            )

        elif event.alert_type == AlertType.WHALE_MOVE:
            from_wallet = escape_markdown_v2(event.from_address)
            to_wallet = escape_markdown_v2(event.to_address)
            return (
                f"🐋 *WHALE MOVE*\n\n"
                f"💰 *Amount:* {amount_display} WCO\n"
                f"💵 *Value:* {usd_display}\n"
                f"📤 *From:* `{from_wallet[:10]}...{from_wallet[-8:]}`\n"
                f"📥 *To:* `{to_wallet[:10]}...{to_wallet[-8:]}`\n"
                f"🔗 [View Tx]({explorer_link})"
            )

        return f"Unknown alert type: {event.alert_type}"

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
            auto_delete_seconds = self.settings.wco_dex_auto_delete_seconds
            if auto_delete_seconds > 0 and self._job_queue:
                self._job_queue.run_once(
                    self._delete_message_callback,
                    when=auto_delete_seconds,
                    data={"chat_id": channel, "message_id": message.message_id},
                    name=f"delete_msg_{message.message_id}",
                )
                logger.debug(
                    "Scheduled auto-delete for message %s in %d seconds.",
                    message.message_id,
                    auto_delete_seconds,
                )
        except Exception:
            logger.exception("Failed to send WCO DEX alert to channel=%s", channel)

    async def _delete_message_callback(self, context) -> None:
        """Callback to delete a message after the auto-delete delay."""
        data = context.job.data
        chat_id = data.get("chat_id")
        message_id = data.get("message_id")
        
        if not chat_id or not message_id:
            return
            
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            logger.debug("Auto-deleted message %s from channel %s.", message_id, chat_id)
        except TelegramError as e:
            # Message might already be deleted or bot lacks permission
            logger.debug("Could not delete message %s: %s", message_id, e)

    def _mark_processed(self, tx_hash: str) -> None:
        """Mark a transaction as processed (must be called within lock)."""
        self._processed_tx_hashes.add(tx_hash)
        # Limit cache size
        if len(self._processed_tx_hashes) > self._max_processed_cache:
            # Remove oldest entries (convert to list, slice, convert back)
            excess = len(self._processed_tx_hashes) - self._max_processed_cache
            to_remove = list(self._processed_tx_hashes)[:excess]
            for h in to_remove:
                self._processed_tx_hashes.discard(h)

    @staticmethod
    def _unique_key_internal(item: Optional[Dict[str, Any]]) -> Optional[str]:
        """Generate unique key for internal transaction."""
        if not item:
            return None
        tx_hash = item.get("transaction_hash")
        idx = item.get("index")
        if not tx_hash or idx is None:
            return None
        return f"{str(tx_hash)}:{str(idx)}"

    @staticmethod
    def _parse_wco_amount(value_wei: Any) -> Optional[Decimal]:
        """Parse WCO amount from wei value."""
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
        """Load persisted state from file."""
        try:
            raw = self._state_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError:
            logger.exception("Failed to read WCO DEX alert state from %s", self._state_path)
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("WCO DEX alert state file is invalid JSON: %s", self._state_path)
            return

        section = (data or {}).get("wco_dex") or {}

        # Load last seen by pool
        last_seen_map = section.get("last_seen_by_pool") or {}
        if isinstance(last_seen_map, dict):
            for k, v in last_seen_map.items():
                if isinstance(k, str) and isinstance(v, str) and k and v:
                    self._last_seen_by_pool[k.lower()] = v

        # Load last seen router
        last_seen_router = section.get("last_seen_router")
        if isinstance(last_seen_router, str) and last_seen_router:
            self._last_seen_router = last_seen_router

        # Load last seen whale tx
        last_seen_whale = section.get("last_seen_whale_tx")
        if isinstance(last_seen_whale, str) and last_seen_whale:
            self._last_seen_whale_tx = last_seen_whale

        # Load alerts enabled state
        alerts_enabled = section.get("alerts_enabled")
        if isinstance(alerts_enabled, bool):
            self._alerts_enabled = alerts_enabled

        # Load processed tx hashes
        processed = section.get("processed_tx_hashes") or []
        if isinstance(processed, list):
            for h in processed[-self._max_processed_cache :]:
                if isinstance(h, str) and h:
                    self._processed_tx_hashes.add(h)

    def _save_state(self) -> None:
        """Persist state to file."""
        data: Dict[str, Any] = {}
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}

        data["wco_dex"] = {
            "last_seen_by_pool": dict(self._last_seen_by_pool),
            "last_seen_router": self._last_seen_router,
            "last_seen_whale_tx": self._last_seen_whale_tx,
            "alerts_enabled": self._alerts_enabled,
            "processed_tx_hashes": list(self._processed_tx_hashes)[-self._max_processed_cache :],
            "channel": self.settings.wco_dex_alert_channel_id,
            "pools": [p.address for p in self._pools],
        }
        try:
            self._state_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        except OSError:
            logger.exception("Failed to write WCO DEX alert state to %s", self._state_path)
