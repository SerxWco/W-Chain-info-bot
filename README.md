# W-Chain Ecosystem Analytics Bot

Professional Telegram bot that delivers real-time token insights, price feeds, and on-chain health metrics for the W-Chain ecosystem (WCO, WAVE, WUSD, and reference assets such as USDT/USDC).

## Highlights

- **Modern architecture** – layered `app/` package with dedicated clients, services, and handlers.
- **Core command set**
  - `/start` – onboarding and quick guide
  - `/wco` – WCO market & supply analytics
  - `/wave` – WAVE reward token snapshot
  - `/price [symbols]` – multi-token price lookup (defaults to WCO, WAVE, USDT, USDC)
  - `/stats` – network throughput, gas, and wallet activity
  - `/tokens` – featured W-Chain assets and contract references
- **Data sources** – W-Chain Oracle APIs, W-Chain Explorer (Blockscout), CoinGecko reference feeds.
- **Resilient UX** – async HTTP, per-endpoint caching, graceful fallbacks, friendly Markdown responses.

## Project Layout

```
app/
├── bot.py              # Application factory (handlers + Telegram wiring)
├── config.py           # Settings + token catalog definitions
├── handlers/           # Telegram command handlers
├── services/           # Domain logic (analytics aggregation)
├── clients/            # HTTP clients for W-Chain & reference feeds
├── utils/              # Formatting + TTL cache helpers
└── main.py             # Entry point (python -m app.main)
requirements.txt
README.md
env_template.txt
```

## Getting Started

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment**
   ```bash
   cp env_template.txt .env
   # edit .env and set TELEGRAM_BOT_TOKEN plus optional overrides
   ```

3. **Run the bot**
   ```bash
   python -m app.main
   ```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) | **required** |
| `BLOCKSCOUT_API_BASE` | Explorer API base URL | `https://scan.w-chain.com/api/v2` |
| `HTTP_TIMEOUT` | Upstream HTTP timeout (seconds) | `12` |
| `PRICE_CACHE_TTL` | TTL for price cache (seconds) | `60` |
| `SUPPLY_CACHE_TTL` | TTL for supply cache (seconds) | `120` |
| `STATS_CACHE_TTL` | TTL for stats cache (seconds) | `45` |

See `app/config.py` to extend the token catalog or add additional CoinGecko mappings.

## Command Reference

- `/start` – Welcome tour + shortcuts.
- `/wco` – Price, market cap, circulating/locked/burned supplies, and allocation breakdown.
- `/wave` – USD & WCO denominated price plus Blockscout holder/transfer counters.
- `/price BTC ETH` – On-demand lookup for arbitrary symbols (falls back to defaults when no args).
- `/stats` – Latest block height, total transactions, active wallets, and average gas.

## Data Providers

- **W-Chain Oracle** – primary WCO/WAVE pricing and supply endpoints.
- **W-Chain Explorer (Blockscout)** – network stats, token counters, gas oracle.
- **CoinGecko** – reference prices for external tickers (USDT, USDC, BTC, ETH, etc.).

## Development Tips

- All bot logic lives under `app/`. Avoid editing generated files elsewhere.
- Add new commands by extending `CommandHandlers` and registering them in `app/bot.py`.
- Update `token_catalog` in `app/config.py` to surface additional ecosystem assets.
- Use `python -m app.main` locally; Procfile deployments can target the same command.

## License

MIT – see repository for details.
