import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import bot
from config import BURN_WALLET_ADDRESS, OG88_TOKEN_ADDRESS
from wchain_api import WChainAPI


class BroadcastBurnAlertTests(unittest.IsolatedAsyncioTestCase):
    async def test_broadcast_burn_alert_sends_expected_payload(self):
        dummy_bot = SimpleNamespace(
            send_message=AsyncMock(),
            send_animation=AsyncMock(),
        )
        context = SimpleNamespace(bot=dummy_bot)
        transaction = {
            "total": {
                "value": str(100 * 10**18),
                "decimals": 18,
            },
            "token": {
                "decimals": 18,
            },
            "timestamp": "2024-01-01T00:00:00Z",
            "transaction_hash": "0xnewhash",
            "from": {"hash": "0xfeedface"},
            "block_number": 12345,
        }
        subscribers = {555}
        expected_amount = bot.format_token_amount(
            bot.normalize_token_amount(transaction["total"]["value"], transaction["total"]["decimals"])
        )
        with patch.object(bot.wchain_api, "get_og88_price", return_value={"price_usd": "0.01"}):
            with patch("bot.BURN_ALERT_ANIMATION_URL", "https://example.com/alert.gif"):
                await bot.broadcast_burn_alert(transaction, subscribers, context)

        dummy_bot.send_message.assert_awaited_once()
        send_kwargs = dummy_bot.send_message.await_args.kwargs
        assert send_kwargs["chat_id"] == 555
        assert "🔥 *OG88 Burn Alert*" in send_kwargs["text"]
        assert f"• Amount: {expected_amount} OG88" in send_kwargs["text"]
        assert "• USD Value: $1.00" in send_kwargs["text"]

        dummy_bot.send_animation.assert_awaited_once()
        animation_kwargs = dummy_bot.send_animation.await_args.kwargs
        assert animation_kwargs["animation"] == "https://example.com/alert.gif"
        assert animation_kwargs["caption"] == f"🔥 {expected_amount} OG88 burned!"


class MonitorBurnWalletTests(unittest.IsolatedAsyncioTestCase):
    async def test_monitor_burn_wallet_triggers_alert_for_new_transactions(self):
        bot_data = {
            "burn_watch_subscribers": {999},
            "burn_watch_state": {"last_hash": "0xoldhash"},
        }
        context = SimpleNamespace(application=SimpleNamespace(bot_data=bot_data))
        tx_new = {
            "transaction_hash": "0xnewhash",
            "timestamp": "2024-01-01T00:00:00Z",
            "total": {"value": "1", "decimals": 18},
        }
        tx_old = {"transaction_hash": "0xoldhash"}
        with patch.object(bot.wchain_api, "get_recent_og88_burns", return_value=[tx_new, tx_old]):
            with patch("bot.broadcast_burn_alert", new_callable=AsyncMock) as mock_alert:
                await bot.monitor_burn_wallet(context)

        mock_alert.assert_awaited_once_with(tx_new, {999}, context)
        assert bot_data["burn_watch_state"]["last_hash"] == "0xnewhash"


class RecentBurnsFilterTests(unittest.TestCase):
    def test_get_recent_og88_burns_filters_to_target_token(self):
        api = WChainAPI()
        transfers = [
            {"token": {"address": OG88_TOKEN_ADDRESS.upper()}, "transaction_hash": "0x1"},
            {"token": {"address": "0xother"}, "transaction_hash": "0x2"},
            {"token": {}, "transaction_hash": "0x3"},
        ]
        with patch.object(WChainAPI, "get_address_token_transfers", return_value=transfers) as mock_transfers:
            result = api.get_recent_og88_burns(limit=3)

        mock_transfers.assert_called_once_with(BURN_WALLET_ADDRESS, limit=3)
        assert result == [transfers[0]]
