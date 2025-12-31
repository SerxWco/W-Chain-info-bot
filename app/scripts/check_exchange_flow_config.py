from __future__ import annotations

import os
from decimal import Decimal

from app.config import Settings
from app.services.exchange_flow_alerts import ExchangeFlowAlertService


def main() -> None:
    # Avoid requiring TELEGRAM_BOT_TOKEN for this diagnostic script.
    settings = Settings(telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", "DUMMY"))

    threshold = Decimal(str(settings.exchange_flow_threshold_wco))
    service = ExchangeFlowAlertService(settings, wchain=None)  # type: ignore[arg-type]

    print("exchange_flow_alerts_enabled:", settings.exchange_flow_alerts_enabled)
    print("exchange_flow_alert_channel_id:", settings.exchange_flow_alert_channel_id or "(unset)")
    print("exchange_flow_poll_seconds:", settings.exchange_flow_poll_seconds)
    print("exchange_flow_poll_page_size:", settings.exchange_flow_poll_page_size)
    print("exchange_flow_threshold_wco(parsed):", str(threshold))
    print("exchange_flow_footer_preview:")
    print(service._render_footer(threshold))


if __name__ == "__main__":
    main()

