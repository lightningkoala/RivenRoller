# Copyright (C) 2026 RivenRoller contributors.
# SPDX-License-Identifier: GPL-3.0-only
"""Headless tests for the auto roller state machine (no game, no controller).

Run: python -m unittest discover -s tests
"""

import copy
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "roller"), str(ROOT / "engine/native"), str(ROOT / "engine/app")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from catalog import Catalog  # noqa: E402
from grading import GRADES, trait_range  # noqa: E402
from preferences import DEFAULTS  # noqa: E402
from roller import Roller  # noqa: E402

CATALOG = Catalog()
BOAR = CATALOG.by_id["boar-shotgun-primary"]
VARIANT = CATALOG.variant({"weapon": "Boar"})
MIDPOINT = {name: (lo + hi) / 2 for name, lo, hi in GRADES}


def stat(identity, grade="B", polarity="positive", fmt="3p1n"):
    trait = CATALOG.trait(VARIANT, identity)
    q = 1 + MIDPOINT[grade] / 100
    value = trait_range(trait, VARIANT["disposition"], fmt, polarity,
                        CATALOG.range_model, 8, [q, q])["low"]
    return {"id": identity, "value": value, "unit": trait["unit"],
            "polarity": polarity}


def card(*stats, fmt="3p1n", weapon="Boar"):
    return {"weapon": weapon, "title": "Boar Test", "format": fmt,
            "stats": list(stats), "complete": True, "rank": 8,
            "rankMode": "manual"}


def screen(mode, current=None, new=None, **extra):
    cards = []
    if current:
        cards.append({**current, "slot": "current", "snapshot": False})
    if new:
        cards.append({**new, "slot": "new", "snapshot": False})
    return {"mode": mode, "cards": cards, "status": "reading", **extra}


def plan(**changes):
    prefs = copy.deepcopy(DEFAULTS)
    prefs.update(weapon=BOAR["id"], variant="boar", format="3p1n",
                 positives=["multishot", "fire-rate-attack-speed", "ammo-efficiency"],
                 negative="impact", spliceGrade="S", lockGrade="F")
    prefs.update(changes)
    return prefs


class Game:
    """Feeds worker states to a roller and records what it pressed."""

    def __init__(self, roller, current):
        self.roller, self.current, self.t = roller, current, 0.0
        self.pressed = []
        self.events = []

    def feed(self, state):
        # The Cycle screen needs two matching reads before the roller acts.
        for _ in range(2 if state["mode"] == "current" else 1):
            self.t += 0.1
            step = self.roller.step(state, self.t)
            self._apply(step)
            if step.event or step.buttons:
                break
        return step

    def _apply(self, step):
        if step.buttons:
            self.pressed.append(step.buttons)
            self.roller.sent(self.t)
        if step.event:
            self.events.append((step.event, step.message))

    def start(self):
        self._apply(self.roller.start(self.t))
        return self.feed(screen("current", self.current))

    def roll(self, new):
        """One full cycle: dialog, comparison (two stable reads), then settle."""
        self.feed(screen("transition", self.current))
        self.feed(screen("comparison", self.current))  # new card not read yet
        self.feed(screen("comparison", self.current, new))
        step = self.feed(screen("comparison", self.current, new))
        kept = new if step.buttons == ("r1", "cross") else self.current
        self.current = kept
        return self.feed(screen("current", kept)), kept is new


