import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from wchain_api import WChainAPI
from config import TELEGRAM_BOT_TOKEN

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize W-Chain API
wchain_api = WChainAPI()

def format_number(num: float, decimals: int = 2) -> str:
    """Format large numbers with appropriate suffixes"""
    if num >= 1e9:
        return f"{num/1e9:.{decimals}f}B"
    elif num >= 1e6:
        return f"{num/1e6:.{decimals}f}M"
    elif num >= 1e3:
        return f"{num/1e3:.{decimals}f}K"
    else:
        return f"{num:.{decimals}f}"

def format_price(price: float) -> str:
    """Format price with appropriate decimal places"""
    if price >= 1:
        return f"${price:,.4f}"
    elif price >= 0.01:
        return f"${price:,.6f}"
    else:
        return f"${price:,.8f}"

def format_wco_price(price: float) -> str:
    """Format WCO price without $ symbol"""
    if price >= 1:
        return f"{price:,.4f}"
    elif price >= 0.01:
        return f"{price:,.6f}"
    else:
        return f"{price:,.8f}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    welcome_message = """
🎯 **WChain Bot**

Welcome! I provide real-time information about W-Chain and its tokens.

**Available Commands:**
/start - See this welcome message
/wco - Complete WCO token information (price, supply, market cap, burn stats)
/wave - WAVE token price and market information
        /OG88 - 🐼 OG88 token price and market information
/buy - Buy WCO, WAVE & OG88 tokens on exchanges

**Quick Start:**
Use /wco for comprehensive W-Chain data! 📊
"""
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    help_message = """
📖 **WChain Bot Help**

**Available Commands:**
/start - See the welcome message
/wco - Complete WCO token information (price, supply, market cap, burn stats)
/wave - WAVE token price and market information
        /OG88 - 🐼 OG88 token price and market information
/buy - Buy WCO, WAVE & OG88 tokens on exchanges

**Data Sources:**
• Price data from W-Chain Oracle API
• OG88 price data from OG88 Price API
• Supply data from W-Chain Supply API
• Real-time updates with 1-2 minute caching

**Features:**
• Real-time price tracking
• Supply distribution analysis
• Market cap calculations
• Burned token tracking
• Multi-token support (WCO, WAVE, OG88)

**Quick Start:**
Use /wco for comprehensive W-Chain data! 📊
    """
    await update.message.reply_text(help_message, parse_mode='Markdown')

async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get WCO and WAVE token prices."""
    await update.message.reply_text("🔄 Fetching price data...")
    
    wco_price = wchain_api.get_wco_price()
    wave_price = wchain_api.get_wave_price()
    
    if not wco_price and not wave_price:
        await update.message.reply_text("❌ Unable to fetch price data. Please try again later.")
        return
    
    message = "💰 **Token Prices**\n\n"
    
    if wco_price:
        price = wco_price.get('price', 0)
        message += f"**WCO:** {format_price(price)}\n"
        # Note: 24h change would need historical data, not available in current API
    
    if wave_price:
        price = wave_price.get('price', 0)
        message += f"**WAVE:** {format_price(price)}\n"
    
    message += f"\n📊 *Data from W-Chain Oracle API*"
    await update.message.reply_text(message, parse_mode='Markdown')

