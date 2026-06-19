"""JARVIS Telegram Bot — polls Telegram for messages, routes through JARVIS.

Requires `JARVIS_TELEGRAM_BOT_TOKEN` in the environment or `.env` file.

Usage:
    python -m jarvis.notifications.telegram_bot

In mock mode (no token), logs what it would do for testing.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("jarvis.notifications.telegram_bot")

# ── Token resolution ─────────────────────────────────────────────────────────


def _resolve_token() -> Optional[str]:
    """Load the bot token from env vars.

    Checks in order: env → ~/JARVIS/.env → ~/EarlyAi/trading-system/.env
    Returns None if not found (mock mode).
    """
    token = os.environ.get("JARVIS_TELEGRAM_BOT_TOKEN", "")
    if token:
        return token

    # Check .env files
    for dotenv_path in [
        Path.home() / "JARVIS" / ".env",
        Path.home() / "EarlyAi" / "trading-system" / ".env",
    ]:
        if dotenv_path.exists():
            try:
                for line in dotenv_path.read_text().splitlines():
                    line = line.strip()
                    if line.startswith("JARVIS_TELEGRAM_BOT_TOKEN="):
                        token = line.split("=", 1)[1].strip().strip("\"'")
                        if token:
                            return token
            except Exception:
                continue

    return None


# ── Bot Application ──────────────────────────────────────────────────────────


class JarvisTelegramBot:
    """Telegram bot that relays messages to JARVIS and responds.

    Uses python-telegram-bot v22.x with Application for polling.
    Falls back to mock mode if no token is provided.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        api_url: str = "http://localhost:8000",
    ) -> None:
        self.token = token if token is not None else _resolve_token()
        self.api_url = api_url.rstrip("/")
        self._application: Any = None
        self._running = False

        if not self.token:
            logger.info(
                "No JARVIS_TELEGRAM_BOT_TOKEN set — running in "
                "console-only mock mode. Set the env var to go live."
            )

    @property
    def is_mock(self) -> bool:
        """True when running without a real bot token."""
        return not self.token

    def _build_application(self) -> Any:
        """Create and configure the python-telegram-bot Application."""
        from telegram.ext import (
            Application,
            CommandHandler,
            MessageHandler,
            filters,
        )

        app = Application.builder().token(self.token).build()

        # Register handlers
        from jarvis.notifications.telegram_handler import TelegramHandler

        handler = TelegramHandler(api_url=self.api_url)

        # Wrap message processing
        async def handle_message(update: Any, context: Any) -> None:
            # Support both regular and edited messages
            msg = update.message or update.edited_message
            if not msg or not msg.text:
                return

            chat_id = str(msg.chat_id)
            text = msg.text
            username = msg.from_user.username if msg.from_user else None

            logger.info("TG from %s: %s", chat_id, text[:80])

            # Process through JARVIS
            try:
                response = handler.handle(chat_id, text, username)
            except Exception as exc:
                logger.error("Handler error: %s", exc, exc_info=True)
                response = f"⚠️ Internal error: {exc}"

            # Send response
            if response:
                await msg.reply_text(
                    response,
                    parse_mode="Markdown",
                )
                logger.debug("TG reply to %s: %s", chat_id, response[:60])

        # Register as handler for ALL text messages (commands + conversation)
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        app.add_handler(CommandHandler("start", handle_message))
        app.add_handler(CommandHandler("help", handle_message))
        app.add_handler(CommandHandler("status", handle_message))
        app.add_handler(CommandHandler("drift", handle_message))
        app.add_handler(CommandHandler("approve", handle_message))
        app.add_handler(CommandHandler("deny", handle_message))
        app.add_handler(CommandHandler("memory", handle_message))
        app.add_handler(CommandHandler("forget", handle_message))

        return app

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def run(self) -> None:
        """Start the bot. Blocks until interrupted."""
        if self.is_mock:
            self._run_mock()
            return

        logger.info("Starting JARVIS Telegram bot (polling)...")
        self._application = self._build_application()
        self._running = True

        try:
            self._application.run_polling(
                allowed_updates=["messages", "edited_message"],
                poll_interval=1.0,
                timeout=30,
                drop_pending_updates=True,
            )
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        except Exception as exc:
            logger.error("Bot error: %s", exc, exc_info=True)
        finally:
            self._running = False

    def stop(self) -> None:
        """Stop the bot gracefully."""
        self._running = False
        if self._application:
            logger.info("Stopping bot...")
            try:
                asyncio.run(self._application.stop())
            except Exception:
                pass

    def _run_mock(self) -> None:
        """Mock mode — just log what would happen."""
        from jarvis.notifications.telegram_handler import TelegramHandler

        handler = TelegramHandler(api_url=self.api_url)
        logger.info("JARVIS Telegram bot running in MOCK mode")
        logger.info("Send a message to test the handler:")
        print("\n🐚 JARVIS Telegram Bot — MOCK MODE 🐚")
        print("Type messages to test, or Ctrl+C to quit.\n")

        while True:
            try:
                line = input("You: ").strip()
                if not line:
                    continue

                response = handler.handle("mock-chat", line)
                print(f"\nJARVIS:\n{response}\n")

            except KeyboardInterrupt:
                print("\nMock session ended.")
                break
            except EOFError:
                break


# ── CLI entry point ──────────────────────────────────────────────────────────


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="JARVIS Telegram Bot")
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="JARVIS API URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Force mock mode even if token is available",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    if args.mock:
        token = None
    else:
        token = _resolve_token()

    if not token:
        logger.info("No Telegram token found — starting in mock mode")
        print("ℹ️  No JARVIS_TELEGRAM_BOT_TOKEN set.")
        print("   Set it in ~/JARVIS/.env to connect to Telegram.")
        print("   Starting in mock mode for testing.\n")

    bot = JarvisTelegramBot(token=token, api_url=args.api_url)
    try:
        bot.run()
    except KeyboardInterrupt:
        bot.stop()
        print("\nBot stopped.")


if __name__ == "__main__":
    main()