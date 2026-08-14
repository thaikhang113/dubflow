"""Mandatory first-run setup entry point."""
from __future__ import annotations

import os

from autodub_gui import bootstrap


def is_first_run() -> bool:
    return not bootstrap.is_complete()


def mark_done() -> None:
    for step in bootstrap.steps():
        bootstrap.mark_completed(step.key)


def maybe_show_first_run(window) -> bool:
    if os.environ.get("AUTODUB_SMOKE") == "1" or bootstrap.is_complete():
        return False
    from autodub.config import Settings
    from autodub_gui.bootstrap_dialog import BootstrapDialog

    try:
        settings = Settings.load(override=True)
    except Exception:
        settings = None
    dialog = BootstrapDialog(settings, window)
    dialog.exec()
    return True
