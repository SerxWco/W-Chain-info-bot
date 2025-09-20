# W-Chain Telegram Bot

A comprehensive Telegram bot that provides real-time information about W-Chain and its tokens (WCO and WAVE). The bot fetches data from the official W-Chain Oracle and Supply APIs to display price information, supply distribution, market cap, and more.

## Features

### 📊 Token Information
- **WCO Token Price**: Real-time USD price from W-Chain Oracle API
- **WAVE Token Price**: Calculated price based on WCO/WAVE trading pair
- **Market Cap**: Calculated using circulating supply and current price

### 📈 Supply Information
- **Total Supply**: Initial WCO token supply
- **Circulating Supply**: Tokens available for trading
- **Locked Supply**: Tokens locked in staking and vesting contracts
- **WCO Burnt**: Tokens sent to burn address
- **Supply Distribution**: Percentage breakdown of token allocation

### 🤖 Bot Commands
- `/start` - Welcome message and bot introduction
- `/help` - Show available commands and help information
- `/price` - Get current WCO and WAVE token prices
- `/supply` - Display WCO supply information and distribution
- `/info` - Complete W-Chain information (prices, supply, market cap)

## Installation

### Prerequisites
- Python 3.7 or higher
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))

### Setup

1. **Clone or download the project files**

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Create environment file**
   Create a `.env` file in the project directory:
   ```
   TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
   ```

4. **Get Telegram Bot Token**
   - Message [@BotFather](https://t.me/botfather) on Telegram
   - Use `/newbot` command to create a new bot
   - Copy the token and add it to your `.env` file

5. **Run the bot**
   ```bash
   python bot.py
   ```

## API Integration

The bot integrates with two main W-Chain APIs:

### Price API
- **WCO Price**: `https://oracle.w-chain.com/api/price/wco`
- **WAVE Price**: `https://oracle.w-chain.com/api/price/wave`
- **Cache**: 1 minute TTL

### Supply API
- **Supply Info**: `https://oracle.w-chain.com/api/wco/supply-info`
- **Cache**: 2 minutes TTL

## Data Sources

### Price Data
- WCO price comes directly from the W-Chain price feed database
- WAVE price is calculated using WCO price and WAVE/WCO trading pair data
- Formula: `WAVE_USD_Price = WAVE_WCO_Rate × WCO_USD_Price`

### Supply Data
- Real-time blockchain data via W-Chain RPC
- Uses Multicall3 for efficient batch balance queries
- Circulating supply calculated as: `Initial Supply - Locked Supply - Burned Supply`

## Features in Detail

### Caching System
- **Price Data**: 1-minute cache to reduce API load
- **Supply Data**: 2-minute cache for optimal performance
- **Automatic Refresh**: Data updates automatically when cache expires

### Error Handling
- Graceful handling of API failures
- User-friendly error messages
- Fallback responses when data is unavailable

### Number Formatting
- Large numbers formatted with K/M/B suffixes
- Price formatting with appropriate decimal places
- Percentage calculations for supply distribution

## Usage Examples

### Get Token Prices
```
/price
```
Returns:
```
💰 Token Prices

WCO: $0.0234
WAVE: $1.4567

📊 Data from W-Chain Oracle API
```

### Get Supply Information
```
/supply
```
Returns:
```
📊 WCO Supply Information

Initial Supply: 1,000,000,000 WCO
Circulating Supply: 744.99M WCO
Locked Supply: 250.00M WCO
WCO Burnt: 5.00M WCO

Distribution:
• Circulating: 74.5%
• Locked: 25.0%
• Burned: 0.5%

📊 Data from W-Chain Supply API
```

### Get Complete Information
```
/info
```
Returns comprehensive data including prices, supply, market cap, and distribution percentages.

## Configuration

### Environment Variables
- `TELEGRAM_BOT_TOKEN`: Your Telegram bot token (required)

### API Endpoints
All API endpoints are configured in `config.py` and can be modified if needed.

### Cache Settings
Cache TTL values can be adjusted in `config.py`:
- `PRICE_CACHE_TTL`: Price data cache duration (default: 60 seconds)
- `CACHE_TTL`: Supply data cache duration (default: 120 seconds)

## File Structure

```
wchain-telegram-bot/
├── bot.py              # Main bot application
├── wchain_api.py       # W-Chain API integration
├── config.py           # Configuration settings
├── requirements.txt    # Python dependencies
├── README.md          # This file
└── .env               # Environment variables (create this)
```

## Dependencies

- `python-telegram-bot==20.7` - Telegram Bot API wrapper
- `requests==2.31.0` - HTTP requests for API calls
- `python-dotenv==1.0.0` - Environment variable management

## Troubleshooting

### Common Issues

1. **Bot not responding**
   - Check if `TELEGRAM_BOT_TOKEN` is set correctly
   - Verify the token is valid and not expired
   - Check internet connection

2. **API data not loading**
   - W-Chain APIs might be temporarily unavailable
   - Check if the bot has internet access
   - Try again after a few minutes

3. **Import errors**
   - Ensure all dependencies are installed: `pip install -r requirements.txt`
   - Check Python version (3.7+ required)

### Getting Help

- Check the console output for error messages
- Verify your `.env` file has the correct bot token
- Ensure all required files are present in the project directory

## API Documentation

For detailed information about the W-Chain APIs used by this bot, refer to the official documentation:

- **Price API**: W-Chain Oracle Price API documentation
- **Supply API**: W-Chain Supply Information API documentation

## License

This project is open source and available under the MIT License.

## Contributing

Contributions are welcome! Please feel free to submit issues, feature requests, or pull requests.

---

**Note**: This bot is for informational purposes only. Always verify data independently for financial decisions.

