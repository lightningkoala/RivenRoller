# Copyright (C) 2026 RivenRoller contributors.
# SPDX-License-Identifier: GPL-3.0-only
"""Usage scenarios: fake Warframe -> real RivenLens tracker -> roller."""

import copy
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "roller"), str(ROOT / "engine/native"),
                str(ROOT / "engine/app"), str(ROOT / "tests")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from catalog import Catalog  # noqa: E402
from preferences import DEFAULTS  # noqa: E402
from roller import Roller  # noqa: E402
from sim import SimGame, helpful_player, play  # noqa: E402

CATALOG = Catalog()


def weapon(name):
    return next(w for w in CATALOG.weapons if w["name"] == name)


def plan(name, positives, negative=None, *, lock="none", lock_slot=-1,
         splice_grade="A", lock_grade="B"):
    entry = weapon(name)
    prefs = copy.deepcopy(DEFAULTS)
    prefs.update(
        weapon=entry["id"], variant=entry["variants"][0]["id"],
        format=f"{len(positives)}p{1 if negative else 0}n",
        positives=list(positives), negative=negative or "any",
        lock=lock, positiveLockSlot=lock_slot,
        spliceGrade=splice_grade, lockGrade=lock_grade)
    return prefs


def ids(card, polarity):
    return {s["id"] for s in card["stats"] if s["polarity"] == polarity}


BOAR = dict(positives=["multishot", "fire-rate-attack-speed", "ammo-efficiency"],
            negative="impact", lock="positive:multishot", lock_slot=0)


class FullRuns(unittest.TestCase):
    """Random rolls until the target appears, with a player doing manual steps."""

    def run_plan(self, name, settings=None, seed=3, game_options=None, **plan_args):
        prefs = plan(name, **plan_args)
        game = SimGame(CATALOG, weapon(name), seed=seed, **(game_options or {}))
        roller = Roller(CATALOG, prefs, {"maxRolls": 10000, **(settings or {})})
        events = play(game, roller, helpful_player(game, roller))
        self.assertEqual(roller.phase, "done", roller.message)
        return game, roller, events, roller.prefs  # as normalized by the planner

    def assert_target(self, game, prefs):
        self.assertEqual(game.current["format"], prefs["format"])
        self.assertEqual(ids(game.current, "positive"), set(prefs["positives"]))
        if prefs["negative"] != "any":
            self.assertEqual(ids(game.current, "negative"), {prefs["negative"]})

    def test_boar_ammo_efficiency_player_picks_cards(self):
        game, roller, events, prefs = self.run_plan("Boar", **BOAR)
        self.assert_target(game, prefs)
        pauses = [m for e, m in events if e == "paused"]
        self.assertEqual(len(pauses), 3, pauses)  # lock ingredient, splice, lock
        self.assertIn("Lock it", pauses[0])
        self.assertIn("Splice Ammo Efficiency", pauses[1])
        self.assertIn("Multishot", pauses[2])
        self.assertNotIn("r1", game.presses)  # never picked a new card itself
        print(f"\n  Boar run: {game.rolls} rolls, {len(game.presses)} presses")

    def test_boar_automatic_card_pick_no_dialogs(self):
        game, roller, events, prefs = self.run_plan(
            "Boar", settings={"autoKeepNew": True}, seed=11,
            game_options=dict(confirm_cycle=False, confirm_keep=False), **BOAR)
        self.assert_target(game, prefs)
        self.assertEqual(game.presses.count("r1"), 4)  # 3 pauses + final

    def test_simple_target_never_discards_a_match(self):
        prefs = plan("Braton", ["multishot", "damage"])
        game = SimGame(CATALOG, weapon("Braton"), seed=5)
        seen = []
        original = game._roll

        def record():
            original()
            seen.append(game.new)
        game._roll = record
        roller = Roller(CATALOG, prefs, {"maxRolls": 10000})
        play(game, roller, helpful_player(game, roller))
        self.assertEqual(roller.phase, "done", roller.message)

        def wanted(card):
            return (card["format"] == "2p0n"
                    and ids(card, "positive") == {"multishot", "damage"})
        self.assertTrue(wanted(seen[-1]))
        self.assertFalse(any(wanted(card) for card in seen[:-1]))
        self.assertEqual(game.current, seen[-1])
        print(f"\n  Braton simple target: {game.rolls} rolls")

    def test_lock_only_plan(self):
        game, roller, events, prefs = self.run_plan(
            "Soma", positives=["critical-chance", "critical-damage"],
            lock="positive:critical-damage", lock_slot=1, lock_grade="A")
        self.assert_target(game, prefs)
        self.assertEqual(len([e for e, _ in events if e == "paused"]), 1)
        locked = next(s for s in game.current["stats"] if s["id"] == "critical-damage")
        self.assertGreaterEqual(locked["_q"], 3.4)  # A- boundary is 3.5

    def test_boundary_locked_stat_survives_layout_changes(self):
        # Seed 11 locks Multishot at -1.47% (B/B- line is -1.5%); in other
        # layouts rounding shows it as B-. The lock must still count as held.
        game, roller, events, prefs = self.run_plan(
            "Boar", settings={"autoKeepNew": True}, seed=11, **BOAR)
        self.assert_target(game, prefs)

    def test_melee_slam_damage_splice(self):
        game, roller, events, prefs = self.run_plan(
            "Nikana", positives=["slam-damage", "critical-damage"], seed=8)
        self.assert_target(game, prefs)

    def test_pistol_viral_splice_with_negative(self):
        game, roller, events, prefs = self.run_plan(
            "Lex", positives=["viral", "multishot"], negative="puncture", seed=2)
        self.assert_target(game, prefs)

    def test_archgun_splice_without_baseline(self):
        entry = next(w for w in CATALOG.weapons if w["kind"] == "Archgun")
        game, roller, events, prefs = self.run_plan(
            entry["name"], positives=["magazine-reload-while-holstered", "multishot"],
            seed=4)
        self.assert_target(game, prefs)


