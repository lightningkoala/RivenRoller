# Copyright (C) 2026 RivenRoller contributors.
# SPDX-License-Identifier: GPL-3.0-only
"""A fake Warframe Riven screen and player, for end-to-end roller scenarios.

SimGame produces the parsed frames RivenLens' reader would produce; they go
through RivenLens' real tracker (ModeTracker) before reaching the roller.
"""

import random

from grading import FORMATS, trait_range
from tracker_mode import ModeTracker

TICK = 0.1


class SimGame:
    def __init__(self, catalog, weapon, *, seed=1, confirm_cycle=True,
                 confirm_keep=True, kuva_rolls=10**9, default_cursor="new",
                 drop_presses=(), unreadable_frames=0, scripted=None,
                 mouse_mode=False, hidden_labels=False, skip_old_every=0):
        self.catalog, self.weapon = catalog, weapon
        self.variant = {**weapon["variants"][0]}
        self.name = self.variant["name"]
        self.rng = random.Random(seed)
        self.confirm_cycle, self.confirm_keep = confirm_cycle, confirm_keep
        self.kuva_rolls, self.default_cursor = kuva_rolls, default_cursor
        self.drop_presses = set(drop_presses)
        self.unreadable_frames = unreadable_frames  # per roll; -1 = forever
        self.scripted = list(scripted or [])
        traits = weapon["family"]["traits"]

        def pool(sign):
            return [
                t["id"] for t in catalog.definitions[weapon["kind"]]
                if traits.get(t["id"], {}).get(sign) == "allowed"
                and t.get(sign) and t.get("value") is not None
            ]

        self.pools = {"positive": pool("positive"), "negative": pool("negative")}
        self.locked = None      # (id, polarity, quality)
        self.spliced = None     # (id, quality)
        self.current = self.random_roll()
        self.new = None
        self.screen, self.wait, self.cursor = "cycle", 0, None
        self.presses, self.rolls, self.focused = [], 0, True
        self.unreadable_left = 0
        # After mouse use, the first controller press only switches input mode.
        self.mouse_mode = self.uses_mouse = mouse_mode
        # Controller cursor covers the Cycle/Confirm label (no screen type from
        # it), and the reader re-reads the dim old card only on some frames.
        self.hidden_labels, self.skip_old_every = hidden_labels, skip_old_every
        self.compare_frames = 0

    # ----------------------------------------------------------- cards

    def stat(self, identity, quality, polarity, fmt):
        trait = self.catalog.trait(self.variant, identity)
        if trait.get("value") is None or fmt not in FORMATS:
            value = 12.3
        else:
            q = 1 + quality / 100
            value = trait_range(trait, self.variant["disposition"], fmt, polarity,
                                self.catalog.range_model, 8, [q, q])["low"]
        return {"id": identity, "value": value, "unit": trait["unit"],
                "polarity": polarity, "_q": quality}

    def build(self, positives, negatives):
        """positives/negatives: lists of (id, quality)."""
        fmt = f"{len(positives)}p{len(negatives)}n"
        stats = [self.stat(i, q, "positive", fmt) for i, q in positives]
        stats += [self.stat(i, q, "negative", fmt) for i, q in negatives]
        return {"weapon": self.name, "title": self.name + " Sim", "format": fmt,
                "stats": stats, "complete": True, "rank": 8, "rankMode": "manual",
                "variantHint": None}

    def random_roll(self):
        positives, negatives = [], []
        if self.spliced:
            positives.append(self.spliced)
        if self.locked:
            (positives if self.locked[1] == "positive" else negatives).append(
                (self.locked[0], self.locked[2]))
        k = max(self.rng.choice((2, 3)), len(positives))
        has_negative = bool(negatives) or self.rng.random() < 0.5
        taken = {i for i, _ in positives + negatives}
        while len(positives) < k:
            identity = self.rng.choice(self.pools["positive"])
            if identity not in taken:
                taken.add(identity)
                positives.append((identity, self.rng.uniform(-10, 10)))
        while has_negative and not negatives:
            identity = self.rng.choice(self.pools["negative"])
            if identity not in taken:
                negatives.append((identity, self.rng.uniform(-10, 10)))
        return self.build(positives, negatives)

    def card(self, positives, negatives=()):
        """Scenario helper: explicit card from (id, quality) pairs."""
        return self.build(list(positives), list(negatives))

    # ---------------------------------------------------------- player

    def lock(self, identity, polarity):
        stat = next(s for s in self.current["stats"]
                    if s["id"] == identity and s["polarity"] == polarity)
        self.locked = (identity, polarity, stat["_q"])

    def splice(self, splice_id, pair):
        stats = {s["id"]: s for s in self.current["stats"]}
        quality = max(stats[i]["_q"] for i in pair)
        keep = [s for s in self.current["stats"] if s["id"] not in pair]
        self.spliced, self.locked = (splice_id, quality), None
        self.current = self.build(
            [(splice_id, quality)]
            + [(s["id"], s["_q"]) for s in keep if s["polarity"] == "positive"],
            [(s["id"], s["_q"]) for s in keep if s["polarity"] == "negative"])

    def player_keeps(self, which):
        assert self.screen == "compare"
        self.mouse_mode = self.uses_mouse
        self._kept(which)

    # ----------------------------------------------------------- input

    def press(self, button):
        index = len(self.presses)
        self.presses.append(button)
        if index in self.drop_presses or not self.focused:
            return
        if self.mouse_mode:
            self.mouse_mode = False
            return
        if self.screen == "cycle" and button == "cross":
            if self.kuva_rolls <= 0:
                self.screen = "no_kuva"
            elif self.confirm_cycle:
                self.screen = "cycle_dialog"
            else:
                self._roll()
        elif self.screen == "cycle_dialog" and button == "cross":
            self._roll()
        elif self.screen == "compare":
            if button == "l1":
                self.cursor = "old"
            elif button == "r1":
                self.cursor = "new"
            elif button == "cross":
                self.choice = self.cursor or self.default_cursor
                if self.confirm_keep:
                    self.screen = "keep_dialog"
                else:
                    self._kept(self.choice)
        elif self.screen == "keep_dialog" and button == "cross":
            self._kept(self.choice)

    def _roll(self):
        self.kuva_rolls -= 1
        self.rolls += 1
        self.new = self.scripted.pop(0) if self.scripted else self.random_roll()
        self.screen, self.wait, self.cursor = "rolling", 6, None
        self.unreadable_left = self.unreadable_frames

    def _kept(self, which):
        if which == "new":
            self.current = self.new
        self.new = None
        self.screen, self.wait = "settling", 3

    # ---------------------------------------------------------- frames

    def frame(self):
        def shown(card, x, complete=True):
            visible = {**card, "screenX": x, "complete": complete}
            visible["stats"] = [
                {k: v for k, v in s.items() if k != "_q"} for s in card["stats"]]
            return visible

        if self.screen in ("rolling", "settling"):
            self.wait -= 1
            if self.wait <= 0:
                self.screen = "compare" if self.screen == "rolling" else "cycle"
            return {"cards": [], "mode": "unknown"}
        if self.screen == "cycle":
            return {"cards": [shown(self.current, 0.5)], "mode": "current"}
        if self.screen == "cycle_dialog":
            return {"cards": [shown(self.current, 0.5, False)], "mode": "transition"}
        if self.screen == "no_kuva":
            return {"cards": [shown(self.current, 0.5, False)], "mode": "unknown"}
        if self.screen == "keep_dialog":
            return {"cards": [shown(self.current, 0.3, False),
                              shown(self.new, 0.7, False)], "mode": "transition"}
        readable = self.unreadable_left == 0
        if self.unreadable_left > 0:
            self.unreadable_left -= 1
        self.compare_frames += 1
        cards = [shown(self.current, 0.3), shown(self.new, 0.7, readable)]
        if self.skip_old_every and self.compare_frames % self.skip_old_every:
            cards = cards[1:]
        seen = "unknown" if self.hidden_labels else "comparison"
        return {"cards": cards, "mode": seen}


