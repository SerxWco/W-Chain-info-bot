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
    # Buyback alert settings (incoming native WCO to a watched wallet)
    buyback_alerts_enabled: bool = field(
        default_factory=lambda: os.getenv("BUYBACK_ALERTS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    )
    buyback_wallet_address: str = field(
        default_factory=lambda: os.getenv(
            "BUYBACK_WALLET_ADDRESS", "0x81d29c0DcD64fAC05C4A394D455cbD79D210C200"
        ).strip()
    )
    buyback_poll_seconds: int = field(default_factory=lambda: int(os.getenv("BUYBACK_POLL_SECONDS", "30")))
    buyback_poll_page_size: int = field(default_factory=lambda: int(os.getenv("BUYBACK_POLL_PAGE_SIZE", "25")))
    buyback_min_amount_wco: float = field(default_factory=lambda: float(os.getenv("BUYBACK_MIN_AMOUNT_WCO", "0")))
    buyback_alert_state_path: str = field(default_factory=lambda: os.getenv("BUYBACK_ALERT_STATE_PATH", ".alert_state.json"))
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
            TokenProfile(
                symbol="SOL",
                name="Binance-Peg SOL",
                description="Bridged SOL liquidity supporting cross-chain LP strategies on W-Chain.",
                contract="0xd4F93CACD6d607789c8eCF1DdDEba8B0c4D915A8",
                info_url="https://scan.w-chain.com/address/0xd4F93CACD6d607789c8eCF1DdDEba8B0c4D915A8",
            ),
            TokenProfile(
                symbol="XRP",
                name="Binance-Peg XRP",
                description="High-throughput XRP exposure for remittance and settlement apps.",
                contract="0x4560d5EB0C32A05fA59Acd2E8D639F84A15A2414",
                info_url="https://scan.w-chain.com/address/0x4560d5EB0C32A05fA59Acd2E8D639F84A15A2414",
            ),
            TokenProfile(
                symbol="USDT",
                name="USDT",
                description="Native Tether USD pools used across W-Swap and money markets.",
                contract="0x40CB2CCcF80Ed2192b53FB09720405F6Fe349743",
                info_url="https://scan.w-chain.com/address/0x40CB2CCcF80Ed2192b53FB09720405F6Fe349743",
            ),
            TokenProfile(
                symbol="BUSDT",
                name="Binance-Peg USDT",
                description="Binance-pegged Tether rail enabling arbitrage between CeFi and W-Chain.",
                contract="0x0Ab978880D3Bf13E448F4F773Acd817e83bDdB0E",
                info_url="https://scan.w-chain.com/address/0x0Ab978880D3Bf13E448F4F773Acd817e83bDdB0E",
            ),
            TokenProfile(
                symbol="USDC",
                name="USDC",
                description="Regulated USD Coin powering settlements for institutional partners.",
                contract="0x643eC74Ed2B79098A37Dc45dcc7F1AbfE2AdE6d8",
                info_url="https://scan.w-chain.com/address/0x643eC74Ed2B79098A37Dc45dcc7F1AbfE2AdE6d8",
            ),
            TokenProfile(
                symbol="BUSDC",
                name="Binance-Peg USDC",
                description="Pegged USDC route bridging Binance liquidity into W-Chain DeFi vaults.",
                contract="0x9B4805Dc867C279A96F3Ed0745C8bc15153A22E6",
                info_url="https://scan.w-chain.com/address/0x9B4805Dc867C279A96F3Ed0745C8bc15153A22E6",
            ),
            TokenProfile(
                symbol="DOGE",
                name="Binance-Peg DOGE",
                description="DOGE exposure for meme and community pools on W-Chain DEXs.",
                contract="0x6cdfdA79787cAA4ad1a95456095beDc95aBd2d75",
                info_url="https://scan.w-chain.com/address/0x6cdfdA79787cAA4ad1a95456095beDc95aBd2d75",
            ),
            TokenProfile(
                symbol="WWCO",
                name="Wrapped WCO",
                description="ERC-20 representation of WCO for custodial integrations and cross-chain swaps.",
                contract="0xEdB8008031141024d50cA2839A607B2f82C1c045",
                info_url="https://scan.w-chain.com/address/0xEdB8008031141024d50cA2839A607B2f82C1c045",
            ),
            TokenProfile(
                symbol="OG-88",
                name="OG-88",
                description="Community reward token for OG-88 gaming and NFT ecosystem initiatives.",
                contract="0xD1841fC048b488d92fdF73624a2128D10A847E88",
                info_url="https://scan.w-chain.com/address/0xD1841fC048b488d92fdF73624a2128D10A847E88",
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

