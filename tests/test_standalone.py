# Copyright (C) 2026 RivenRoller contributors.
# SPDX-License-Identifier: GPL-3.0-only
"""Standalone guarantees: pristine engine, isolated data, tracker mode, window."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "roller"), str(ROOT / "engine/native"),
                str(ROOT / "engine/app"), str(ROOT / "tests")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import settings  # noqa: E402
from tracker_mode import ModeTracker  # noqa: E402


class StandaloneTests(unittest.TestCase):
    def test_data_folder_is_separate(self):
        self.assertNotIn("RivenLens", str(settings.data_directory()))
        self.assertNotEqual(settings.data_directory(), settings.rivenlens_directory())

    def test_first_run_copies_rivenlens_preferences_read_only(self):
        with tempfile.TemporaryDirectory() as home:
            os.environ["XDG_DATA_HOME"] = home
            os.environ["LOCALAPPDATA"] = home
            try:
                source = settings.rivenlens_directory()
                source.mkdir(parents=True)
                (source / "preferences.json").write_text('{"weapon": "x"}')
                before = (source / "preferences.json").stat().st_mtime_ns
                target = settings.data_directory()
                self.assertTrue(settings.import_rivenlens_preferences(target))
                self.assertFalse(settings.import_rivenlens_preferences(target))
                self.assertEqual(json.loads((target / "preferences.json").read_text()),
                                 {"weapon": "x"})
                self.assertEqual((source / "preferences.json").stat().st_mtime_ns, before)
                self.assertEqual(sorted(p.name for p in source.iterdir()),
                                 ["preferences.json"])
                store = settings.RollerSettings(target)
                store.state["maxRolls"] = 7
                store.save()
                self.assertEqual(settings.RollerSettings(target).state["maxRolls"], 7)
            finally:
                os.environ.pop("XDG_DATA_HOME")
                os.environ.pop("LOCALAPPDATA")

    def test_mode_tracker_reports_screen(self):
        tracker = ModeTracker()
        for mode in ("current", "transition", "comparison", "unknown"):
            out = tracker.update({"cards": [], "mode": mode}, 1.0)
            self.assertEqual(out["mode"], mode)
        out = tracker.update({"cards": [], "mode": "hover"}, 2.0)
        self.assertEqual(out["mode"], "hover")
        out = tracker.update({"cards": [], "mode": "unknown"}, 2.1)
        self.assertEqual(out["mode"], "hover")

    def test_hotkeys_fire_once_per_press(self):
        from gamepad import HOTKEYS, Hotkeys
        keys = Hotkeys()
        fired = []
        keys.go.connect(lambda: fired.append("go"))
        keys.stop.connect(lambda: fired.append("stop"))
        held = set()
        read = lambda key: key in held
        keys.poll(read)
        held.add(HOTKEYS["go"])
        keys.poll(read)
        keys.poll(read)  # still held: no repeat
        held.clear()
        keys.poll(read)
        held.add(HOTKEYS["stop"])
        keys.poll(read)
        self.assertEqual(fired, ["go", "stop"])

    def test_engine_matches_upstream_manifest(self):
        manifest = json.loads((ROOT / "engine/MANIFEST.json").read_text())
        for relative, digest in manifest["files"].items():
            data = (ROOT / "engine" / relative).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), digest, relative)

    def test_window_end_to_end(self):
        """Run the real window in a subprocess (Qt multimedia needs its own process)."""
        script = ROOT / "tests" / "window_check.py"
        result = subprocess.run([sys.executable, str(script)], capture_output=True,
                                text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr[-2000:])
        self.assertIn("WINDOW OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
