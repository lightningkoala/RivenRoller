# Copyright (C) 2026 RivenRoller contributors.
# SPDX-License-Identifier: GPL-3.0-only
"""Drive the real RollerWindow with a fake capture worker and fake controller."""

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "roller"), str(ROOT / "engine/native"),
                str(ROOT / "engine/app"), str(ROOT / "tests")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
data = tempfile.mkdtemp()
os.environ["XDG_DATA_HOME"] = os.environ["LOCALAPPDATA"] = data

import instance  # noqa: E402
import settings  # noqa: E402

instance.data_directory = settings.data_directory
import tracker_mode  # noqa: E402

tracker_mode.install()

from PySide6.QtCore import QCoreApplication, QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
import audio  # noqa: E402

audio.SoundChannel.play = lambda self, *a: None  # no sound device in CI
from gamepad import InputSender  # noqa: E402
from preferences import Preferences  # noqa: E402
from roller_window import RollerWindow  # noqa: E402
from test_roller import card, plan, screen, stat  # noqa: E402


class FakeWorker(QObject):
    updated = Signal(object)
    displays = Signal(object, object)
    finished = Signal()

    def __init__(self, *_):
        super().__init__()
        self.rev = 0

    def start(self):
        pass

    def configure(self, *_):
        self.rev += 1
        return self.rev

    def isRunning(self):
        return False

    def shutdown(self):
        pass


class Pad:
    log = []

    def press(self, buttons):
        Pad.log.extend(buttons)

    def close(self):
        pass


directory = settings.data_directory()
prefs = Preferences(directory)
prefs.state.update(plan())
store = settings.RollerSettings(directory)
assert store.state["autoKeepNew"] is False
window = RollerWindow(prefs, store, worker_factory=FakeWorker)
assert window.windowTitle() == "RivenRoller"
assert window.roller_view.parentWidget() is window.planner.parentWidget()
window.input.close()
window.input = InputSender(window, gamepad_factory=Pad, focused=lambda: True)
window.input.finished.connect(window.input_finished)
window.running, window.revision = True, window.worker.rev


def push(state):
    window.receive({"revision": window.revision, **state})
    deadline = time.time() + 1
    while window.roller and window.roller.sending and time.time() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    QCoreApplication.processEvents()


junk = card(stat("damage"), stat("zoom"), stat("slash"),
            stat("puncture", polarity="negative"))
window.start_roller()
push(screen("current", junk))
push(screen("current", junk))
push(screen("transition", junk))
ingredient = card(stat("reload-speed", "S"), stat("zoom"), stat("slash"),
                  stat("puncture", polarity="negative"))
push(screen("comparison", junk, ingredient))
push(screen("comparison", junk, ingredient))
assert Pad.log == ["cross", "cross"], Pad.log  # wanted roll: nothing pressed
assert window.roller.phase == "paused", window.roller.message
assert "Keep the NEW roll yourself" in window.roller_view.status.text()
assert "Reload Speed" in window.roller_view.status.text()
push(screen("current", ingredient))  # the player kept the new card
assert not window.roller_view.start.isEnabled()
# Resume while RivenRoller itself has focus: it waits instead of pressing.
window.resume_roller()
window.input._focused = lambda: False
push(screen("current", ingredient))
push(screen("current", ingredient))
assert window.roller.active and Pad.log == ["cross", "cross"]
assert "Click into Warframe" in window.roller_view.status.text()
# Focus arrives, then is lost again just before the button goes out.
import roller as roller_module  # noqa: E402

roller_module.AIM_SECONDS = 0  # skip the "put the pointer on Cycle" wait
answers = iter([True])
window.input._focused = lambda: next(answers, False)
push(screen("current", ingredient))
for _ in range(50):
    QCoreApplication.processEvents()
    time.sleep(0.01)
assert window.roller.phase == "stopped", window.roller.phase
assert "focused" in window.roller.message and Pad.log == ["cross", "cross"]
window.apply_capture()  # pausing OCR must not error with a stopped roller
assert not any((Path(data) / "Arbitrations").glob("**/*")), "touched RivenLens data"
window.close()
print("WINDOW OK")