MIRE = dict(positives=["status-damage", "melee-damage", "critical-chance"],
            lock="positive:critical-chance", lock_slot=2)


class EitherLock(unittest.TestCase):
    """Mire: Status Damage + Melee Damage + Critical Chance, lock whichever
    of Melee Damage / Critical Chance rolls at the lock grade first."""

    def spliced(self, game):
        return game.card([("status-damage", 9.8), ("range", 0), ("puncture", 0)])

    def start(self, new_roll, **settings):
        prefs = plan("Mire", lock_grade="S", **MIRE)
        game = SimGame(CATALOG, weapon("Mire"), seed=1)
        game.current = self.spliced(game)
        game.spliced = ("status-damage", 9.8)
        game.scripted = [new_roll(game)]
        roller = Roller(CATALOG, prefs, {"maxRolls": 1, **settings})
        play(game, roller)
        return game, roller

    @staticmethod
    def melee_s(game):
        return game.card([("status-damage", 9.8), ("melee-damage", 9.8), ("range", 0)])

    @staticmethod
    def crit_s(game):
        return game.card([("status-damage", 9.8), ("critical-chance", 9.8), ("range", 0)])

    def test_planner_lock_only_by_default(self):
        game, roller = self.start(self.melee_s)
        self.assertIn("1-roll limit", roller.message)  # passed over
        game, roller = self.start(self.crit_s)
        self.assertEqual(roller.phase, "paused")
        self.assertIn("+Critical Chance", roller.message)

    def test_either_stat_pauses_when_enabled(self):
        for roll, name in ((self.melee_s, "+Melee Damage"), (self.crit_s, "+Critical Chance")):
            game, roller = self.start(roll, anyTargetLock=True)
            self.assertEqual(roller.phase, "paused", roller.message)
            self.assertIn(name, roller.message)
            self.assertEqual(roller.stage, "final")
            self.assertEqual(roller.planner.lock_target, roller.lock)

    def test_grade_still_applies(self):
        weak = lambda game: game.card(
            [("status-damage", 9.8), ("melee-damage", 5), ("critical-chance", 5)])
        game, roller = self.start(weak, anyTargetLock=True)
        self.assertIn("1-roll limit", roller.message)

    def test_full_runs_finish_with_whichever_was_locked(self):
        locked = set()
        for seed in range(6):
            prefs = plan("Mire", lock_grade="A", **MIRE)
            game = SimGame(CATALOG, weapon("Mire"), seed=seed, mouse_mode=True)
            roller = Roller(CATALOG, prefs, {"maxRolls": 10000, "anyTargetLock": True})
            play(game, roller, helpful_player(game, roller))
            self.assertEqual(roller.phase, "done", roller.message)
            self.assertEqual(ids(game.current, "positive"), set(prefs["positives"]))
            self.assertEqual(game.current["format"], "3p0n")
            locked.add(game.locked[0])
        self.assertEqual(locked, {"melee-damage", "critical-chance"})

    def test_locking_the_other_accepted_stat_is_fine(self):
        # Both roll at S; the roller names one, the player locks the other.
        both = lambda game: game.card(
            [("status-damage", 9.8), ("melee-damage", 9.9), ("critical-chance", 9.7)])
        prefs = plan("Mire", lock_grade="S", **MIRE)
        game = SimGame(CATALOG, weapon("Mire"), seed=2)
        game.current, game.spliced = self.spliced(game), ("status-damage", 9.8)
        game.scripted = [both(game)]
        roller = Roller(CATALOG, prefs, {"maxRolls": 10000, "anyTargetLock": True})

        def player(event, message):
            if game.screen == "compare":
                game.player_keeps("new")
            if event == "paused" and not game.locked:
                game.lock("critical-chance", "positive")
            return event == "paused"
        play(game, roller, player)
        self.assertEqual(roller.phase, "done", roller.message)
        self.assertEqual(roller.lock["id"], "critical-chance")


