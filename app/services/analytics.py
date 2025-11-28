import asyncio
from dataclasses import asdict
from typing import Dict, Iterable, List, Optional

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

    async def list_tokens(self) -> List[Dict]:
        overview = []
        wco_data = await self.build_wco_overview()
        wave_data = await self.build_wave_overview()
        reference_prices = await self.reference.get_prices(token.symbol for token in self.settings.token_catalog)

        for token in self.settings.token_catalog:
            profile = asdict(token)
            if token.symbol == "WCO":
                profile.update(
                    {
                        "price": wco_data.get("price"),
                        "market_cap": wco_data.get("market_cap"),
                        "circulating": wco_data.get("circulating"),
                    }
                )
            elif token.symbol == "WAVE":
                profile.update(
                    {
                        "price": wave_data.get("price_usd"),
                        "holders": (wave_data.get("counters") or {}).get("token_holders_count"),
                    }
                )
            else:
                profile.update({"price": reference_prices.get(token.symbol)})
            overview.append(profile)
        return overview

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
        stats, gas = await asyncio.gather(
            self.wchain.get_network_stats(),
            self.wchain.get_gas_oracle(),
        )
        return {
            "last_block": (stats or {}).get("last_block") or (stats or {}).get("block_height"),
            "tx_count": (stats or {}).get("transactions_count") or (stats or {}).get("tx_count"),
            "wallets": (stats or {}).get("addresses_count") or (stats or {}).get("wallets"),
            "gas": (gas or {}).get("average") or (gas or {}).get("medium"),
            "gas_details": gas or {},
        }

    async def _get_wave_counters(self) -> Optional[Dict]:
        contract = self.settings.wave_contract
        if not contract:
            return None
        return await self.wchain.get_token_counters(contract)


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

