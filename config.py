import os

# Telegram Bot Configuration - Read directly from .env file
TELEGRAM_BOT_TOKEN = None
try:
    with open('.env', 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('TELEGRAM_BOT_TOKEN='):
                TELEGRAM_BOT_TOKEN = line.split('=', 1)[1].strip()
                break
except FileNotFoundError:
    pass

# Fallback to environment variable
if not TELEGRAM_BOT_TOKEN:
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# W-Chain API Endpoints
WCO_PRICE_API = "https://oracle.w-chain.com/api/price/wco"
WAVE_PRICE_API = "https://oracle.w-chain.com/api/price/wave"
WCO_SUPPLY_API = "https://oracle.w-chain.com/api/wco/supply-info"
HOLDERS_API = "https://scan.w-chain.com/api/v2/addresses"
OG88_PRICE_API = "https://og88-price-api-production.up.railway.app/price"
OG88_COUNTERS_API = "https://scan.w-chain.com/api/v2/tokens/0xD1841fC048b488d92fdF73624a2128D10A847E88/counters"
WAVE_COUNTERS_API = "https://scan.w-chain.com/api/v2/tokens/0x42AbfB13B4E3d25407fFa9705146b7Cb812404a0/counters"

# Cache settings
CACHE_TTL = 120  # 2 minutes for supply info
PRICE_CACHE_TTL = 60  # 1 minute for price data