class ThingsGoingWrong(unittest.TestCase):
    def setup(self, settings=None, scripted=None, prefs=None, name="Boar", **options):
        prefs = prefs or plan(name, **BOAR)
        game = SimGame(CATALOG, weapon(name), seed=1, **options)
        junk = game.card([("damage", 0), ("zoom", 0), ("slash", 0)], [("puncture", 0)])
        game.current = junk
        game.scripted = [build(game) for build in (scripted or [])]
        return game, Roller(CATALOG, prefs, settings or {}), junk

    @staticmethod
    def junk2(game):
        return game.card([("damage", 5), ("puncture", 0)], [("zoom", 0)])

    @staticmethod
    def ingredient(game):
        return game.card([("reload-speed", 9), ("zoom", 0), ("slash", 0)],
                         [("puncture", 0)])

    def test_missed_press_keeps_wrong_card_and_stops(self):
        # Third press is L1 (cycle, yes, L1, cross): drop it.
        game, roller, junk = self.setup(scripted=[self.junk2], drop_presses={2})
        play(game, roller)
        self.assertEqual(roller.phase, "stopped")
        self.assertIn("different card", roller.message)
        self.assertEqual(game.rolls, 1)

    def test_ignored_presses_are_repeated_once(self):
        # Press order per roll: cycle, yes, l1, cross, yes. Drop a mid-run Cycle
        # (index 5) and, separately, the Confirm after L1 (index 3).
        # L1 toggles the selection, so the repeat after a dropped Confirm must be
        # the Confirm alone (a real run kept the wrong card otherwise).
        # Also the Yes on either dialog (indexes 1 and 4), as logged on a real run.
        for dropped, extra in ((5, 1), (3, 1), (1, 1), (4, 1), (6, 1)):
            game, roller, junk = self.setup(settings={"maxRolls": 3},
                                            drop_presses={dropped})
            play(game, roller)
            self.assertIn("3-roll limit", roller.message, dropped)
            self.assertEqual(game.rolls, 3)
            self.assertEqual(len(game.presses), 15 + extra)
            self.assertEqual(game.current, junk)  # every roll kept the old card

    def test_slow_ocr_on_new_roll_waits_instead_of_stopping(self):
        # Unreadable for 4 s: RivenLens' warning fires, then the card clears up.
        game, roller, junk = self.setup(settings={"maxRolls": 1},
                                        scripted=[self.junk2], unreadable_frames=40)
        play(game, roller)
        self.assertIn("1-roll limit", roller.message)
        self.assertEqual(game.current, junk)

    def test_started_on_the_comparison_screen(self):
        game, roller, junk = self.setup()
        game.new, game.screen = self.junk2(game), "compare"
        play(game, roller)
        self.assertEqual(roller.phase, "stopped")
        self.assertIn("Two cards are on screen", roller.message)
        self.assertEqual(game.presses, [])

    def test_out_of_kuva_stops(self):
        game, roller, junk = self.setup(kuva_rolls=0)
        play(game, roller)
        self.assertEqual(roller.phase, "stopped")
        self.assertIn("didn't open", roller.message)
        self.assertEqual(game.presses, ["cross"])

    def test_unreadable_new_roll_is_never_discarded(self):
        game, roller, junk = self.setup(scripted=[self.ingredient],
                                        unreadable_frames=-1)
        play(game, roller)
        self.assertEqual(roller.phase, "stopped")
        self.assertIn("OCR", roller.message)
        self.assertEqual(game.presses, ["cross", "cross"])  # cycle + yes only
        self.assertEqual(game.screen, "compare")  # both cards still on screen

    def test_briefly_unreadable_roll_recovers(self):
        game, roller, junk = self.setup(scripted=[self.ingredient],
                                        unreadable_frames=6)
        play(game, roller)
        self.assertEqual(roller.phase, "paused")
        self.assertIn("Reload Speed", roller.message)

    def test_wanted_roll_pauses_without_pressing(self):
        game, roller, junk = self.setup(scripted=[self.ingredient])
        play(game, roller)
        self.assertEqual(roller.phase, "paused")
        self.assertIn("Keep the NEW roll yourself", roller.message)
        self.assertEqual(game.presses, ["cross", "cross"])
        self.assertEqual(game.screen, "compare")

    def test_resume_before_finishing_in_game_waits(self):
        game, roller, junk = self.setup(scripted=[self.ingredient])
        pauses = []

        def impatient(event, message):  # resumes once without doing anything
            pauses.append(message)
            return len(pauses) == 1
        play(game, roller, impatient)
        self.assertEqual(roller.phase, "paused")
        self.assertIn("Finish in-game", roller.message)
        self.assertEqual(game.presses, ["cross", "cross"])

    def test_forgot_to_lock_stops_on_next_roll(self):
        game, roller, junk = self.setup(scripted=[self.ingredient, self.junk2])

        def forgetful(event, message):
            if game.screen == "compare" and event == "paused":
                game.player_keeps("new")  # keeps it but never locks
            return event == "paused"
        play(game, roller, forgetful)
        self.assertEqual(roller.phase, "stopped")
        self.assertIn("Is it locked?", roller.message)
        self.assertEqual(game.screen, "compare")  # nothing chosen for the player
        self.assertEqual(game.presses, ["cross"] * 4)

    def test_new_roll_identical_to_current_keeps_rolling(self):
        same = lambda game: game.card(
            [("damage", 0), ("zoom", 0), ("slash", 0)], [("puncture", 0)])
        game, roller, junk = self.setup(scripted=[same, self.junk2],
                                        settings={"maxRolls": 2})
        play(game, roller)
        self.assertIn("2-roll limit", roller.message)
        self.assertEqual(game.rolls, 2)

    def test_start_waits_for_you_to_click_into_warframe(self):
        game, roller, junk = self.setup(settings={"maxRolls": 1})
        game.focused = False

        first_press = []

        def click_in(tick, game):
            if tick == 50:  # five seconds after pressing Start
                game.focused = True
            if game.presses and not first_press:
                first_press.append(tick)
        play(game, roller, on_tick=click_in)
        # Three seconds to put the pointer on Cycle after switching back.
        self.assertGreaterEqual(first_press[0], 50 + 29)
        self.assertEqual(game.rolls, 1)
        self.assertIn("1-roll limit", roller.message)

    def test_hotkey_start_inside_warframe_presses_without_delay(self):
        game, roller, junk = self.setup(settings={"maxRolls": 1})
        first_press = []

        def watch(tick, game):
            if game.presses and not first_press:
                first_press.append(tick)
        play(game, roller, on_tick=watch)
        self.assertLessEqual(first_press[0], 4)

    def test_first_press_swallowed_by_mouse_to_controller_switch(self):
        game, roller, junk = self.setup(settings={"maxRolls": 3}, mouse_mode=True)
        play(game, roller)
        self.assertIn("3-roll limit", roller.message)
        self.assertEqual(game.rolls, 3)
        # One extra Cycle press at the start, none afterwards.
        self.assertEqual(game.presses[:3], ["cross", "cross", "cross"])
        self.assertEqual(len(game.presses), 1 + 3 * 5)

    def test_full_run_with_mouse_between_every_pause(self):
        prefs = plan("Boar", **BOAR)
        game = SimGame(CATALOG, weapon("Boar"), seed=3, mouse_mode=True)
        roller = Roller(CATALOG, prefs, {"maxRolls": 10000})
        play(game, roller, helpful_player(game, roller))
        self.assertEqual(roller.phase, "done", roller.message)
        self.assertEqual(ids(game.current, "positive"), set(roller.prefs["positives"]))

    def test_old_card_read_only_every_other_frame(self):
        # As logged on a real run: frames alternate between both cards and the
        # new card alone, and the hidden Confirm label gives no screen type.
        for every in (2, 3):
            game, roller, junk = self.setup(
                settings={"maxRolls": 3}, scripted=[self.junk2],
                hidden_labels=True, skip_old_every=every)
            play(game, roller)
            self.assertIn("3-roll limit", roller.message, every)
            self.assertEqual(game.rolls, 3)

    def test_dim_old_card_never_fully_read(self):
        # As logged: the old card stayed "waiting for a confirming read" and the
        # Confirm label was hidden, so no frame had two complete cards.
        game, roller, junk = self.setup(
            settings={"maxRolls": 3}, scripted=[self.junk2],
            hidden_labels=True, old_card_unreadable=True)
        play(game, roller)
        self.assertIn("3-roll limit", roller.message)
        self.assertEqual(game.rolls, 3)
        game, roller, junk = self.setup(scripted=[self.ingredient],
                                        hidden_labels=True, old_card_unreadable=True)
        play(game, roller)
        self.assertEqual(roller.phase, "paused")
        self.assertIn("Reload Speed", roller.message)

    def test_wanted_roll_found_with_alternating_frames(self):
        game, roller, junk = self.setup(scripted=[self.ingredient],
                                        hidden_labels=True, skip_old_every=2)
        play(game, roller)
        self.assertEqual(roller.phase, "paused")
        self.assertIn("Reload Speed", roller.message)

    def test_full_run_with_alternating_frames(self):
        prefs = plan("Boar", **BOAR)
        game = SimGame(CATALOG, weapon("Boar"), seed=3, mouse_mode=True,
                       hidden_labels=True, skip_old_every=2)
        roller = Roller(CATALOG, prefs, {"maxRolls": 10000})
        play(game, roller, helpful_player(game, roller))
        self.assertEqual(roller.phase, "done", roller.message)
        self.assertEqual(ids(game.current, "positive"), set(roller.prefs["positives"]))

    def test_start_gives_up_if_warframe_never_focused(self):
        game, roller, junk = self.setup()
        game.focused = False
        play(game, roller, max_ticks=600)
        self.assertEqual(roller.phase, "stopped")
        self.assertIn("Click into the game", roller.message)
        self.assertEqual(game.presses, [])

    def test_alt_tab_stops_immediately(self):
        game, roller, junk = self.setup()

        def leave(tick, game):
            if tick == 40:
                game.focused = False
        play(game, roller, on_tick=leave, max_ticks=400)
        self.assertEqual(roller.phase, "stopped")
        self.assertIn("focused", roller.message)

    def test_wrong_weapon_riven(self):
        game, roller, junk = self.setup()
        other = SimGame(CATALOG, weapon("Sobek"), seed=1)
        game.current = other.current
        play(game, roller)
        self.assertEqual(roller.phase, "stopped")
        self.assertIn("isn't for Boar", roller.message)
        self.assertEqual(game.presses, [])

    def test_roll_limit_is_exact(self):
        game, roller, junk = self.setup(settings={"maxRolls": 3})
        play(game, roller)
        self.assertEqual(roller.phase, "stopped")
        self.assertIn("3-roll limit", roller.message)
        self.assertEqual(game.rolls, 3)

    def test_start_with_ingredient_on_card_asks_before_rolling(self):
        game, roller, junk = self.setup()
        game.current = self.ingredient(game)
        play(game, roller)
        self.assertEqual(roller.phase, "paused")
        self.assertIn("Make sure it's locked", roller.message)
        self.assertEqual(game.presses, [])

    def test_start_with_lock_stat_on_card_asks_before_rolling(self):
        game, roller, junk = self.setup()
        game.current = game.card(
            [("ammo-efficiency", 8), ("multishot", 5), ("zoom", 0)], [("slash", 0)])
        play(game, roller)
        self.assertEqual(roller.phase, "paused")
        self.assertIn("+Multishot", roller.message)
        self.assertEqual(game.presses, [])

    def test_odd_layout_after_splice_can_resume(self):
        # Both ingredients on a 2-positive card splice into a 1-positive card.
        prefs = plan("Boar", ["ammo-efficiency", "multishot"])
        game, roller, junk = self.setup(prefs=prefs, settings={"maxRolls": 2})
        game.current = game.card([("reload-speed", 9), ("magazine-capacity", -9)])
        play(game, roller, helpful_player(game, roller))
        self.assertEqual(game.spliced[0], "ammo-efficiency")
        self.assertIn("2-roll limit", roller.message)  # it resumed and rolled
        self.assertIn("ammo-efficiency", ids(game.current, "positive"))

    def test_lock_stat_that_cannot_roll_stops_at_start(self):
        prefs = plan("Boar", ["multishot", "damage"], lock="positive:multishot",
                     lock_slot=0)
        game, roller, junk = self.setup(prefs=prefs)
        original = Roller.start

        def start(self, now):
            step = original(self, now)
            self.planner.is_rollable = lambda *_: False
            return step
        roller.start = start.__get__(roller)
        play(game, roller)
        self.assertEqual(roller.phase, "stopped")
        self.assertIn("can't roll", roller.message)
        self.assertEqual(game.presses, [])

    def test_ingredient_needing_an_impossible_partner_is_skipped(self):
        game, roller, junk = self.setup()
        roller.start(0)
        traits = copy.deepcopy(roller.weapon["family"]["traits"])
        traits["magazine-capacity"]["positive"] = "excluded"
        roller.weapon = {**roller.weapon, "family": {"traits": traits}}
        # -Reload Speed needs +Magazine Capacity, which can't roll here.
        self.assertFalse(roller._completable("reload-speed", "negative"))
        self.assertTrue(roller._completable("reload-speed", "positive"))
        self.assertTrue(roller._completable("ammo-maximum", "negative"))

if __name__ == "__main__":
    unittest.main()