class RollerTests(unittest.TestCase):
    def roller(self, prefs=None, **settings):
        return Roller(CATALOG, prefs or plan(), {"autoKeepNew": True, **settings})

    def junk(self):
        return card(stat("damage"), stat("zoom"), stat("punch-through"),
                    stat("puncture", polarity="negative"))

    def test_boar_splice_flow(self):
        roller = self.roller()
        game = Game(roller, self.junk())
        game.start()
        self.assertEqual(roller.stage, "ingredient")
        self.assertEqual(game.pressed, [("cross",)])

        # An A-grade ingredient is not enough for an S splice: keep current.
        step, kept_new = game.roll(card(stat("reload-speed", "A"), stat("damage"),
                                        stat("zoom"), stat("puncture", polarity="negative")))
        self.assertFalse(kept_new)
        self.assertEqual(roller.phase, "await_dialog")  # cycled again

        # An S-grade ingredient: keep it and pause for the user to lock it.
        ingredient = card(stat("magazine-capacity", "S"), stat("damage"), stat("zoom"),
                          stat("puncture", polarity="negative"))
        step, kept_new = game.roll(ingredient)
        self.assertTrue(kept_new)
        self.assertEqual(step.event, "paused")
        self.assertIn("Magazine Capacity", step.message)
        self.assertEqual(roller.stage, "partner")

        # Resume -> roll until the F-grade partner appears with the locked stat.
        game._apply(roller.resume(game.t))
        game.feed(screen("current", game.current))
        step, kept_new = game.roll(card(stat("magazine-capacity", "S"), stat("damage"),
                                        stat("zoom"), stat("slash", polarity="negative")))
        self.assertFalse(kept_new)
        step, kept_new = game.roll(card(stat("magazine-capacity", "S"),
                                        stat("reload-speed", "F"), stat("zoom"),
                                        stat("slash", polarity="negative")))
        self.assertTrue(kept_new)
        self.assertEqual(step.event, "paused")
        self.assertIn("Splice", step.message)
        self.assertEqual(roller.stage, "final")

        # Resume without splicing: refuse to roll.
        game._apply(roller.resume(game.t))
        step = game.feed(screen("current", game.current))
        self.assertEqual(step.event, "paused")
        self.assertIn("spliced", step.message)

        # After splicing, roll to the final target.
        spliced = card(stat("ammo-efficiency", "S"), stat("zoom"), stat("damage"),
                       stat("slash", polarity="negative"))
        game.current = spliced
        game._apply(roller.resume(game.t))
        game.feed(screen("current", spliced))
        target = card(stat("ammo-efficiency", "S"), stat("multishot", "A"),
                      stat("fire-rate-attack-speed", "B"),
                      stat("impact", "B", polarity="negative"))
        step, kept_new = game.roll(target)
        self.assertTrue(kept_new)
        self.assertEqual(step.event, "done")
        self.assertEqual(roller.phase, "done")

    def test_locked_ingredient_missing_stops(self):
        roller = self.roller(startStage="partner")
        game = Game(roller, card(stat("magazine-capacity", "S"), stat("damage"),
                                 stat("zoom"), stat("puncture", polarity="negative")))
        game.start()
        self.assertEqual(roller.stage, "partner")
        game.roll(self.junk())
        self.assertEqual(roller.phase, "stopped")
        self.assertIn("locked", roller.message)

    def test_both_ingredients_at_once_skips_lock(self):
        roller = self.roller()
        game = Game(roller, self.junk())
        game.start()
        step, kept_new = game.roll(card(stat("weapon-recoil", "C", polarity="negative"),
                                        stat("ammo-maximum", "S"), stat("damage"),
                                        stat("zoom")))
        self.assertTrue(kept_new)
        self.assertEqual(step.event, "paused")
        self.assertIn("Splice", step.message)

    def test_manual_lock_stage_uses_lock_grade(self):
        prefs = plan(lock="positive:multishot", positiveLockSlot=0, lockGrade="A")
        roller = self.roller(prefs)
        spliced = card(stat("ammo-efficiency", "S"), stat("zoom"), stat("damage"),
                       stat("slash", polarity="negative"))
        game = Game(roller, spliced)
        game.start()
        self.assertEqual(roller.stage, "lock")
        _, kept_new = game.roll(card(stat("ammo-efficiency", "S"), stat("multishot", "B"),
                                     stat("zoom"), stat("slash", polarity="negative")))
        self.assertFalse(kept_new)
        step, kept_new = game.roll(card(stat("ammo-efficiency", "S"),
                                        stat("multishot", "A+"), stat("zoom"),
                                        stat("slash", polarity="negative")))
        self.assertTrue(kept_new)
        self.assertEqual(step.event, "paused")
        self.assertEqual(roller.stage, "final")

    def test_final_grade_minimum(self):
        roller = self.roller(startStage="final", finalGrade="A")
        current = card(stat("ammo-efficiency", "S"), stat("zoom"), stat("damage"),
                       stat("slash", polarity="negative"))
        game = Game(roller, current)
        game.start()
        weak = card(stat("ammo-efficiency", "S"), stat("multishot", "B"),
                    stat("fire-rate-attack-speed", "A"), stat("impact", polarity="negative"))
        _, kept_new = game.roll(weak)
        self.assertFalse(kept_new)
        self.assertTrue(roller.active)

    def test_safety_stops(self):
        # OCR warning on the new roll.
        roller = self.roller()
        game = Game(roller, self.junk())
        game.start()
        game.feed(screen("transition", game.current))
        for _ in range(250):  # waits for a clean read, then gives up
            step = game.feed(screen("comparison", game.current,
                                    newRollWarning={"id": "1", "message": "x"}))
            if step.event:
                break
        self.assertEqual(step.event, "stopped")
        self.assertIn("OCR", step.message)
        self.assertEqual(game.pressed, [("cross",), ("cross",)])
        # No dialog after Cycle.
        roller = self.roller()
        game = Game(roller, self.junk())
        game.start()
        for _ in range(60):
            step = game.feed(screen("current", game.current))
            if step.event:
                break
        self.assertEqual(step.event, "stopped")
        # Kept card never settles (e.g. wrong card selected).
        roller = self.roller()
        game = Game(roller, self.junk())
        game.start()
        game.feed(screen("transition", game.current))
        new = card(stat("damage", "C"), stat("zoom"), stat("slash"),
                   stat("puncture", polarity="negative"))
        game.feed(screen("comparison", game.current, new))
        game.feed(screen("comparison", game.current, new))
        for _ in range(80):
            step = game.feed(screen("current", new))  # roller kept old; new shows
            if step.event:
                break
        self.assertEqual(step.event, "stopped")
        # Wrong weapon.
        roller = self.roller()
        game = Game(roller, card(stat("damage"), stat("zoom"), weapon="Sobek", fmt="2p0n"))
        step = game.start()
        self.assertEqual(step.event, "stopped")
        self.assertIn("Boar", step.message)

    def test_roll_limit(self):
        roller = self.roller(maxRolls=2)
        game = Game(roller, self.junk())
        game.start()
        game.roll(card(stat("damage", "C"), stat("zoom"), stat("slash"),
                       stat("slash", polarity="negative")))
        other = card(stat("damage", "A"), stat("zoom"), stat("slash"),
                     stat("puncture", polarity="negative"))
        step, _ = game.roll(other)
        self.assertEqual(step.event, "stopped")
        self.assertIn("2-roll limit", step.message)


if __name__ == "__main__":
    unittest.main()
