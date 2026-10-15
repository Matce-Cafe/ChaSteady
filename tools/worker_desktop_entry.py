"""Entrypoint used to freeze the local worker for the desktop supervisor.

The supervisor owns the console-mode Worker.exe process and its inherited
stdin/stdout/stderr pipes. This wrapper deliberately does not infer bundle or
data roots; the desktop CLI requires both roots to be passed explicitly.
"""
import os
from pathlib import Path
import sys


if not getattr(sys, "frozen", False):
    # Keep direct development invocation useful without depending on cwd or
    # site-packages. PyInstaller resolves this import through the spec's pathex.
    _PROJECT_ROOT = Path(__file__).resolve().parents[1]
    _WORKER_SOURCE = _PROJECT_ROOT / "worker"
    sys.path.insert(0, str(_WORKER_SOURCE))

from cha_stabilizer.cli import main  # noqa: E402


if __name__ == "__main__":
    # Test-only opt-in: Python thread stacks go to the owned stderr pipe, never
    # the private stdout protocol. This is disabled for normal application use.
    diagnostic_stacks = os.environ.get("CHASTEADY_TEST_STACKS") == "1"
    if diagnostic_stacks:
        import faulthandler
        faulthandler.dump_traceback_later(5, repeat=True, file=sys.stderr)
    try:
        raise SystemExit(main())
    finally:
        if diagnostic_stacks:
            faulthandler.cancel_dump_traceback_later()
