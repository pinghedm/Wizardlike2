import os
import sys

# Set WIZARDLIKE_DEBUG=1 (or true/yes/on) to stream debug logs to stderr.
DEBUG_ENABLED = os.environ.get('WIZARDLIKE_DEBUG', '').lower() in ('1', 'true', 'yes', 'on')


def debug_log(msg: str) -> None:
    """Write a debug line to stderr when WIZARDLIKE_DEBUG is set.

    Flushed immediately so the last line before a crash is the operation that
    crashed."""
    if DEBUG_ENABLED:
        print(f'[DEBUG] {msg}', file=sys.stderr, flush=True)
