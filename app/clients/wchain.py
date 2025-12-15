import asyncio
import logging
from typing import Any, Dict, Iterable, Optional

import httpx

from app.config import Settings
from app.utils import TTLCache

logger = logging.getLogger(__name__)


class WChainClient:
    """Async client responsible for W-Chain native APIs and explorer data."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._cache = TTLCache()

    async def get_wco_price(self) -> Optional[Dict]:
        return await self._fetch_json(
            self.settings.wco_price_api, cache_key="price:wco", ttl=self.settings.cache_price_ttl
        )

    async def get_wave_price(self) -> Optional[Dict]:
        return await self._fetch_json(
            self.settings.wave_price_api, cache_key="price:wave", ttl=self.settings.cache_price_ttl
        )

    async def get_wco_supply(self) -> Optional[Dict]:
        return await self._fetch_json(
            self.settings.wco_supply_api, cache_key="supply:wco", ttl=self.settings.cache_supply_ttl
        )

    async def get_token_counters(self, contract_address: str) -> Optional[Dict]:
        url = f"{self.settings.blockscout_base}/tokens/{contract_address}/counters"
        cache_key = f"token:counters:{contract_address.lower()}"
        return await self._fetch_json(url, cache_key=cache_key, ttl=self.settings.cache_stats_ttl)

    async def get_network_stats(self) -> Optional[Dict]:
        return await self._fetch_json(
            self.settings.stats_endpoint, cache_key="network:stats", ttl=self.settings.cache_stats_ttl
        )

    async def get_gas_oracle(self) -> Optional[Dict]:
        return await self._fetch_json(
            self.settings.gas_oracle_endpoint, cache_key="network:gas", ttl=self.settings.cache_stats_ttl
        )

    async def get_address_transactions(
        self,
        address: str,
        *,
        direction: str = "to",
        page_size: int = 25,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch address transactions from Blockscout.

        direction:
          - "to": incoming transfers / txs where to == address
          - "from": outgoing transfers / txs where from == address
          - "all": no direction filter
        """
        normalized = address
        url = f"{self.settings.blockscout_base}/addresses/{normalized}/transactions"
        params: Dict[str, Any] = {}
        if direction in {"to", "from"}:
            params["filter"] = direction
        if page_size:
            params["page_size"] = int(page_size)

        try:
            async with httpx.AsyncClient(timeout=self.settings.http_timeout) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            logger.warning("HTTP error calling %s: %s", url, exc)
            return None

    async def _fetch_json(self, url: str, cache_key: Optional[str], ttl: Optional[int]) -> Optional[Dict]:
        if cache_key:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        try:
            async with httpx.AsyncClient(timeout=self.settings.http_timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.warning("HTTP error calling %s: %s", url, exc)
            return self._cache.get(cache_key) if cache_key else None

        if cache_key and ttl:
            self._cache.set(cache_key, data, ttl)
        return data


class ReferencePriceClient:
    """Lightweight helper for non W-Chain prices (USDT, USDC, etc.)."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._cache = TTLCache()

    async def get_prices(self, symbols: Iterable[str]) -> Dict[str, Optional[float]]:
        normalized = sorted({symbol.upper() for symbol in symbols})
        coingecko_ids = {
            symbol: self.settings.coingecko_ids.get(symbol)
            for symbol in normalized
            if symbol in self.settings.coingecko_ids
        }

        result = {symbol: None for symbol in normalized}
        if not coingecko_ids:
            return result

        cache_key = "fiat:" + ",".join(normalized)
        cached = self._cache.get(cache_key)
        if cached:
            return {**result, **cached}

        params = {
            "ids": ",".join(filter(None, coingecko_ids.values())),
            "vs_currencies": "usd",
        }

        try:
            async with httpx.AsyncClient(timeout=self.settings.http_timeout) as client:
                response = await client.get(self.settings.coin_prices_url, params=params)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            logger.warning("Failed to fetch reference prices: %s", exc)
            return result

        parsed: Dict[str, Optional[float]] = {}
        for symbol, cg_id in coingecko_ids.items():
            usd_value = payload.get(cg_id, {}).get("usd")
            parsed[symbol] = float(usd_value) if usd_value is not None else None

        self._cache.set(cache_key, parsed, self.settings.cache_price_ttl)
        return {**result, **parsed}

