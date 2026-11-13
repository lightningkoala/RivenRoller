# Copyright (C) 2026 RivenRoller contributors; based on RivenLens
# (C) 2026 remesis and RivenLens contributors.
# SPDX-License-Identifier: GPL-3.0-only

"""Virtual DualShock 4 output for the auto roller, plus a game-focus check.

Uses vgamepad (ViGEmBus on Windows). Warframe shows PlayStation prompts for it;
Cross, L1 and R1 match a DualSense. Presses use fixed timings and are only sent
while Warframe's own window is in the foreground.
"""

import queue
import sys
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal

HOLD_SECONDS = 0.06
GAP_SECONDS = 0.15
GAME_TITLE = "Warframe"


class GamepadUnavailable(RuntimeError):
    pass


def foreground_title():
    """Title of the foreground window; never opens the game process."""
    if sys.platform != "win32":
        return None
    import ctypes

    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetForegroundWindow.restype = ctypes.c_void_p
    handle = user.GetForegroundWindow()
    if not handle:
        return ""
    buffer = ctypes.create_unicode_buffer(256)
    user.GetWindowTextW(ctypes.c_void_p(handle), buffer, 256)
    return buffer.value


def game_focused():
    """True only when the foreground window is titled exactly "Warframe"."""
    return foreground_title() == GAME_TITLE


def focus_problem():
    title = foreground_title()
    shown = f' (focused: "{title[:40]}")' if title else ""
    return "Warframe isn't the focused window" + shown + "."


class VirtualGamepad:
    def __init__(self):
        if sys.platform != "win32":
            raise GamepadUnavailable("The auto roller currently supports Windows only.")
        try:
            import vgamepad
        except Exception as exc:
            raise GamepadUnavailable(
                "Controller output needs vgamepad and ViGEmBus. Install with "
                "'pip install vgamepad' (it offers the ViGEmBus driver installer)."
            ) from exc
        try:
            self.pad = vgamepad.VDS4Gamepad()
        except Exception as exc:
            raise GamepadUnavailable(
                "Couldn't create the virtual controller. Is ViGEmBus installed?"
            ) from exc
        ds4 = vgamepad.DS4_BUTTONS
        self.buttons = {
            "cross": ds4.DS4_BUTTON_CROSS,
            "circle": ds4.DS4_BUTTON_CIRCLE,
            "square": ds4.DS4_BUTTON_SQUARE,
            "triangle": ds4.DS4_BUTTON_TRIANGLE,
            "l1": ds4.DS4_BUTTON_SHOULDER_LEFT,
            "r1": ds4.DS4_BUTTON_SHOULDER_RIGHT,
        }
        # Let Warframe register the new device before the first press.
        self.pad.reset()
        self.pad.update()

    def press(self, names):
        for name in names:
            button = self.buttons[name]
            self.pad.press_button(button=button)
            self.pad.update()
            time.sleep(HOLD_SECONDS)
            self.pad.release_button(button=button)
            self.pad.update()
            time.sleep(GAP_SECONDS)

    def close(self):
        try:
            self.pad.reset()
            self.pad.update()
        except Exception:
            pass
        self.pad = None


class InputSender(QObject):
    """Presses buttons on a background thread; refuses if Warframe isn't focused."""

    finished = Signal(bool, str)  # sent, problem

    def __init__(self, parent=None, gamepad_factory=VirtualGamepad, focused=game_focused):
        super().__init__(parent)
        self._factory, self._focused = gamepad_factory, focused
        self._pad = None
        self._jobs = queue.Queue()
        self._thread = None

    def open(self):
        """Create the controller now, so setup problems show before a run starts."""
        if self._pad is None:
            self._pad = self._factory()
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def focused(self):
        return bool(self._focused())

    def send(self, buttons):
        self._jobs.put(tuple(buttons))

    def _run(self):
        while True:
            buttons = self._jobs.get()
            if buttons is None:
                return
            problem = ""
            for name in buttons:
                if not self._focused():
                    problem = focus_problem()
                    break
                try:
                    self._pad.press([name])
                except Exception as exc:
                    problem = f"Controller output failed: {exc}"
                    break
            self.finished.emit(not problem, problem)

    def close(self):
        if self._thread is not None:
            self._jobs.put(None)
            self._thread.join(timeout=2)
            self._thread = None
        if self._pad is not None:
            self._pad.close()
            self._pad = None


HOTKEYS = {"go": 0x77, "stop": 0x78}  # F8 start/resume, F9 stop (virtual keys)


class Hotkeys(QObject):
    """F8/F9 anywhere, so a run can start with the pointer already on Cycle.

    Polls the two keys' state; it installs no keyboard hook.
    """

    go = Signal()
    stop = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._down = {name: False for name in HOTKEYS}
        self._state = None
        if sys.platform == "win32":
            import ctypes

            self._state = ctypes.WinDLL("user32").GetAsyncKeyState
            self._state.restype = ctypes.c_short
            self._timer = QTimer(self)
            self._timer.setInterval(40)
            self._timer.timeout.connect(self.poll)
            self._timer.start()

    def poll(self, read=None):
        read = read or (lambda key: bool(self._state(key) & 0x8000))
        for name, key in HOTKEYS.items():
            down = read(key)
            if down and not self._down[name]:
                getattr(self, name).emit()
            self._down[name] = down
