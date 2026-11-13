# Copyright (C) 2026 RivenRoller contributors; based on RivenLens
# (C) 2026 remesis and RivenLens contributors.
# SPDX-License-Identifier: GPL-3.0-only

"""Staged auto-rolling driven only by verified capture-worker states.

The roller never guesses. Each controller input is sent only after the screen
it belongs to has been confirmed, and anything unexpected (an OCR warning, an
ungradable stat, a missing held stat, a timeout, a lost focus) stops the run
instead of retrying. Manual steps (locking a stat, splicing) pause the run for
the user and are checked against the card on Resume.

This module has no Qt or controller dependency so it can be tested headless.
"""

import copy
from dataclasses import dataclass

from alerts import final_target_matches, meets_grade
from catalog import recipes, spliced_trait
from grading import FORMATS, GRADE_NAMES, grade_stat, grading_rank
from planner import Planner
from tracker import key

STAGES = ("auto", "ingredient", "partner", "lock", "final")
STAGE_LABELS = {
    "auto": "Auto (from plan and card)",
    "ingredient": "Find a splice ingredient",
    "partner": "Find the splice partner",
    "lock": "Find the manual lock stat",
    "final": "Find the final target",
}
BUTTONS = ("cross", "circle", "square", "triangle", "l1", "r1")
DEFAULTS = {
    "bindings": {
        # DualShock layout. Cycle assumes the cursor rests on the Cycle button.
        "cycle": ["cross"],
        "confirmYes": ["cross"],
        "keepOld": ["l1", "cross"],
        "keepNew": ["r1", "cross"],
    },
    "maxRolls": 50,
    "finalGrade": "F",
    "startStage": "auto",
    # Off (default): a wanted roll pauses on the comparison screen and you pick
    # the new card yourself, so a missed button press can never discard it.
    "autoKeepNew": False,
    "open": True,
}
TIMEOUTS = {
    "dialog": 4.0,  # Cycle press -> YES/NO dialog
    "roll": 20.0,  # YES press -> verified new card on the comparison screen
    "settle": 6.0,  # keep press -> verified kept card on the Cycle screen
    "start": 6.0,  # start/resume -> verified card on the Cycle screen
    "focus": 20.0,  # start/resume -> you clicking back into Warframe
}
# After you switch back into Warframe, time to put the pointer on Cycle.
AIM_SECONDS = 3.0
# A press can be ignored: Warframe uses the first controller press after mouse
# use just to switch to controller mode, and occasionally drops one right after
# a screen change. If a press visibly did nothing, repeat it (twice at most).
WAKE_RETRY_SECONDS = 1.2
KEEP_RETRY_SECONDS = 2.5
PRESS_RETRIES = 2
STABLE_READS = 2  # Fresh, identical worker states before a decision or press.


def roller_settings(saved):
    """Sanitize saved roller settings; unknown or malformed values use defaults."""
    saved = saved if isinstance(saved, dict) else {}
    result = copy.deepcopy(DEFAULTS)
    bindings = saved.get("bindings")
    if isinstance(bindings, dict):
        for action in result["bindings"]:
            value = bindings.get(action)
            if (
                isinstance(value, list)
                and 1 <= len(value) <= 4
                and all(b in BUTTONS for b in value)
            ):
                result["bindings"][action] = list(value)
    rolls = saved.get("maxRolls")
    if type(rolls) is int and 1 <= rolls <= 10000:
        result["maxRolls"] = rolls
    if saved.get("finalGrade") in GRADE_NAMES:
        result["finalGrade"] = saved["finalGrade"]
    if saved.get("startStage") in STAGES:
        result["startStage"] = saved["startStage"]
    for flag in ("open", "autoKeepNew"):
        if type(saved.get(flag)) is bool:
            result[flag] = saved[flag]
    return result


@dataclass
class Step:
    """One roller decision: buttons to send and/or a user-facing event."""

    buttons: tuple = ()
    event: str | None = None  # "paused", "done" or "stopped"
    message: str = ""


