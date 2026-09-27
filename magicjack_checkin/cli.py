from __future__ import annotations

import argparse
import logging
import sys

from .backends import get_backend
from .config import BACKENDS, ConfigError, load
from .dtmf import twiml
from .runner import run


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="magicjack-checkin",
        description="Call a reservation line and key in digits on a schedule.",
    )
    p.add_argument("config", help="path to a TOML job file (see config.example.toml)")
    p.add_argument("--backend", choices=BACKENDS, help="override call.backend from the config")
    p.add_argument("--dry-run", action="store_true", help="same as --backend dry-run")
    p.add_argument("--now", action="store_true", help="ignore the schedule window and call immediately")
    p.add_argument("--show-twiml", action="store_true", help="print the generated TwiML and exit")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
    )
    try:
        job = load(args.config, "dry-run" if args.dry_run else args.backend)
        if args.show_twiml:
            print(twiml(job))
            return 0
        backend = get_backend(job)
    except (ConfigError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    try:
        return 0 if run(job, backend, ignore_schedule=args.now) else 1
    except KeyboardInterrupt:
        print("\ncancelled", file=sys.stderr)
        return 130
