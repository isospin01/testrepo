"""
timer.py — 25-minute Pomodoro work-block timer with Grok break reminder.

When the countdown ends, opens Chrome with Grok Voice Mode as the Victorian maid
to announce the break. No escalation — a single gentle reminder. The session
closes once the master speaks the session key.

Usage:
    python timer.py                 # Start 25-minute work block
    python timer.py --dev           # Dev mode: Ctrl+C works, full logging
    python timer.py --minutes 1     # Custom duration (useful for testing)
"""
import argparse
import signal
import sys
import threading
import time

# ---------------------------------------------------------------------------
# Parse args early so DEV_MODE is set before config is imported
# ---------------------------------------------------------------------------
_parser = argparse.ArgumentParser(description="GrokAlarm Pomodoro Timer")
_parser.add_argument("--dev", action="store_true", help="Developer mode (Ctrl+C enabled)")
_parser.add_argument("--minutes", type=float, default=None, help="Override timer duration in minutes")
_args = _parser.parse_args()

import config
if _args.dev:
    config.DEV_MODE = True

from config import (
    DEV_MODE,
    TIMER_DURATION_S,
    BREAK_SCENARIO_PROMPT,
    KEYWORD_FINAL_RESPONSE_MAX_WAIT_S,
    KEYWORD_FINAL_SILENCE_S,
)
from session_key import generate_session_key, write_key_to_desktop, delete_key_file
from browser_control import GrokBrowser


# ---------------------------------------------------------------------------
# Global shutdown event
# ---------------------------------------------------------------------------
shutdown_event = threading.Event()


def _emergency_shutdown(signum, frame):
    print("\n[timer] DEV_MODE: Ctrl+C caught — initiating shutdown.")
    shutdown_event.set()


def _setup_signal_handling():
    if DEV_MODE:
        signal.signal(signal.SIGINT, _emergency_shutdown)
        print("[timer] DEV_MODE: Ctrl+C handler active.")
    else:
        signal.signal(signal.SIGINT, signal.SIG_IGN)


def _countdown(duration_s: float) -> None:
    """Print a live countdown, blocking until it expires or shutdown is set."""
    end = time.monotonic() + duration_s
    while not shutdown_event.is_set():
        remaining = end - time.monotonic()
        if remaining <= 0:
            break
        mins, secs = divmod(int(remaining), 60)
        print(f"\r[timer] Work block: {mins:02d}:{secs:02d} remaining   ", end="", flush=True)
        time.sleep(1)
    print()  # newline after countdown


def main():
    duration_s = (_args.minutes * 60) if _args.minutes is not None else TIMER_DURATION_S
    mins_label = duration_s / 60

    print("=" * 60)
    print("  GrokAlarm — Pomodoro Timer")
    print(f"  Duration: {mins_label:.0f} minutes")
    print(f"  Mode: {'DEVELOPER' if DEV_MODE else 'PRODUCTION'}")
    print("=" * 60)

    _setup_signal_handling()

    print(f"[timer] Work block started. Focus for {mins_label:.0f} minutes.")
    _countdown(duration_s)

    if shutdown_event.is_set():
        print("[timer] Timer cancelled.")
        sys.exit(0)

    print("[timer] Work block complete! Launching break reminder...")

    # Generate session key — master must speak it to dismiss the reminder
    session_key = generate_session_key()
    write_key_to_desktop(session_key)
    print(f"[timer] Session key: {session_key}")

    browser = GrokBrowser(session_key=session_key, scenario_prompt=BREAK_SCENARIO_PROMPT)
    try:
        browser.start()
    except Exception as e:
        print(f"[timer] ABORT: Browser error: {e}")
        if DEV_MODE:
            import traceback
            traceback.print_exc()
        delete_key_file()
        sys.exit(1)

    print("\n[timer] Break reminder active.")
    print("[timer] Speak/type the session key in Grok to dismiss.")

    while not shutdown_event.is_set():
        matched_text = browser.consume_session_key_match_text()
        if matched_text:
            print(f"[timer] Session key matched: '{matched_text}'")
            print("[timer] Waiting for Grok final response...")
            if browser.wait_for_final_response_complete(
                timeout_s=KEYWORD_FINAL_RESPONSE_MAX_WAIT_S,
                idle_s=KEYWORD_FINAL_SILENCE_S,
            ):
                print("[timer] Final response completed.")
            else:
                print("[timer] Final-response timeout; shutting down.")
            shutdown_event.set()
            break
        time.sleep(0.2)

    print("\n[timer] Cleaning up...")
    browser.stop()
    delete_key_file()
    print("[timer] Break reminder dismissed. Enjoy your break!")
    sys.exit(0)


if __name__ == "__main__":
    main()
