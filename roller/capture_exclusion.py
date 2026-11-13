# Copyright (C) 2026 RivenRoller contributors.
# SPDX-License-Identifier: GPL-3.0-only

"""Keep RivenRoller's own windows out of the screen capture.

The window shows Riven names and stats. When it sits on the captured monitor,
OCR reads that text too, and the reader can mistake it for extra Riven cards
and reject the frame. Windows can exclude a window from capture (Windows 10
version 2004 and later); the window stays visible to you.
"""

import sys

from PySide6.QtCore import QEvent, QObject

WDA_EXCLUDEFROMCAPTURE = 0x11


def exclude_window(widget):
    """True when the window was excluded from capture."""
    if sys.platform != "win32":
        return False
    import ctypes

    try:
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        user.SetWindowDisplayAffinity.restype = ctypes.c_int
        return bool(
            user.SetWindowDisplayAffinity(int(widget.winId()), WDA_EXCLUDEFROMCAPTURE)
        )
    except Exception:
        return False


class CaptureExclusion(QObject):
    """Applies the exclusion to every top-level window as it is shown
    (main window, dialogs, dropdown lists, tooltips)."""

    def __init__(self, app, exclude=exclude_window):
        super().__init__(app)
        self._exclude = exclude
        self.failed = False
        app.installEventFilter(self)

    def eventFilter(self, watched, event):
        if (
            event.type() == QEvent.Type.Show
            and watched.isWidgetType()
            and watched.isWindow()
        ):
            if not self._exclude(watched):
                self.failed = True
        return False
