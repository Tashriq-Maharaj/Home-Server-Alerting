#!/usr/bin/env python3
"""
Server Alerting - Entry Point
Lightweight, real-time Ubuntu server monitoring and alerting system.
"""

import argparse
import sys

from src.config import load_config
from src.monitor import ServerMonitor, setup_logging


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reliable, lightweight real-time server monitoring and alerting for Ubuntu Server."
    )
    parser.add_argument(
        "--config",
        "-c",
        type=str,
        default=None,
        help="Path to JSON configuration file (defaults to config/config.default.json).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Collect a single metrics snapshot, print diagnostics, and exit.",
    )
    parser.add_argument(
        "--test-notify",
        action="store_true",
        help="Send a test notification across enabled channels (Telegram, Email) and exit.",
    )
    parser.add_argument(
        "--interval",
        "-i",
        type=int,
        default=None,
        help="Override the collection interval in seconds (default: 10s).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()

    # Load configuration (.env + JSON + defaults)
    config = load_config(args.config)

    if args.interval:
        config.monitoring.interval_seconds = max(1, args.interval)

    # Initialize logging
    setup_logging(config)

    monitor = ServerMonitor(config)

    # Test notification mode
    if args.test_notify:
        print(f"Sending test notification for host '{config.server.hostname}'...")
        success = monitor.dispatcher.send_test_notification()
        if success:
            print("Successfully dispatched test notification!")
            return 0
        else:
            print("Failed to dispatch test notification. Check credentials in .env.")
            return 1

    # Single snapshot run mode
    if args.once:
        monitor.run_once()
        return 0

    # Continuous service loop
    try:
        monitor.run()
    except KeyboardInterrupt:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
