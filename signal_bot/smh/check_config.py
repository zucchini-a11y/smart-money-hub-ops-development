"""Configuration validation without printing secret values."""
import argparse
import asyncio
from .config import Config
from .startup_validation import format_report, validate_startup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--safe-startup",
        action="store_true",
        help="Run read-only dependency, database, and Telegram permission checks; never polls or sends.",
    )
    args = parser.parse_args()
    try:
        c = Config.load()
        if args.safe_startup:
            result = asyncio.run(validate_startup(c))
            print(format_report(result))
            raise SystemExit(0 if result["ok"] else 1)
        print("Configuration: ready" if c.ready else
              "Configuration: discovery only. Set ADMIN_TELEGRAM_ID and both channel IDs to enable publishing.")
    except ValueError as e:
        print(str(e))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
