import logging

from telegram import Update

from app.bot import build_application
from app.config import Settings


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )


def main() -> None:
    configure_logging()
    settings = Settings.from_env()
    application = build_application(settings)
    logging.info("Starting W-Chain Telegram bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