async def supply_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get WCO supply information."""
    await update.message.reply_text("🔄 Fetching supply data...")
    
    supply_data = wchain_api.get_wco_supply_info()
    
    if not supply_data:
        await update.message.reply_text("❌ Unable to fetch supply data. Please try again later.")
        return
    
    summary = supply_data.get('summary', {})
    
    message = "📊 **WCO Supply Information**\n\n"
    
    # Get supply data
    initial_supply = float(summary.get('initial_supply_wco', 0))
    circulating_supply = float(summary.get('circulating_supply_wco', 0))
    locked_supply = float(summary.get('locked_supply_wco', 0))
    burned_supply = float(summary.get('burned_supply_wco', 0))
    
    # Calculate total supply (initial - burnt)
    total_supply = initial_supply - burned_supply
    
    message += f"**Total Supply:** {total_supply:,.0f} WCO\n"
    message += f"**Circulating Supply:** {circulating_supply:,.0f} WCO\n"
    message += f"**Locked Supply:** {format_number(locked_supply, 2)} WCO\n"
    message += f"**WCO Burnt:** {format_number(burned_supply, 2)} WCO\n"
    
    # Calculate percentages based on total supply
    if total_supply > 0:
        circulating_pct = (circulating_supply / total_supply) * 100
        locked_pct = (locked_supply / total_supply) * 100
        burned_pct = (burned_supply / total_supply) * 100
        
        message += f"\n**Distribution:**\n"
        message += f"• Circulating: {circulating_pct:.1f}%\n"
        message += f"• Locked: {locked_pct:.1f}%\n"
        message += f"• Burned: {burned_pct:.1f}%\n"
    
    message += f"\n📊 *Data from W-Chain Supply API*"
    await update.message.reply_text(message, parse_mode='Markdown')


async def wco_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show WCO token information."""
    await update.message.reply_text("🔄 Fetching WCO data...")
    
    wco_price = wchain_api.get_wco_price()
    supply_data = wchain_api.get_wco_supply_info()
    market_cap = wchain_api.get_market_cap()
    holders_count = wchain_api.get_holders_count()
    
    if not wco_price and not supply_data:
        await update.message.reply_text("❌ Unable to fetch WCO data. Please try again later.")
        return
    
    message = "🪙 **WCO Token Information**\n\n"
    
    # Price and Market Cap
    if wco_price:
        price = wco_price.get('price', 0)
        message += f"💰 **Price:** {format_price(price)}\n"
    
    if market_cap:
        message += f"📊 **Market Cap:** ${format_number(market_cap, 2)}\n"
    
    message += "\n"
    
    # Supply Information
    if supply_data:
        summary = supply_data.get('summary', {})
        initial_supply = float(summary.get('initial_supply_wco', 0))
        circulating_supply = float(summary.get('circulating_supply_wco', 0))
        locked_supply = float(summary.get('locked_supply_wco', 0))
        burned_supply = float(summary.get('burned_supply_wco', 0))
        
        total_supply = initial_supply - burned_supply
        
        message += "📈 **Supply Stats:**\n"
        message += f"🔢 Total: {total_supply:,.0f} WCO\n"
        message += f"💸 Circulating: {circulating_supply:,.0f} WCO\n"
        message += f"🔒 Locked: {format_number(locked_supply, 2)} WCO\n"
        message += f"🔥 Burnt: {format_number(burned_supply, 2)} WCO\n"
        
        # Calculate percentages
        if total_supply > 0:
            circulating_pct = (circulating_supply / total_supply) * 100
            locked_pct = (locked_supply / total_supply) * 100
            burned_pct = (burned_supply / total_supply) * 100
            
            message += f"\n📊 **Distribution:**\n"
            message += f"💸 Circulating: {circulating_pct:.1f}%\n"
            message += f"🔒 Locked: {locked_pct:.1f}%\n"
            message += f"🔥 Burnt: {burned_pct:.1f}%\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show buy links for WCO, WAVE, and OG88 tokens."""
    message = "💳 **Buy WCO, WAVE & OG88 Tokens**\n\n"
    message += "🪙 **WCO (Native Token):**\n"
    message += f"🔗 [Bitmart](https://www.bitmart.com/es-ES/invite/Pdc9we)\n"
    message += f"🔗 [Mexc](https://www.mexc.com/invite/register?inviteCode=1LqAi&source=invite&utm_source=usershare&utm_medium=usershare&utm_biz=affiliate&utm_campaign=invite)\n"
    message += f"🔗 [Bitrue](https://www.bitrue.com/referral/landing?cn=600000&inviteCode=LHLAAG)\n"
    message += f"🔗 [W-Swap DEX](https://app.w-swap.com/#/)\n\n"
    message += "🌊 **WAVE (Reward Token):**\n"
    message += f"🔗 [W-Swap DEX](https://app.w-swap.com/#/)\n\n"
    message += "🎯 **OG88 (Community Meme):**\n"
    message += f"🔗 [W-Swap DEX](https://app.w-swap.com/#/)\n\n"
    message += "💡 *Click any link above to start trading!*"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def wave_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show WAVE token information."""
    await update.message.reply_text("🔄 Fetching WAVE data...")
    
    wave_price = wchain_api.get_wave_price()
    wco_price = wchain_api.get_wco_price()
    wave_counters = wchain_api.get_wave_counters()
    
    if not wave_price:
        await update.message.reply_text("❌ Unable to fetch WAVE data. Please try again later.")
        return
    
    message = "🌊 **WAVE Token Information**\n\n"
    
    # Price Information
    if wave_price:
        price = wave_price.get('price', 0)
        message += f"💰 **Price:** {format_price(price)}\n"
    
    # WCO Price for reference
    if wco_price:
        wco_price_val = wco_price.get('price', 0)
        message += f"🪙 **WCO Price:** {format_wco_price(wco_price_val)} WCO\n"
    
    # Add holders and transfers count
    if wave_counters:
        holders_count = int(wave_counters.get('token_holders_count', 0))
        transfers_count = int(wave_counters.get('transfers_count', 0))
        message += f"👥 **Holders:** {holders_count:,}\n"
        message += f"🔄 **Transfers:** {transfers_count:,}\n"
    
    message += "\n"
    message += "📋 **Token Info:**\n"
    message += "WAVE is the native reward and incentive token at the heart of W Swap, W Chain's decentralized exchange. Designed to catalyze liquidity, user participation, and sustainable ecosystem growth, WAVE empowers users through liquidity mining, staking rewards, and future governance capabilities.\n"
    message += "\n💱 Price calculated via WAVE/WCO trading pair"
    
    message += f"\n📊 *Data from W-Chain Oracle API & W-Chain Explorer*"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def og88_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show OG88 token information."""
    await update.message.reply_text("🔄 Fetching OG88 data...")
    
    og88_data = wchain_api.get_og88_price()
    og88_counters = wchain_api.get_og88_counters()
    
    if not og88_data:
        await update.message.reply_text("❌ Unable to fetch OG88 data. Please try again later.")
        return
    
    message = "🐼 **OG88 Token Information**\n\n"
    
    # Price Information
    price_usd = float(og88_data.get('price_usd', 0))
    price_wco = float(og88_data.get('price_wco', 0))
    market_cap = float(og88_data.get('market_cap', 0))
    
    message += f"💰 **Price USD:** {format_price(price_usd)}\n"
    message += f"🪙 **Price WCO:** {format_wco_price(price_wco)} WCO\n"
    message += f"📊 **Market Cap:** ${format_number(market_cap, 2)}\n"
    
    # Add holders and transfers count
    if og88_counters:
        holders_count = int(og88_counters.get('token_holders_count', 0))
        transfers_count = int(og88_counters.get('transfers_count', 0))
        message += f"👥 **Holders:** {holders_count:,}\n"
        message += f"🔄 **Transfers:** {transfers_count:,}\n"
    
    # Add last updated timestamp
    last_updated = og88_data.get('last_updated', 'N/A')
    if last_updated != 'N/A':
        message += f"🕒 **Last Updated:** {last_updated}\n"
    
    message += "\n📋 **Token Info:**\n"
    message += "OG 88 – The Original Community Meme on W Chain:\n"
    
    message += f"\n🌐 **Website:** [OG88.meme](https://og88.meme)\n"
    message += f"🔗 **Contract:** [0xD1841fC048b488d92fdF73624a2128D10A847E88](https://scan.w-chain.com/token/0xD1841fC048b488d92fdF73624a2128D10A847E88)\n"
    
    message += f"\n📊 *Data from OG88 Price API & W-Chain Explorer*"
    
    await update.message.reply_text(message, parse_mode='Markdown')

def main():
    """Start the bot."""
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not found. Please set it in your environment variables.")
        return
    
    # Create the Application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("wco", wco_command))
    application.add_handler(CommandHandler("wave", wave_command))
    application.add_handler(CommandHandler("OG88", og88_command))
    application.add_handler(CommandHandler("buy", buy_command))
    
    # Keep old commands for backward compatibility
    application.add_handler(CommandHandler("price", price_command))
    application.add_handler(CommandHandler("supply", supply_command))
    
    # Start the bot
    print("🤖 W-Chain Bot is starting...")
    print("Press Ctrl+C to stop the bot")
    
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"❌ Error running bot: {e}")

if __name__ == '__main__':
    main()
