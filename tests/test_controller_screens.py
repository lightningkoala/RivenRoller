# Copyright (C) 2026 RivenRoller contributors.
# SPDX-License-Identifier: GPL-3.0-only
"""Screen recognition with controller prompts (text as OCR read real screens)."""

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "roller"), str(ROOT / "engine/native"),
                str(ROOT / "engine/app"), str(ROOT / "tests")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import reader  # noqa: E402
import screen_modes  # noqa: E402
import tracker_mode  # noqa: E402
from tracker_mode import ModeTracker  # noqa: E402

ORIGINAL = reader.mode_from_lines
MODE = screen_modes.install()
reader.mode_from_lines = ORIGINAL  # keep other tests on the stock function


def lines(*texts):
    return [{"text": text} for text in texts]


CARD = ["Boar Ampi-lexidex", "+3.2 Punch Through", "MR 15"]


class ControllerScreens(unittest.TestCase):
    def test_dialog_with_button_glyphs(self):
        # Focused read of the real dialog: the Cross glyph became "X".
        seen = lines(" NO", "X YES", "Maximum", "MR 15", "CYCLE FOR,900",
                     "Remaining Kuva:,21,944,428")
        self.assertEqual(ORIGINAL(seen), "current")  # the stock rule misses it
        self.assertEqual(MODE(seen), "transition")
        for yes, no in (("YES", "NO"), ("(X) YES", "(O) NO"), ("XYES", "ONO"),
                        ("\u2297 YES", "\u25ce NO"), ("@ YES", "0 NO")):
            self.assertEqual(MODE(lines(yes, no, *CARD)), "transition", (yes, no))
        self.assertEqual(MODE(lines("X YES   O NO", *CARD)), "transition")
        self.assertEqual(
            MODE(lines("Cycle Riven into current selection?", "CONFIRM")), "transition")

    def test_yes_and_no_must_share_a_row(self):
        seen = [{"text": "YES", "y": 100, "h": 20}, {"text": "NO", "y": 400, "h": 20},
                {"text": "CYCLE FOR 900", "y": 500, "h": 20}]
        self.assertEqual(MODE(seen), "current")

    def test_cycle_screen_with_cursor_over_its_label(self):
        self.assertEqual(MODE(lines(*CARD, "Remaining Kuva:21,944,428")), "current")
        self.assertEqual(MODE(lines(*CARD, "CYCLE FOR 900")), "current")

    def test_other_screens_unchanged(self):
        self.assertEqual(MODE(lines(*CARD, "CONFIRM")), "comparison")
        for partial in ("CON", "CONF", "CONFI"):  # cursor over the label
            self.assertEqual(MODE(lines(*CARD, partial)), "comparison", partial)
        self.assertEqual(MODE(lines(*CARD, "CONTROLLER CONNECTED")), "unknown")
        self.assertEqual(MODE(lines(*CARD)), "unknown")
        self.assertEqual(MODE(lines("+12% Damage to Grineer", "NO")), "unknown")


def card(title, x, complete=True, screen_x=-1):
    return {"weapon": "Boar", "title": title, "format": "2p0n", "complete": complete,
            "rank": 8, "rankMode": "manual", "variantHint": None, "screenX": screen_x,
            "titleBounds": {"x": x - 100, "y": 650, "w": 200, "h": 30},
            "stats": [{"id": "damage", "value": float(sum(map(ord, title))), "unit": "%",
                       "polarity": "positive"},
                      {"id": "zoom", "value": 1.0, "unit": "%", "polarity": "positive"}]}


class HiddenButtonLabel(unittest.TestCase):
    """The reader can't place cards when the cursor hides the button label."""

    def setUp(self):
        tracker_mode.ModeTracker.anchor = None

    def slots(self, out):
        return {c["slot"]: (c["title"], c["snapshot"]) for c in out["cards"]}

    def test_cycle_screen_card_is_accepted(self):
        tracker = ModeTracker()
        for tick in range(1, 4):
            out = tracker.update({"cards": [card("old", 960)], "mode": "current"},
                                 tick / 10)
        self.assertEqual(self.slots(out), {"current": ("old", False)})

    def test_comparison_roles_follow_left_to_right_order(self):
        for order in ((0, 1), (1, 0)):  # whichever order the reader lists them
            tracker_mode.ModeTracker.anchor = None
            tracker = ModeTracker()
            pair = [card("old", 610), card("new", 960)]
            for tick in range(1, 4):
                out = tracker.update(
                    {"cards": [pair[i] for i in order], "mode": "unknown"}, tick / 10)
            self.assertEqual(out["mode"], "comparison")
            self.assertEqual(self.slots(out),
                             {"current": ("old", False), "new": ("new", False)})

    def test_remembered_button_position_places_cards(self):
        tracker = ModeTracker()
        # Label readable once: the reader placed the centered card itself.
        tracker.update({"cards": [card("old", 960, screen_x=0.5)], "mode": "current"}, 0.1)
        placed = tracker._place({"cards": [card("old", 610), card("new", 960)],
                                 "mode": "unknown"})["cards"]
        self.assertAlmostEqual(placed[1]["screenX"], 0.5)
        self.assertLess(placed[0]["screenX"], 0.43)

    def test_unknown_single_card_is_not_called_a_comparison(self):
        tracker = ModeTracker()
        out = tracker.update({"cards": [card("old", 960)], "mode": "unknown"}, 0.1)
        self.assertEqual(out["mode"], "unknown")
        other = {**card("new", 960), "weapon": "Sobek"}
        out = tracker.update({"cards": [card("old", 610), other], "mode": "unknown"}, 0.2)
        self.assertEqual(out["mode"], "unknown")

    def test_incomplete_old_card_is_still_the_comparison_screen(self):
        tracker = ModeTracker()
        for tick in range(1, 4):
            out = tracker.update({"cards": [card("old", 610, False), card("new", 960)],
                                  "mode": "unknown"}, tick / 10)
        self.assertEqual(out["mode"], "comparison")
        self.assertEqual(self.slots(out), {"new": ("new", False)})


if __name__ == "__main__":
    unittest.main()
