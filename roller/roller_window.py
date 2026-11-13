# Copyright (C) 2026 RivenRoller contributors.
# SPDX-License-Identifier: GPL-3.0-only

"""RivenLens' main window with the Auto roller panel added (by subclassing)."""

import time
import traceback

import screen_modes
from tracker_mode import ModeTracker

from PySide6.QtCore import Signal

from alerts import History
from companion import Companion, CompanionSettings, Notifier, RunState
from companion_view import CompanionView
from gamepad import GamepadUnavailable, Hotkeys, InputSender
from roller import STAGE_LABELS, Roller
from roller_view import RollerView
from window import MainWindow
from worker import CaptureWorker


class QuietHistory(History):
    """RivenLens' alert history, silent while the roller is running.

    RivenLens dings for every new card that carries a watched stat. Once a stat
    is locked or spliced it is on every roll, so that alert would sound on each
    one. The roller plays its own sound when it pauses, finishes or stops.
    Matches are still recorded, so they don't all ding when the run ends.
    """

    muted = False

    def take(self, keys):
        fresh = super().take(keys)
        return [] if self.muted else fresh


class RollerWindow(MainWindow):
    notify_result = Signal(str)  # from the notification thread

    def __init__(self, preferences, store, worker_factory=CaptureWorker):
        super().__init__(preferences, worker_factory)
        self.match_history = QuietHistory()
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
        # Phone companion: read-only status page and push notifications.
        self.companion = None
        self.run_state = RunState()
        self.companion_store = CompanionSettings(preferences.directory)
        self.notifier = Notifier(on_result=self.notify_result.emit)
        self.companion_view = CompanionView(self.companion_store)
        self.companion_view.changed.connect(self.apply_companion)
        self.companion_view.toggled.connect(self.schedule_balance)
        self.companion_view.test_requested.connect(self.test_notification)
        self.notify_result.connect(self.companion_view.show_notify_result)
        column.insertSpacing(column.count() - 1, 8)
        column.insertWidget(column.count() - 1, self.companion_view)
        self.apply_companion()
        self.schedule_balance()

    # ------------------------------------------------- RivenLens window hooks

    def receive(self, state):
        roller = getattr(self, "roller", None)
        self.match_history.muted = roller is not None and roller.active
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
            if getattr(self, "companion", None) is not None:
                self.companion.close()
                self.companion = None
        super().closeEvent(event)

    # ------------------------------------------------------- phone companion

    def apply_companion(self):
        """Start, stop or restart the status page to match its settings."""
        self.companion_store.save()
        settings = self.companion_store.state
        if self.companion is not None and (
            not settings["enabled"] or self.companion.token != settings["token"]
        ):
            self.companion.close()
            self.companion = None
        if settings["enabled"] and self.companion is None:
            try:
                self.companion = Companion(settings["token"], settings["port"])
            except OSError as exc:
                self.companion_view.show_link(
                    None, problem=f"Couldn't start the page: {exc}"
                )
                return
            self.publish_companion()
        if self.companion is None:
            self.companion_view.show_link(None)
        else:
            self.companion_view.show_link(self.companion.address(), self.companion.token)

    def publish_companion(self):
        roller = self.roller
        if roller is not None:
            stage = roller.stage
            self.run_state.update(
                phase=roller.phase,
                stage=stage,
                stageLabel=STAGE_LABELS.get(stage, ""),
                message=roller.message,
                rolls=roller.rolls,
                maxRolls=roller.settings["maxRolls"],
            )
            record = getattr(roller, "record", None)
            if record:
                self.run_state.add_roll(record)
        if self.companion is not None:
            self.companion.publish(self.run_state.data)

    def plan_summary(self):
        planner = getattr(self.roller, "planner", None)
        if planner is None:
            return {}
        parts = [
            "+" + " / ".join(planner.name(i) for i in slot)
            for slot in planner.positive_options
            if slot
        ]
        if planner.has_negative:
            negatives = [t for t in planner.targets(3) if t]
            if negatives:
                parts.append("−" + " / ".join(planner.name(i) for i in negatives))
        return {"weapon": planner.weapon["name"], "target": ", ".join(parts)}

    def test_notification(self):
        sent = self.notifier.send(
            self.companion_store.state,
            "test",
            "Notifications from RivenRoller are working.",
        )
        self.companion_view.show_notify_result(
            "Sending..." if sent else "Fill in an ntfy topic or a Discord webhook first.",
            pending=True,
        )

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
        self.run_state.reset(self.plan_summary())
        plan = getattr(self.roller, "prefs", self.state)
        planner = getattr(self.roller, "planner", None)
        # Each slot lists every accepted stat (first choice plus alternatives).
        positives = (
            [list(options) for options in planner.positive_options]
            if planner
            else plan.get("positives")
        )
        negatives = (
            ([t for t in planner.targets(3) if t] if planner.has_negative else [])
            if planner
            else plan.get("negative")
        )
        self.log(
            "plan: format={} positives={} negative={} lock={} lockGrade={} "
            "spliceGrade={} | roller: {}".format(
                plan.get("format"), positives, negatives,
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
        if step.event and not quiet:
            self.notifier.send(self.companion_store.state, step.event, step.message)
        self.publish_companion()
        self.roller_view.set_phase(self.roller.phase, step.message or None)
