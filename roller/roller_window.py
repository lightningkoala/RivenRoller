# Copyright (C) 2026 RivenRoller contributors.
# SPDX-License-Identifier: GPL-3.0-only

"""RivenLens' main window with the Auto roller panel added (by subclassing)."""

import time
import traceback

import screen_modes
from tracker_mode import ModeTracker

from gamepad import GamepadUnavailable, Hotkeys, InputSender
from roller import Roller
from roller_view import RollerView
from window import MainWindow
from worker import CaptureWorker


class RollerWindow(MainWindow):
    def __init__(self, preferences, store, worker_factory=CaptureWorker):
        super().__init__(preferences, worker_factory)
        self.run_log = preferences.directory / "logs" / "roller-run.log"
        self._seen = None
        self._logged_decision = ""
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
            self.log_screen(state)
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

    def log(self, text):
        """Append to a small local log of what the roller saw and pressed."""
        try:
            self.run_log.parent.mkdir(parents=True, exist_ok=True)
            if self.run_log.exists() and self.run_log.stat().st_size > 1024 * 1024:
                # Keep the previous file, so the end of a long run isn't lost.
                self.run_log.replace(self.run_log.with_name("roller-run.old.log"))
            with open(self.run_log, "a", encoding="utf-8") as file:
                file.write(f"{time.strftime('%H:%M:%S')} {text}\n")
        except OSError:
            pass

    def log_screen(self, state):
        """Log only changes: screen mode, which cards are fresh, roller phase."""
        cards = ",".join(
            f"{c.get('slot')}:{'stale' if c.get('snapshot') else 'fresh'}"
            for c in state.get("cards", [])
        )
        seen = (
            state.get("mode"),
            cards,
            self.roller.phase,
            state.get("status"),
            ModeTracker.last_read,
        )
        if seen != self._seen:
            self._seen = seen
            self.log(
                f"screen={seen[0]} cards=[{cards}] ocr={seen[3]} phase={seen[2]} "
                f"focused={self.input.focused()} read=[{seen[4]}] "
                f"text={list(screen_modes.last_texts)}"
            )

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
        self.log(f"--- start: weapon={self.state.get('weapon')} "
                 f"bindings={self.store.state['bindings']}")
        step = self.roller.start(time.monotonic())
        plan = getattr(self.roller, "prefs", self.state)
        self.log(
            "plan: format={} positives={} negative={} lock={} lockGrade={} "
            "spliceGrade={} | roller: {}".format(
                plan.get("format"), plan.get("positives"), plan.get("negative"),
                plan.get("lock"), plan.get("lockGrade"), plan.get("spliceGrade"),
                {k: v for k, v in self.store.state.items() if k not in ("bindings", "open")},
            )
        )
        self.apply_roll_step(step)

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
        self.log(f"press result: {'sent' if sent else 'NOT sent - ' + problem}")
        if sent:
            self.roller.sent(time.monotonic())
        else:
            self.apply_roll_step(self.roller.stop(problem))

    def apply_roll_step(self, step, quiet=False):
        decision = getattr(self.roller, "decision", "")
        if decision and decision != self._logged_decision:
            self._logged_decision = decision
            self.log(decision)
        if step.buttons:
            self.log(f"press {' '.join(step.buttons)} (phase={self.roller.phase})")
            self.input.send(step.buttons)
        if step.event:
            self.log(f"{step.event}: {step.message}")
        if step.event in ("paused", "done"):
            self.warning_sound.stop()
            self.good_sound.play()
        elif step.event == "stopped" and not quiet:
            self.good_sound.stop()
            self.warning_sound.play()
        if step.event and self.tray and not quiet:
            self.tray.showMessage("RivenRoller", step.message)
        self.roller_view.set_phase(self.roller.phase, step.message or None)
