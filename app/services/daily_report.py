"""Daily crypto metrics report service."""

import asyncio
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from telegram import Bot
from telegram.ext import ContextTypes

from app.clients.wchain import WChainClient
from app.config import Settings
from app.utils import format_token_amount, format_usd

logger = logging.getLogger(__name__)


@dataclass
class DailyMetrics:
    """Snapshot of daily metrics."""
    timestamp: str
    holders: Optional[int] = None
    transactions: Optional[int] = None
    volume_moved: Optional[float] = None
    circulating_supply: Optional[float] = None
    market_cap: Optional[float] = None
    burned: Optional[float] = None
    price: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DailyMetrics":
        return cls(
            timestamp=data.get("timestamp", ""),
            holders=data.get("holders"),
            transactions=data.get("transactions"),
            volume_moved=data.get("volume_moved"),
            circulating_supply=data.get("circulating_supply"),
            market_cap=data.get("market_cap"),
            burned=data.get("burned"),
            price=data.get("price"),
        )


class DailyReportService:
    """
    Sends a daily metrics report at a scheduled time with comparisons
    to the previous day's values.
    """

    def __init__(self, settings: Settings, wchain: WChainClient):
        self.settings = settings
        self.wchain = wchain
        self._lock = asyncio.Lock()
        self._state_path = Path(self.settings.daily_report_state_path)
        self._previous_metrics: Optional[DailyMetrics] = None
        self._load_state()

    async def ensure_initialized(self) -> None:
        """
        On cold start, fetch current metrics as baseline if we don't have
        previous data stored.
        """
        async with self._lock:
            if self._previous_metrics is not None:
                logger.info(
                    "Daily report service initialized with previous metrics from %s",
                    self._previous_metrics.timestamp,
                )
                return

        # Fetch current metrics as baseline
        current = await self._fetch_current_metrics()
        if current:
            async with self._lock:
                if self._previous_metrics is None:
                    self._previous_metrics = current
                    self._save_state()
                    logger.info(
                        "Daily report service initialized with baseline metrics."
                    )

    async def job_callback(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Called by the job scheduler to send the daily report."""
        await self.send_daily_report(context.bot)

    async def send_daily_report(self, bot: Bot) -> None:
        """Fetch current metrics, compare to previous day, and send report."""
        if not self.settings.daily_report_enabled:
            logger.debug("Daily report disabled, skipping.")
            return

        channel_id = self.settings.daily_report_channel_id
        if not channel_id:
            logger.warning("Daily report channel ID not configured, skipping.")
            return

        # Fetch current metrics
        current = await self._fetch_current_metrics()
        if not current:
            logger.error("Failed to fetch current metrics for daily report.")
            return

        # Get previous metrics for comparison
        async with self._lock:
            previous = self._previous_metrics

        # Generate and send the report
        message = self._render_report(current, previous)

        try:
            await bot.send_message(
                chat_id=channel_id,
                text=message,
                parse_mode="Markdown",
            )
            logger.info("Daily report sent to channel %s", channel_id)
        except Exception:
            logger.exception("Failed to send daily report to channel %s", channel_id)
            return

        # Update previous metrics for tomorrow's comparison
        async with self._lock:
            self._previous_metrics = current
            self._save_state()

    async def _fetch_current_metrics(self) -> Optional[DailyMetrics]:
        """Fetch all metrics needed for the daily report."""
        try:
            # Fetch price, supply, and token counters in parallel
            price_data, supply_data, counters = await asyncio.gather(
                self.wchain.get_wco_price(),
                self.wchain.get_wco_supply(),
                self._get_wco_counters(),
            )

            # Extract price
            price = self._safe_float(price_data, "price")

            # Extract supply metrics
            summary = (supply_data or {}).get("summary", {})
            circulating = self._safe_float(summary, "circulating_supply_wco")
            burned = self._safe_float(summary, "burned_supply_wco")

            # Calculate market cap
            market_cap = price * circulating if (price and circulating) else None

            # Extract counters (holders, transfers)
            holders = None
            transactions = None
            if counters:
                holders = self._safe_int(counters, "token_holders_count")
                transactions = self._safe_int(counters, "transfers_count")

            # Volume moved - we'll track the change in circulating supply as a proxy
            # In a real implementation, this would come from a 24h volume API
            volume_moved = self._safe_float(summary, "volume_24h_wco")

            return DailyMetrics(
                timestamp=datetime.utcnow().isoformat(),
                holders=holders,
                transactions=transactions,
                volume_moved=volume_moved,
                circulating_supply=circulating,
                market_cap=market_cap,
                burned=burned,
                price=price,
            )
        except Exception:
            logger.exception("Error fetching daily metrics")
            return None

    async def _get_wco_counters(self) -> Optional[Dict]:
        """Fetch WCO token counters from WWCO contract."""
        wwco_address = self.settings.wwco_token_address
        if not wwco_address:
            return None
        return await self.wchain.get_token_counters(wwco_address)

    def _render_report(
        self, current: DailyMetrics, previous: Optional[DailyMetrics]
    ) -> str:
        """Render the daily report message with comparisons."""
        # Get current date for header
        now = datetime.utcnow()
        day_name = now.strftime("%A")
        date_str = now.strftime("%B %d, %Y")

        lines = [
            "✅ *Daily Update*\n",
            f"W-Ocean Daily Update 📅 {day_name}, {date_str}\n",
        ]

        # Total Holders
        holders_line = self._format_metric_line(
            "🌊 Total Holders",
            current.holders,
            previous.holders if previous else None,
            is_currency=False,
            decimals=0,
            inverse_sentiment=False,  # More holders is good
        )
        lines.append(holders_line)

        # Transactions
        tx_line = self._format_metric_line(
            "💱 Transactions",
            current.transactions,
            previous.transactions if previous else None,
            is_currency=False,
            decimals=0,
            inverse_sentiment=False,  # More transactions is good
        )
        lines.append(tx_line)

        # Volume Moved
        volume_line = self._format_metric_line(
            "💰 Volume Moved",
            current.volume_moved,
            previous.volume_moved if previous else None,
            is_currency=False,
            decimals=0,
            suffix=" WCO",
            inverse_sentiment=False,  # More volume is good
        )
        lines.append(volume_line)

        # Circulating Supply
        circ_line = self._format_metric_line(
            "🪙 Circulating Supply",
            current.circulating_supply,
            previous.circulating_supply if previous else None,
            is_currency=False,
            decimals=0,
            suffix=" WCO",
            inverse_sentiment=True,  # Less circulating is generally better (deflationary)
        )
        lines.append(circ_line)

        # Market Cap
        mcap_line = self._format_metric_line(
            "📈 Market Cap",
            current.market_cap,
            previous.market_cap if previous else None,
            is_currency=True,
            decimals=0,
            inverse_sentiment=False,  # Higher market cap is good
        )
        lines.append(mcap_line)

        # WCO Burnt
        burn_line = self._format_metric_line(
            "🔥 WCO Burnt",
            current.burned,
            previous.burned if previous else None,
            is_currency=False,
            decimals=0,
            suffix=" WCO",
            inverse_sentiment=False,  # More burn is good
        )
        lines.append(burn_line)

        # Footer hashtags
        lines.append("\n#WCO #WChain #CryptoUpdate #DeFi")

        return "\n".join(lines)

    def _format_metric_line(
        self,
        label: str,
        current_value: Optional[float],
        previous_value: Optional[float],
        is_currency: bool = False,
        decimals: int = 0,
        suffix: str = "",
        inverse_sentiment: bool = False,
    ) -> str:
        """Format a single metric line with change indicator."""
        if current_value is None:
            return f"{label}: N/A"

        # Format current value
        if is_currency:
            formatted_value = f"${current_value:,.{decimals}f}"
        else:
            formatted_value = f"{current_value:,.{decimals}f}{suffix}"

        # Calculate and format change
        if previous_value is not None and previous_value != 0:
            change = current_value - previous_value
            if change >= 0:
                change_str = f"+{change:,.{decimals}f}"
            else:
                change_str = f"{change:,.{decimals}f}"

            # Determine sentiment (green/red indicator)
            is_positive = change > 0
            if inverse_sentiment:
                is_positive = not is_positive

            indicator = "🟢" if is_positive else "🔴"
            if change == 0:
                indicator = "⚪"

            if is_currency:
                return f"{label}: {formatted_value} ({change_str}) {indicator}"
            else:
                return f"{label}: {formatted_value} ({change_str}) {indicator}"
        else:
            return f"{label}: {formatted_value}"

    def _load_state(self) -> None:
        """Load previous metrics from state file."""
        try:
            raw = self._state_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError:
            logger.exception(
                "Failed to read daily report state from %s", self._state_path
            )
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(
                "Daily report state file is invalid JSON: %s", self._state_path
            )
            return

        daily_report = (data or {}).get("daily_report") or {}
        previous = daily_report.get("previous_metrics")
        if previous:
            self._previous_metrics = DailyMetrics.from_dict(previous)

    def _save_state(self) -> None:
        """Save current metrics to state file for next day comparison."""
        data: Dict[str, Any] = {}
        # Preserve other watcher sections if sharing a state file
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}

        data["daily_report"] = {
            "previous_metrics": (
                self._previous_metrics.to_dict() if self._previous_metrics else None
            ),
        }

        try:
            self._state_path.write_text(
                json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
            )
        except OSError:
            logger.exception(
                "Failed to write daily report state to %s", self._state_path
            )

    @staticmethod
    def _safe_float(payload: Optional[Dict], key: str) -> Optional[float]:
        if not payload:
            return None
        value = payload.get(key)
        if value in (None, "", "NaN"):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_int(payload: Optional[Dict], key: str) -> Optional[int]:
        if not payload:
            return None
        value = payload.get(key)
        if value in (None, "", "NaN"):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
