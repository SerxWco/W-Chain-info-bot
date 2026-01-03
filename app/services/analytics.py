import asyncio
from typing import Dict, Iterable, Optional

from app.clients import ReferencePriceClient, WChainClient
from app.config import Settings


class AnalyticsService:
    """Coordinates upstream data sources to serve bot commands."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.wchain = WChainClient(settings)
        self.reference = ReferencePriceClient(settings)

    async def build_wco_overview(self) -> Dict:
        price_data, supply_data, stats = await asyncio.gather(
            self.wchain.get_wco_price(),
            self.wchain.get_wco_supply(),
            self.wchain.get_network_stats(),
        )

        price = _safe_float(price_data, "price")
        summary = (supply_data or {}).get("summary", {})
        total_supply = _safe_float(summary, "initial_supply_wco")
        burned = _safe_float(summary, "burned_supply_wco")
        circulating = _safe_float(summary, "circulating_supply_wco")
        locked = _safe_float(summary, "locked_supply_wco")
        total_after_burn = (total_supply or 0) - (burned or 0)

        distribution = _build_distribution(
            circulating=circulating,
            locked=locked,
            burned=burned,
            baseline=total_after_burn if total_after_burn > 0 else circulating,
        )

        market_cap = price * circulating if (price is not None and circulating) else None

        return {
            "price": price,
            "market_cap": market_cap,
            "circulating": circulating,
            "locked": locked,
            "burned": burned,
            "total": total_after_burn if total_after_burn > 0 else total_supply,
            "distribution": distribution,
            "last_updated": (price_data or {}).get("last_updated"),
            "network": stats or {},
        }

    async def build_wave_overview(self) -> Dict:
        wave_price_data, wco_price_data, counters = await asyncio.gather(
            self.wchain.get_wave_price(),
            self.wchain.get_wco_price(),
            self._get_wave_counters(),
        )
        wave_price = _safe_float(wave_price_data, "price")
        wco_price = _safe_float(wco_price_data, "price")

        return {
            "price_usd": wave_price,
            "price_wco": (wave_price / wco_price) if wave_price and wco_price else None,
            "counters": counters or {},
        }

    async def price_lookup(self, symbols: Optional[Iterable[str]]) -> Dict[str, Optional[float]]:
        symbols = list(symbols) if symbols else self.settings.default_price_symbols
        symbols = [symbol.upper() for symbol in symbols if symbol]

        result: Dict[str, Optional[float]] = {symbol: None for symbol in symbols}
        if not symbols:
            return result

        wchain_map = {}
        if "WCO" in result:
            wchain_map["WCO"] = await self.wchain.get_wco_price()
        if "WAVE" in result:
            wchain_map["WAVE"] = await self.wchain.get_wave_price()

        for symbol, payload in wchain_map.items():
            result[symbol] = _safe_float(payload, "price")

        remaining = [symbol for symbol in symbols if result.get(symbol) is None]
        if remaining:
            reference_prices = await self.reference.get_prices(remaining)
            for symbol, price in reference_prices.items():
                result[symbol] = price

        return result

    async def network_stats(self) -> Dict:
        stats = await self.wchain.get_network_stats() or {}
        gas_prices = stats.get("gas_prices") or {}

        last_block = _safe_float(stats, "total_blocks") or _safe_float(stats, "last_block")
        tx_count = _safe_float(stats, "total_transactions") or _safe_float(stats, "transactions_count")
        wallets = _safe_float(stats, "total_addresses") or _safe_float(stats, "addresses_count")
        gas = _safe_float(gas_prices, "average") or _safe_float(gas_prices, "fast") or _safe_float(stats, "static_gas_price")

        return {
            "last_block": last_block,
            "tx_count": tx_count,
            "wallets": wallets,
            "gas": gas,
            "gas_details": gas_prices,
        }

    async def _get_wave_counters(self) -> Optional[Dict]:
        contract = self.settings.wave_contract
        if not contract:
            return None
        return await self.wchain.get_token_counters(contract)

    async def build_token_overview(self, symbol: str) -> Optional[Dict]:
        """Build overview for a specific token from the catalog."""
        symbol_upper = symbol.upper()
        profile = next(
            (t for t in self.settings.token_catalog if t.symbol.upper() == symbol_upper),
            None,
        )
        if not profile:
            return None

        # Fetch price
        prices = await self.price_lookup([symbol_upper])
        price = prices.get(symbol_upper)

        # Fetch counters if contract exists
        counters = None
        if profile.contract:
            counters = await self.wchain.get_token_counters(profile.contract)

        return {
            "symbol": profile.symbol,
            "name": profile.name,
            "description": profile.description,
            "contract": profile.contract,
            "info_url": profile.info_url,
            "price_usd": price,
            "counters": counters,
        }


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


def _build_distribution(
    *, circulating: Optional[float], locked: Optional[float], burned: Optional[float], baseline: Optional[float]
) -> Dict[str, Optional[float]]:
    total = baseline or 0
    if not total:
        return {"circulating": None, "locked": None, "burned": None}
    return {
        "circulating": (circulating or 0) / total * 100,
        "locked": (locked or 0) / total * 100,
        "burned": (burned or 0) / total * 100,
    }

