# Copyright (C) 2026 RivenRoller contributors.
# SPDX-License-Identifier: GPL-3.0-only

"""RivenLens' main window with the Auto roller panel added (by subclassing)."""

import time
import traceback

from gamepad import GamepadUnavailable, Hotkeys, InputSender
from roller import Roller
from roller_view import RollerView
from window import MainWindow
from worker import CaptureWorker


class RollerWindow(MainWindow):
    def __init__(self, preferences, store, worker_factory=CaptureWorker):
        super().__init__(preferences, worker_factory)
        self.setWindowTitle("RivenRoller")
        self.store = store
        self.roller = None
        self.roller_view = RollerView(store)
        self.roller_view.changed.connect(store.save)
        self.roller_view.toggled.connect(self.schedule_balance)
        self.roller_view.start_requested.connect(self.start_roller)
        self.roller_view.resume_requested.connect(self.resume_roller)
        self.roller_view.stop_requested.connect(
            lambda: self.stop_roller("Stopped by you.", quiet=True)
        )
        self.input = InputSender(self)
        self.input.finished.connect(self.input_finished)
        self.hotkeys = Hotkeys(self)
        self.hotkeys.go.connect(self.hotkey_go)
        self.hotkeys.stop.connect(
            lambda: self.stop_roller("Stopped by you (F9).", quiet=True)
        )
        # The planner sits in a wrapper column that ends with a stretch.
        column = self.planner.parentWidget().layout()
        column.insertSpacing(column.count() - 1, 8)
        column.insertWidget(column.count() - 1, self.roller_view)
        self.schedule_balance()

    # ------------------------------------------------- RivenLens window hooks

    def receive(self, state):
        super().receive(state)
        if (
            not self._closing
            and state.get("revision") == self.revision
            and getattr(self, "roller", None) is not None
            and self.roller.active
        ):
            try:
                step = self.roller.step(
                    state, time.monotonic(), self.input.focused()
                )
            except Exception as exc:  # never keep pressing after a bug
                traceback.print_exc()
                step = self.roller.stop(f"Internal roller error: {exc}")
            self.apply_roll_step(step)

    def apply_capture(self):
        # Pausing OCR, or changing monitor/language, resets the tracker.
        self.stop_roller("Capture was paused or reconfigured.")
        super().apply_capture()

    def closeEvent(self, event):
        if not self._closing:
            if getattr(self, "roller", None) is not None:
                self.roller.stop("Closing.")
            if hasattr(self, "input"):
                self.input.close()
        super().closeEvent(event)

    # ----------------------------------------------------------- auto roller

    def start_roller(self):
        if self.roller is not None and self.roller.active:
            return
        if not self.running:
            self.roller_view.set_phase("stopped", "Press Start OCR first.")
            return
        try:
            self.input.open()
        except GamepadUnavailable as exc:
            self.roller_view.set_phase("stopped", str(exc))
            return
        self.roller = Roller(self.catalog, self.state, self.store.state)
        self.apply_roll_step(self.roller.start(time.monotonic()))

    def hotkey_go(self):
        """F8: start, or resume when paused. Ignored mid-run and while typing here."""
        if self._closing or self.isActiveWindow():
            return
        if self.roller is not None and self.roller.phase == Roller.PAUSED:
            self.resume_roller()
        elif self.roller is None or not self.roller.active:
            self.start_roller()

    def resume_roller(self):
        if self.roller is not None:
            self.apply_roll_step(self.roller.resume(time.monotonic()))

    def stop_roller(self, message, quiet=False):
        roller = getattr(self, "roller", None)
        if roller is not None and (roller.active or roller.phase == Roller.PAUSED):
            self.apply_roll_step(roller.stop(message), quiet=quiet)

    def input_finished(self, sent, problem):
        if self.roller is None or not self.roller.active:
            return
        if sent:
            self.roller.sent(time.monotonic())
        else:
            self.apply_roll_step(self.roller.stop(problem))

    def apply_roll_step(self, step, quiet=False):
        if step.buttons:
            self.input.send(step.buttons)
        if step.event in ("paused", "done"):
            self.warning_sound.stop()
            self.good_sound.play()
        elif step.event == "stopped" and not quiet:
            self.good_sound.stop()
            self.warning_sound.play()
        if step.event and self.tray and not quiet:
            self.tray.showMessage("RivenRoller", step.message)
        self.roller_view.set_phase(self.roller.phase, step.message or None)
