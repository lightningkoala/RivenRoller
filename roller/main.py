# Copyright (C) 2026 RivenRoller contributors; based on RivenLens
# (C) 2026 remesis and RivenLens contributors.
# SPDX-License-Identifier: GPL-3.0-only

"""RivenRoller entry point: the RivenLens engine plus the Auto roller.

Uses its own data folder and never starts RivenLens' updater, so an installed
copy of RivenLens and its settings are left untouched.
"""

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engine"
sys.path[:0] = [str(ROOT / "roller"), str(ENGINE / "native"), str(ENGINE / "app")]

# Redirect the engine's data folder (OCR models, runtimes, logs) before any
# engine module imports it. Must run before importing worker/window/OCR code.
import instance  # noqa: E402
import settings  # noqa: E402

instance.data_directory = settings.data_directory

import tracker_mode  # noqa: E402

tracker_mode.install()

import screen_modes  # noqa: E402

screen_modes.install()

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QColor, QFont, QIcon, QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from appearance import theme_for  # noqa: E402
from desktop import ICON  # noqa: E402
from preferences import Preferences  # noqa: E402
from releases import ReleaseConfig  # noqa: E402
from roller_window import RollerWindow  # noqa: E402

APP_ID = "RivenRoller.App"


def set_app_identity():
    """Group RivenRoller separately from RivenLens on the Windows taskbar."""
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.WinDLL("shell32").SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def open_log(directory):
    """Without a console (pythonw), keep errors in a small local log file."""
    if sys.stderr is not None:
        return
    try:
        logs = directory / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        path = logs / "rivenroller.log"
        if path.exists() and path.stat().st_size > 1024 * 1024:
            path.unlink()
        sys.stderr = sys.stdout = open(path, "a", encoding="utf-8", buffering=1)
    except OSError:
        pass


def main():
    open_log(settings.data_directory())
    set_app_identity()
    app = QApplication(sys.argv)
    app.setOrganizationName("RivenRoller")
    app.setApplicationName("RivenRoller")
    app.setApplicationDisplayName("RivenRoller")
    app.setWindowIcon(QIcon(str(ICON)))
    app.setApplicationVersion(ReleaseConfig.load().version)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 9))
    palette = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, "#0b0f14"),
        (QPalette.ColorRole.Base, "#182432"),
        (QPalette.ColorRole.Text, "#e5edf7"),
        (QPalette.ColorRole.WindowText, "#e5edf7"),
        (QPalette.ColorRole.ButtonText, "#e5edf7"),
        (QPalette.ColorRole.Highlight, "#28516a"),
        (QPalette.ColorRole.HighlightedText, "#ffffff"),
    ):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setStyleSheet(theme_for())
    directory = settings.data_directory()
    imported = settings.import_rivenlens_preferences(directory)
    lease = instance.InstallationLease(ROOT, directory / "locks")
    if not lease.acquire():
        QMessageBox.information(None, "RivenRoller", "RivenRoller is already open.")
        return 0
    try:
        try:
            window = RollerWindow(
                Preferences(directory), settings.RollerSettings(directory)
            )
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(None, "RivenRoller could not start", str(exc))
            return 1
        window.show()
        if imported:
            QTimer.singleShot(
                400,
                lambda: window.roller_view.status.setText(
                    "Copied your RivenLens plans and capture settings (RivenLens "
                    "itself was not changed)."
                ),
            )
        return app.exec()
    finally:
        lease.close()


if __name__ == "__main__":
    sys.exit(main())
