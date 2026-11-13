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


# RivenLens' own stage dings stay silent during a run (a locked or spliced stat
# would otherwise ding on every roll) and aren't replayed afterwards.
from roller_window import QuietHistory  # noqa: E402

assert isinstance(window.match_history, QuietHistory)
history = QuietHistory()
history.muted = True
assert history.take(["a", "b"]) == []
history.muted = False
assert history.take(["a", "b", "c"]) == ["c"]

# Phone companion: off by default; when enabled it serves the run read-only.
import json  # noqa: E402
import socket  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

assert window.companion is None and not window.companion_store.state["enabled"]
assert window.companion_view.parentWidget() is window.planner.parentWidget()
probe = socket.socket()
probe.bind(("127.0.0.1", 0))
free_port = probe.getsockname()[1]
probe.close()
notified = []
window.notifier.opener = lambda request: notified.append(request)
window.companion_store.state["port"] = free_port
window.companion_view.topic.setText("rivenroller-test")
window.companion_view.enabled.setChecked(True)  # as ticked by the user
assert window.companion is not None and "?k=" in window.companion_view.link.text()
assert (directory / "companion.json").is_file()


def phone(path="/state"):
    url = "http://127.0.0.1:{}{}?k={}".format(
        window.companion.port, path, window.companion.token)
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.read()


assert json.loads(phone())["phase"] == "idle"

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
assert window.match_history.muted  # the run was active on the last frame
assert Pad.log == ["cross", "cross"], Pad.log  # wanted roll: nothing pressed
assert window.roller.phase == "paused", window.roller.message
assert "Keep the NEW roll yourself" in window.roller_view.status.text()
assert "Reload Speed" in window.roller_view.status.text()
seen = json.loads(phone())
assert seen["phase"] == "paused" and seen["rolls"] == 1, seen
assert seen["stage"] == "partner" and "Reload Speed" in seen["message"]
assert seen["plan"]["weapon"] and seen["plan"]["target"].startswith("+"), seen["plan"]
(rolled,) = seen["history"]
assert rolled["roll"] == 1 and rolled["wanted"] is True and rolled["stage"] == "ingredient"
assert {"name": "Reload Speed", "polarity": "positive", "grade": "S"}.items() <= {
    k: v for k, v in rolled["stats"][0].items()}.items(), rolled
assert len(rolled["stats"]) == 4 and rolled["stats"][3]["polarity"] == "negative"
for _ in range(100):  # the notification goes out on its own thread
    if notified:
        break
    QCoreApplication.processEvents()
    time.sleep(0.01)
assert len(notified) == 1 and notified[0].full_url == "https://ntfy.sh/rivenroller-test"
assert notified[0].headers["Title"] == "Roller needs you"
assert "Reload Speed" in notified[0].data.decode("utf-8")
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
for _ in range(100):
    if len(notified) > 1:
        break
    QCoreApplication.processEvents()
    time.sleep(0.01)
assert notified[1].headers["Title"] == "Roller stopped", notified
assert json.loads(phone())["phase"] == "stopped"
# Turning the page off closes the port.
window.companion_view.enabled.setChecked(False)
assert window.companion is None and "off" in window.companion_view.link.text()
try:
    urllib.request.urlopen(f"http://127.0.0.1:{free_port}/", timeout=2)
    raise AssertionError("page still served after being turned off")
except urllib.error.HTTPError:
    raise AssertionError("page still served after being turned off")
except OSError:
    pass
window.apply_capture()  # pausing OCR must not error with a stopped roller
assert not any((Path(data) / "Arbitrations").glob("**/*")), "touched RivenLens data"
window.close()
print("WINDOW OK")