class Roller:
    IDLE, PAUSED, DONE, STOPPED = "idle", "paused", "done", "stopped"

    def __init__(self, catalog, preferences, settings):
        self.catalog = catalog
        self.preferences = preferences
        self.settings = roller_settings(settings)
        self.phase = self.IDLE
        self.message = "Auto roller idle."
        self.stage = None
        self.rolls = 0
        self.sending = False

    # ----------------------------------------------------------------- control

    @property
    def active(self):
        return self.phase not in (self.IDLE, self.PAUSED, self.DONE, self.STOPPED)

    def start(self, now):
        """Snapshot the planner, then wait for a verified Cycle screen."""
        self.prefs = copy.deepcopy(self.preferences)
        self.planner = Planner(self.catalog, self.prefs)
        self.weapon = self.planner.weapon
        self.splice = self.planner.splice
        self.lock = self.planner.lock_target
        if self.lock and self.lock["id"] == self.splice:
            self.lock = None
        traits = self.weapon["family"]["traits"]

        def rollable(identity):
            entry = traits.get(identity, {})
            return any(
                entry.get(sign, "excluded") != "excluded"
                for sign in ("positive", "negative")
            )

        self.pairs = [
            tuple(pair)
            for pair in (recipes(self.splice, self.weapon["kind"]) if self.splice else [])
            if all(rollable(i) for i in pair)
        ]
        if self.splice and not self.pairs:
            return self._stop(
                f"No rollable splice recipe for {self.name(self.splice)} on "
                f"{self.weapon['name']}."
            )
        self.ingredients = {i for pair in self.pairs for i in pair}
        baseline = spliced_trait(self.splice, self.weapon["kind"]) if self.splice else None
        # A spliced stat takes the higher ingredient grade, which the ingredient
        # stage already checked. Without a bundled baseline, rely on that.
        self.inferred_splice = bool(self.splice) and (
            not baseline or baseline.get("value") is None
        )
        self.locked_ingredient = None
        self.stage = None
        self.rolls = 0
        self.sending = False
        self.decision = ""
        self.warned = False
        self.focused = True
        self.after = None
        self.keep_confirmed, self.keep_retried, self.keep_action = False, 0, None
        self.settled, self.settled_key = 0, None
        self._enter("starting", now)
        self.message = "Open the Riven's Cycle screen in Warframe."
        if self.inferred_splice:
            self.message += (
                f" Note: no bundled baseline for {self.name(self.splice)}; its grade "
                "is taken from the ingredient you spliced."
            )
        return Step(message=self.message)

    def resume(self, now):
        if self.phase != self.PAUSED:
            return Step()
        self.settled, self.settled_key = 0, None
        self._enter("resuming", now)
        self.message = "Checking your card before resuming..."
        return Step(message=self.message)

    def stop(self, message="Stopped."):
        if self.phase in (self.IDLE, self.DONE, self.STOPPED):
            return Step()
        return self._stop(message)

    def sent(self, now):
        """The input thread finished pressing; waiting timers start from here."""
        self.sending = False
        self.since = now

    # --------------------------------------------------------------- the loop

    def step(self, state, now, focused=True):
        """Advance on one worker state. Call for every published state.

        focused: whether Warframe is the foreground window. Start and Resume
        wait for it, since clicking the button focuses RivenRoller itself.
        """
        if not self.active or self.sending:
            return Step()
        self.focused = focused
        if state.get("error"):
            return self._stop("Capture error: " + str(state["error"]))
        if state.get("newRollWarning"):
            # RivenLens raises this after about a second of unclear reads. Most
            # cards clear up a few seconds later, so keep waiting for two
            # agreeing complete reads; nothing is decided until then.
            self.warned = True
        mode = state.get("mode")
        if mode in ("hover", "inspection"):
            return self._stop("Left the Riven cycle screen.")
        cards = {card.get("slot"): card for card in state.get("cards", [])}
        handler = getattr(self, "_on_" + self.phase)
        return handler(mode, cards, now)

    def _on_starting(self, mode, cards, now):
        current = self._settled_current(mode, cards)
        if current is None and (mode == "comparison" or "new" in cards):
            return self._stop(
                "Two cards are on screen. Choose one in-game first, then start "
                "from the Cycle screen."
            )
        if current is None:
            return self._timeout(now, "start", "No verified card on the Cycle screen.")
        graded = self._grade(current, strict=False)
        if graded is None:
            return self._stop(self._grade_problem(current))
        stage = self.settings["startStage"]
        confirm = None
        if stage == "auto":
            # Auto never assumes a stat is locked: when the card already holds
            # something the next stage depends on, pause for you to confirm.
            if self.splice and not self._has(graded, self.splice):
                pair = self._ready_pair(graded)
                found = self._best_ingredient(graded)
                if pair:
                    stage = self._after_splice()
                    confirm = (
                        f"Both ingredients are already on the card "
                        f"({self._pair_text(pair, graded)}). Splice "
                        f"{self.name(self.splice)}, then Resume."
                    )
                elif found:
                    stat, result = found
                    self.locked_ingredient = (stat["id"], stat["polarity"])
                    stage = "partner"
                    confirm = (
                        f"The card already has {self._signed(stat)} at "
                        f"{result['grade']}. Make sure it's locked, then Resume to "
                        "roll for its splice partner."
                    )
                else:
                    stage = "ingredient"
            elif self.lock and not self._has(
                graded, self.lock["id"], self.lock["polarity"], self.prefs["lockGrade"]
            ):
                stage = "lock"
            else:
                stage = "final"
                if self.lock:
                    confirm = (
                        f"The card already has {self._signed(self.lock)}. Make sure "
                        "it's locked, then Resume to roll for the final target."
                    )
        if stage in ("ingredient", "partner") and not self.splice:
            return self._stop("The plan has no splice; pick a later start stage.")
        if stage == "lock" and not self.lock:
            return self._stop("The plan has no manual lock; pick another start stage.")
        if stage == "lock" and not self.planner.is_rollable(
            self.lock["id"], self.lock["polarity"]
        ):
            return self._stop(
                f"{self._signed(self.lock)} can't roll on {self.weapon['name']}, "
                "so the roller can't find it."
            )
        if stage == "partner" and self.locked_ingredient is None:
            held = [
                (stat, grade)
                for stat, grade in graded
                if stat["id"] in self.ingredients
                and self._completable(stat["id"], stat["polarity"])
            ]
            if not held:
                return self._stop("No splice ingredient on the current card to pair.")
            held.sort(key=lambda sg: self._grade_index(sg[1]))
            stat = held[0][0]
            self.locked_ingredient = (stat["id"], stat["polarity"])
        self.stage = stage
        if confirm:
            return self._pause(confirm)
        problem = self._held_problem(graded)
        if problem:
            return self._stop(problem)
        if not self.focused:
            return self._await_focus(now, self._stop)
        if self._aiming(now):
            return Step(message=self.message)
        return self._cycle(current, now)

    def _on_resuming(self, mode, cards, now):
        current = self._settled_current(mode, cards)
        if current is None:
            if now - self.since > TIMEOUTS["start"]:
                return self._pause(
                    "Couldn't see a card on the Cycle screen. Finish in-game "
                    "(choose a card, lock or splice), then Resume."
                )
            return Step()
        graded = self._grade(current, strict=False)
        if graded is None:
            return self._pause(self._grade_problem(current) + " Then Resume.")
        problem = self._held_problem(graded)
        if problem:
            return self._pause(problem + " Fix it in-game, then Resume.")
        if not self.focused:
            return self._await_focus(now, self._pause)
        if self._aiming(now):
            return Step(message=self.message)
        return self._cycle(current, now)

    def _on_await_dialog(self, mode, cards, now):
        if mode == "transition":
            self.wake_retry = 0
            self._enter("await_roll", now)
            return self._press("confirmYes")
        if mode == "comparison":
            self.wake_retry = 0
            self._enter("await_roll", now)
            return self._on_await_roll(mode, cards, now)
        current = self._fresh_current(mode, cards)
        if (
            self.wake_retry
            and current is not None
            and key(current) == self.previous_key
            and now - self.since > WAKE_RETRY_SECONDS
        ):
            # Once per roll, and only while the unchanged Cycle screen is still
            # being read (so no dialog has opened).
            self.wake_retry -= 1
            self.message = "Cycle didn't register; pressing it again."
            return self._press("cycle")
        return self._timeout(
            now, "dialog", "The Cycle press didn't open the confirmation dialog."
        )

    def _on_await_roll(self, mode, cards, now):
        new = cards.get("new")
        if (
            mode in ("comparison", "unknown")
            and new
            and not new.get("snapshot")
            and new.get("complete") is True
        ):
            # The tracker had no new card when Cycle was pressed, so this is the
            # new roll even if it happens to display the same stats as before.
            #
            # RivenLens re-reads the dim left card only every 0.75 s. On the
            # frames in between it reads the new card alone, and with the
            # controller cursor on the Confirm label that frame has no screen
            # type. So count agreeing reads of the new card across both kinds of
            # frame, and require the comparison screen to have been seen once.
            identity = key(new)
            if identity != self.stable_key:
                self.stable, self.compared = 0, False
            self.stable += 1
            self.stable_key = identity
            if mode == "comparison":
                self.compared = True
            if self.stable >= STABLE_READS and self.compared:
                return self._decide(new, now)
        else:
            self.stable, self.stable_key, self.compared = 0, None, False
        return self._timeout(
            now,
            "roll",
            "OCR couldn't read the new roll cleanly. Check it yourself; the roller "
            "won't discard a roll it can't read."
            if self.warned
            else "No verified new roll appeared.",
        )

    def _on_await_current(self, mode, cards, now):
        if mode == "transition":
            # Some layouts ask "are you sure?" after a card is chosen. Answer it
            # once; the dialog can stay visible for a few frames afterwards.
            if not self.keep_confirmed:
                self.keep_confirmed = True
                return self._press("confirmYes")
            return self._timeout(now, "settle", "The keep dialog didn't close.")
        if (
            mode == "comparison"
            and not self.keep_confirmed
            and self.keep_retried < PRESS_RETRIES
            and self.keep_action == "keepOld"
            and now - self.since > KEEP_RETRY_SECONDS
        ):
            # Still on the comparison screen with no dialog. A real run showed
            # what happens here: the select press (L1) registers, the Confirm
            # right after it is dropped, and L1 is a toggle, so sending the whole
            # sequence again selects the NEW card. Repeat only the Confirm.
            self.keep_retried += 1
            self.sending = True
            return Step(
                buttons=tuple(self.settings["bindings"]["keepOld"][-1:]),
                message="Confirm didn't register; pressing it again.",
            )
        current = self._settled_current(mode, cards)
        if current is not None:
            if key(current) != self.expected_key:
                return self._stop(
                    "A different card was kept than intended (a missed button "
                    "press?). Check the keep bindings."
                )
            after, self.after = self.after, None
            if after and after[0] == "pause":
                return self._pause(after[1])
            if after and after[0] == "done":
                self.phase = self.DONE
                self.message = after[1]
                return Step(event="done", message=self.message)
            return self._cycle(current, now)
        return self._timeout(
            now, "settle", "The kept card didn't settle on the Cycle screen."
        )

    # ------------------------------------------------------------- decisions

    def _decide(self, new, now):
        graded = self._grade(new)
        if graded is None:
            return self._stop(self._grade_problem(new))
        problem = self._held_problem(graded)
        if problem:
            return self._stop(problem)
        stage = self.stage
        outcome = getattr(self, "_match_" + stage)(new, graded)
        # One line per decided roll for the run log: what was read and why.
        self.decision = "roll {} [{}] {} {}: {} -> {}".format(
            self.rolls,
            stage,
            new.get("title", "?"),
            new.get("format", "?"),
            ", ".join(
                "{} {}{} {}".format(
                    self._signed(stat),
                    stat["value"],
                    stat.get("unit", ""),
                    result.get("grade", "?"),
                )
                for stat, result in graded
            ),
            "WANTED" if outcome else "keep current",
        )
        if outcome is None:
            return self._keep("keepOld", self.previous_key, None, now)
        if self.settings["autoKeepNew"]:
            return self._keep("keepNew", key(new), outcome, now)
        # Safest path: never press anything on a wanted roll.
        message = "Keep the NEW roll yourself (right card). " + outcome[1]
        if outcome[0] == "done":
            self.phase, self.message = self.DONE, message
            return Step(event="done", message=message)
        return self._pause(message)

    def _match_ingredient(self, card, graded):
        grade = self.prefs["spliceGrade"]
        if self._has(graded, self.splice, "positive", grade):
            self.stage = self._after_splice()
            return (
                "pause",
                f"{self.name(self.splice)} rolled directly at {grade} or better. "
                "Lock it if you want to keep it, then Resume.",
            )
        pair = self._ready_pair(graded)
        if pair:
            self.stage = self._after_splice()
            return (
                "pause",
                f"Both ingredients rolled together ({self._pair_text(pair, graded)}). "
                f"Splice {self.name(self.splice)} now, then Resume.",
            )
        found = self._best_ingredient(graded)
        if not found:
            return None
        stat, result = found
        self.locked_ingredient = (stat["id"], stat["polarity"])
        self.stage = "partner"
        return (
            "pause",
            f"Found {self._signed(stat)} at {result['grade']}. "
            "Lock it, then Resume to roll for its splice partner.",
        )

    def _match_partner(self, card, graded):
        pair = self._ready_pair(graded, require=self.locked_ingredient[0])
        if not pair:
            return None
        self.stage = self._after_splice()
        return (
            "pause",
            f"Partner found ({self._pair_text(pair, graded)}). "
            f"Splice {self.name(self.splice)} now, then Resume.",
        )

    def _match_lock(self, card, graded):
        if card["format"] != self.prefs["format"]:
            return None
        found = self._has(
            graded, self.lock["id"], self.lock["polarity"], self.prefs["lockGrade"]
        )
        if not found:
            return None
        self.stage = "final"
        return (
            "pause",
            f"Found {self._signed(self.lock)} at {found[1]['grade']}. "
            "Lock it, then Resume to roll for the final target.",
        )

    def _match_final(self, card, graded):
        graded = self._held_adjusted(graded)
        grades = [result for _, result in graded]
        if not final_target_matches(card, grades, self.planner):
            return None
        minimum = self.settings["finalGrade"]
        held = {self.splice, self.lock["id"] if self.lock else None}
        if not all(
            meets_grade(result, minimum)
            for stat, result in graded
            if stat["polarity"] == "positive" and stat["id"] not in held
        ):
            return None
        return ("done", f"Target roll found after {self.rolls} rolls. Roller stopped.")

    def _after_splice(self):
        return "lock" if self.lock else "final"

    def _completable(self, identity, polarity):
        """Can a partner still roll so that one of the pair is positive?"""
        traits = self.weapon["family"]["traits"]

        def can(other, sign):
            return traits.get(other, {}).get(sign, "excluded") != "excluded"

        for pair in self.pairs:
            if identity in pair:
                other = pair[0] if pair[1] == identity else pair[1]
                if can(other, "positive") or (
                    polarity == "positive" and can(other, "negative")
                ):
                    return True
        return False

    def _best_ingredient(self, graded):
        """Highest-graded ingredient at the splice grade that can be completed."""
        candidates = [
            (stat, result)
            for stat, result in graded
            if stat["id"] in self.ingredients
            and meets_grade(result, self.prefs["spliceGrade"])
            and self._completable(stat["id"], stat["polarity"])
        ]
        candidates.sort(key=lambda sg: self._grade_index(sg[1]))
        return candidates[0] if candidates else None

    def _signed(self, stat):
        sign = "−" if stat["polarity"] == "negative" else "+"
        return sign + self.name(stat["id"])

    def _ready_pair(self, graded, require=None):
        """Both ingredients present, one positive, and one at the splice grade.

        The spliced stat takes the higher ingredient grade, so the partner can be
        any grade (S + F splices to S).
        """
        present = {stat["id"]: (stat, result) for stat, result in graded}
        for pair in self.pairs:
            if require and require not in pair:
                continue
            if not all(i in present for i in pair):
                continue
            if not any(present[i][0]["polarity"] == "positive" for i in pair):
                continue
            if any(meets_grade(present[i][1], self.prefs["spliceGrade"]) for i in pair):
                return pair
        return None

    def _held_problem(self, graded):
        """Stats that must survive every roll of this stage (locks, splices)."""
        if self.stage == "partner":
            identity, polarity = self.locked_ingredient
            if not self._has(graded, identity, polarity):
                return (
                    f"{self.name(identity)} isn't on the card. Is it locked?"
                )
        if self.stage in ("lock", "final") and self.splice:
            if not self._has(graded, self.splice, "positive"):
                return f"{self.name(self.splice)} isn't on the card. Was it spliced?"
        if self.stage == "final" and self.lock:
            if not self._has(
                graded,
                self.lock["id"],
                self.lock["polarity"],
                self.prefs["lockGrade"],
                held=True,
            ):
                return (
                    f"{self.name(self.lock['id'])} at {self.prefs['lockGrade']} or "
                    "better isn't on the card. Is it locked?"
                )
        return None

    # ----------------------------------------------------------------- inputs

    def _cycle(self, current, now):
        if self.rolls >= self.settings["maxRolls"]:
            return self._stop(
                f"Reached the {self.settings['maxRolls']}-roll limit. Roller stopped."
            )
        self.rolls += 1
        self.previous_key = key(current)
        self.stable, self.stable_key, self.compared = 0, None, False
        self.wake_retry, self.warned = PRESS_RETRIES, False
        self._enter("await_dialog", now)
        self.message = f"Rolling ({STAGE_LABELS[self.stage].lower()}), roll {self.rolls}."
        return self._press("cycle")

    def _keep(self, action, expected, outcome, now):
        self.expected_key = expected
        self.after = outcome
        self.keep_confirmed, self.keep_retried, self.keep_action = False, 0, action
        self.settled, self.settled_key = 0, None
        self._enter("await_current", now)
        return self._press(action)

    def _press(self, action):
        self.sending = True
        return Step(
            buttons=tuple(self.settings["bindings"][action]), message=self.message
        )

    # ---------------------------------------------------------------- helpers

    def _enter(self, phase, now):
        self.phase, self.since = phase, now
        if phase in ("starting", "resuming"):
            self.waited_focus, self.focus_at = False, None
            self.wake_retry = PRESS_RETRIES

    def _aiming(self, now):
        """True while giving you time to aim after switching into Warframe."""
        if not self.waited_focus:
            return False  # started by hotkey from inside the game
        if self.focus_at is None:
            self.focus_at = now
            self.message = (
                f"Put the pointer on Cycle. Rolling in {AIM_SECONDS:.0f} seconds."
            )
        return now - self.focus_at < AIM_SECONDS

    def _await_focus(self, now, give_up):
        self.waited_focus, self.focus_at = True, None
        if now - self.since > TIMEOUTS["focus"]:
            return give_up("Warframe wasn't focused. Click into the game after "
                           "pressing Start or Resume.")
        if self.message != "Click into Warframe to begin.":
            self.message = "Click into Warframe to begin."
            return Step(message=self.message)
        return Step()

    def _timeout(self, now, kind, message):
        if now - self.since > TIMEOUTS[kind]:
            return self._stop(message)
        return Step()

    def _pause(self, message):
        self.phase, self.message = self.PAUSED, message
        return Step(event="paused", message=message)

    def _stop(self, message):
        self.phase, self.message, self.sending = self.STOPPED, message, False
        return Step(event="stopped", message=message)

    def _settled_current(self, mode, cards):
        """The Cycle-screen card after consecutive fresh, identical reads."""
        current = self._fresh_current(mode, cards)
        identity = key(current) if current else None
        self.settled = (
            self.settled + 1 if identity and identity == self.settled_key else
            (1 if identity else 0)
        )
        self.settled_key = identity
        return current if self.settled >= STABLE_READS else None

    @staticmethod
    def _fresh_current(mode, cards):
        current = cards.get("current")
        if (
            mode == "current"
            and "new" not in cards
            and current
            and not current.get("snapshot")
            and current.get("complete") is True
        ):
            return current
        return None

    def _grade(self, card, strict=True):
        """Stats with grades for the planned weapon, or None.

        Strict (every roll decision): every stat must grade. Lenient (start and
        resume, where only the presence of held stats matters): a stat that
        can't be graded is kept without a grade, e.g. right after a splice.
        """
        rank = grading_rank(card, self.prefs)
        group = self.catalog.group(card)
        variant = self.catalog.variant(card, self.prefs["gradeVariants"], rank=rank)
        if (
            not group
            or self.weapon["id"] not in group["memberIds"]
            or (variant and variant["kind"] != self.weapon["kind"])
        ):
            return None
        gradable = rank is not None and variant and card.get("format") in FORMATS
        if not gradable and strict:
            return None
        graded = []
        for stat in card["stats"]:
            if self.inferred_splice and stat["id"] == self.splice:
                result = {"grade": self.prefs["spliceGrade"], "inferred": True}
            elif not gradable:
                result = {"unknown": True}
            else:
                try:
                    result = grade_stat(
                        stat,
                        self.catalog.trait(variant, stat["id"]),
                        variant["disposition"],
                        card["format"],
                        self.catalog.range_model,
                        rank,
                    )
                except (ValueError, KeyError, TypeError):
                    result = {"unknown": True}
            graded.append((stat, result))
        if strict and any(r.get("grade") not in GRADE_NAMES for _, r in graded):
            return None
        return graded

    def _grade_problem(self, card):
        group = self.catalog.group(card)
        if not group or self.weapon["id"] not in group["memberIds"]:
            return (
                f"This Riven isn't for {self.weapon['name']}. "
                "Select the right weapon in the planner."
            )
        return (
            "A stat couldn't be graded (unreadable rank or variant, or a value "
            "outside its range). Check the card; nothing was discarded."
        )

    @staticmethod
    def _has(graded, identity, polarity=None, minimum=None, held=False):
        for stat, result in graded:
            if stat["id"] == identity and polarity in (None, stat["polarity"]):
                if (
                    minimum is None
                    or result.get("unknown")
                    or meets_grade(result, minimum)
                    or (held and Roller._within_one(result, minimum))
                ):
                    return stat, result
        return None

    @staticmethod
    def _within_one(result, minimum):
        """A held stat on a grade boundary can display one grade lower when the
        card's layout changes (rounding). Its grade was verified when found."""
        grade = result.get("grade")
        return (
            grade in GRADE_NAMES
            and GRADE_NAMES.index(grade) <= GRADE_NAMES.index(minimum) + 1
        )

    def _held_adjusted(self, graded):
        """Grades for the final check, with boundary tolerance for held stats."""
        adjusted = []
        for stat, result in graded:
            minimum = None
            if self.lock == {"id": stat["id"], "polarity": stat["polarity"]}:
                minimum = self.prefs["lockGrade"]
            elif stat["id"] == self.splice:
                minimum = self.prefs["spliceGrade"]
            if (
                minimum
                and not meets_grade(result, minimum)
                and self._within_one(result, minimum)
            ):
                result = {**result, "grade": minimum, "boundary": True}
            adjusted.append((stat, result))
        return adjusted

    @staticmethod
    def _grade_index(result):
        grade = result.get("grade")
        return GRADE_NAMES.index(grade) if grade in GRADE_NAMES else len(GRADE_NAMES)

    def _pair_text(self, pair, graded):
        present = {stat["id"]: (stat, result) for stat, result in graded}
        return " + ".join(
            f"{self.name(i)} {present[i][1].get('grade', '?')}" for i in pair
        )

    def name(self, identity):
        return self.planner.name(identity)
