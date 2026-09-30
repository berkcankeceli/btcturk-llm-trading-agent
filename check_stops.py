"""Minute-level stop-loss / take-profit watcher. Run it from cron every minute.

main.py checks exits only once per tick (e.g. every 10 minutes, and each tick also spends
time on screening + the LLM call). If price gaps through the stop between two ticks, the exit
fills far below the planned stop. This script closes that gap: it only compares the latest
price with each open position's stop_loss_price / take_profit_price from state.json and, when
a level is hit, exits through the bot's OWN exit path (main.handle_position), so the trade
log, lesson, notification mail and state.json update are identical to a normal exit.

No LLM call, no screening, no new entries, no change to stop/target levels.

Locking: main.py (via `flock` in its cron line) and this script take the SAME exclusive lock,
so they never write state.json at the same time and can never sell one position twice.

Usage:
  python check_stops.py --dry-run   # log what would be sold, place no orders, write nothing
  python check_stops.py             # exit for real when a level is hit (honours DRY_RUN in .env)
"""
import os
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone

import main as bot
import storage
from btcturk_client import BtcTurkClient

# Must be the same file main.py's cron line locks (see README, "Minute-level stop watch").
LOCK_FILE = os.getenv("LOCK_FILE", os.path.join(tempfile.gettempdir(), "trade-agent.lock"))
LOCK_WAIT_SEC = 30


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"{ts} [STOP-CHECK] {msg}", flush=True)


def _try_lock(fd) -> bool:
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(fd) -> None:
    if os.name == "nt":
        import msvcrt
        fd.seek(0)
        msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)


def acquire_lock():
    """Wait up to LOCK_WAIT_SEC for the shared lock; None if the main tick keeps holding it."""
    fd = open(LOCK_FILE, "a+")
    deadline = time.monotonic() + LOCK_WAIT_SEC
    while not _try_lock(fd):
        if time.monotonic() >= deadline:
            fd.close()
            return None
        time.sleep(1)
    return fd


def run(dry_run: bool) -> None:
    mode = "DRY-RUN" if dry_run else ("LIVE" if not bot.DRY_RUN else "BOT-DRY_RUN")
    lock_fd = acquire_lock()
    if lock_fd is None:
        log(f"({mode}) lock not acquired within {LOCK_WAIT_SEC}s (main tick running), skipping this minute.")
        return

    try:
        positions = storage.load_positions()
        if not positions:
            log(f"({mode}) no open positions.")
            return

        client = BtcTurkClient(os.getenv("BTCTURK_API_KEY", ""), os.getenv("BTCTURK_API_SECRET", ""))
        try:
            ticker_data = client.get_ticker_all()
        except Exception as exc:  # network error / rate limit: never crash, retry next minute
            log(f"({mode}) ERROR: ticker unavailable, skipping this minute: {exc!r}")
            return

        remaining, closed_any = [], False
        for p in positions:
            ticker = next((t for t in ticker_data if t["pairNormalized"] == p["symbol"]), None)
            if ticker is None:
                log(f"({mode}) WARNING: no ticker for {p['symbol']}, skipped.")
                remaining.append(p)
                continue

            last = ticker["last"]
            stop, target = p["stop_loss_price"], p["take_profit_price"]
            hit = "STOP" if last <= stop else ("TARGET" if last >= target else None)
            log(f"({mode}) {p['symbol']} last={last} stop={stop} target={target} "
                f"entry={p['entry_price']} -> {hit + ' HIT' if hit else 'OK'}")

            if not hit:
                remaining.append(p)
                continue
            if dry_run:
                log(f"(DRY-RUN) would sell {p['symbol']} ({hit}) - no order placed.")
                remaining.append(p)
                continue

            try:
                closed = bot.handle_position(client, p, ticker_data)  # the bot's own exit path
            except Exception as exc:
                log(f"({mode}) ERROR while exiting {p['symbol']}: {exc!r}\n{traceback.format_exc()}")
                closed = False
            if closed:
                closed_any = True
                log(f"({mode}) {p['symbol']} CLOSED ({hit}).")
            else:
                remaining.append(p)

        if closed_any:
            storage.save_positions(remaining)
            log(f"({mode}) state.json updated, remaining: {[p['symbol'] for p in remaining]}")
    finally:
        _unlock(lock_fd)
        lock_fd.close()


if __name__ == "__main__":
    try:
        run(dry_run="--dry-run" in sys.argv)
    except Exception as exc:
        log(f"UNEXPECTED ERROR: {exc!r}\n{traceback.format_exc()}")
