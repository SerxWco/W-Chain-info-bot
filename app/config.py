import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class TokenProfile:
    """Metadata describing a catalogued W-Chain ecosystem token."""

    symbol: str
    name: str
    description: str
    contract: Optional[str] = None
    info_url: Optional[str] = None


@dataclass
class Settings:
    """Centralised configuration for the Telegram bot."""

    telegram_token: str
    wco_price_api: str = "https://oracle.w-chain.com/api/price/wco"
    wave_price_api: str = "https://oracle.w-chain.com/api/price/wave"
    wco_supply_api: str = "https://oracle.w-chain.com/api/wco/supply-info"
    blockscout_base: str = field(
        default_factory=lambda: os.getenv("BLOCKSCOUT_API_BASE", "https://scan.w-chain.com/api/v2")
    )
    http_timeout: float = field(default_factory=lambda: float(os.getenv("HTTP_TIMEOUT", "12")))
    cache_price_ttl: int = field(default_factory=lambda: int(os.getenv("PRICE_CACHE_TTL", "60")))
    cache_supply_ttl: int = field(default_factory=lambda: int(os.getenv("SUPPLY_CACHE_TTL", "120")))
    cache_stats_ttl: int = field(default_factory=lambda: int(os.getenv("STATS_CACHE_TTL", "45")))
    coin_prices_url: str = "https://api.coingecko.com/api/v3/simple/price"
    coingecko_ids: Dict[str, str] = field(
        default_factory=lambda: {
            "USDT": "tether",
            "USDC": "usd-coin",
            "BTC": "bitcoin",
            "ETH": "ethereum",
        }
    )
    default_price_symbols: List[str] = field(default_factory=lambda: ["WCO", "WAVE", "USDT", "USDC"])
    token_catalog: List[TokenProfile] = field(
        default_factory=lambda: [
            TokenProfile(
                symbol="WCO",
                name="W-Chain Token",
                description="Primary gas, security, and governance asset for W-Chain.",
                info_url="https://wchain.cc/",
            ),
            TokenProfile(
                symbol="WAVE",
                name="WAVE",
                description="Liquidity mining and reward token powering W-Swap incentives.",
                contract="0x42abfb13b4e3d25407ffa9705146b7cb812404a0",
                info_url="https://app.w-swap.com/#/",
            ),
            TokenProfile(
                symbol="WUSD",
                name="Wrapped USD",
                description="Protocol-backed stable asset used across W-Chain dApps.",
            ),
        ]
    )

    @property
    def wave_contract(self) -> Optional[str]:
        return next((token.contract for token in self.token_catalog if token.symbol == "WAVE"), None)

    @property
    def stats_endpoint(self) -> str:
        return f"{self.blockscout_base}/stats"

    @property
    def gas_oracle_endpoint(self) -> str:
        return f"{self.blockscout_base}/gas-price-oracle"

    @staticmethod
    def _require(key: str, value: Optional[str]) -> str:
        if not value:
            raise RuntimeError(f"Missing required environment variable '{key}'.")
        return value

    @classmethod
    def from_env(cls) -> "Settings":
        token = cls._require("TELEGRAM_BOT_TOKEN", os.getenv("TELEGRAM_BOT_TOKEN"))
        return cls(telegram_token=token)