def play(game, roller, player=None, *, max_ticks=400_000, on_tick=None):
    """Run until the roller ends. player(event, message) may act and resume."""
    tracker = ModeTracker()
    now, events = 0.0, []

    def apply(step):
        for button in step.buttons:
            if not game.focused:
                apply(roller.stop("Warframe isn't the focused window."))
                return
            game.press(button)
        if step.buttons:
            roller.sent(now)
        if step.event:
            events.append((step.event, step.message))

    apply(roller.start(now))
    resume_at = None
    for tick in range(max_ticks):
        now += TICK
        if on_tick:
            on_tick(tick, game)
        state = {**tracker.update(game.frame(), now), "error": None}
        if roller.active:
            apply(roller.step(state, now, game.focused))
        if roller.phase == "paused" and resume_at is None:
            if player is None or not player("paused", roller.message):
                break
            resume_at = tick + 5  # the player takes a moment in-game
        if resume_at is not None and tick >= resume_at:
            resume_at = None
            apply(roller.resume(now))
        if roller.phase in ("done", "stopped"):
            if player:
                player(roller.phase, roller.message)
            break
    return events


def helpful_player(game, roller):
    """Does what each pause message asks: keep the new card, lock, splice."""
    def act(event, message):
        if game.screen == "compare":
            game.player_keeps("new")
        if event != "paused":
            return False
        if "Splice" in message and not game.spliced:
            present = {s["id"] for s in game.current["stats"]}
            pair = next(p for p in roller.pairs if set(p) <= present)
            game.splice(roller.splice, pair)
        elif roller.stage == "partner":
            game.lock(*roller.locked_ingredient)
        elif roller.stage == "final" and roller.lock:
            game.lock(roller.lock["id"], roller.lock["polarity"])
        return True
    return act
