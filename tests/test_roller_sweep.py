# Copyright (C) 2026 RivenRoller contributors.
# SPDX-License-Identifier: GPL-3.0-only
"""Every weapon x every splice it supports: full staged flow, headless."""

import copy
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "roller"), str(ROOT / "engine/native"), str(ROOT / "engine/app"), str(ROOT / "tests")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from catalog import SPLICE_IDS, recipes, splices_for  # noqa: E402
from grading import GRADES, trait_range  # noqa: E402
from planner import Planner  # noqa: E402
from preferences import DEFAULTS  # noqa: E402
from roller import Roller  # noqa: E402
from test_roller import CATALOG, Game, screen  # noqa: E402

MID = {name: (lo + hi) / 2 for name, lo, hi in GRADES}


class Weapon:
    def __init__(self, weapon):
        self.weapon = weapon
        self.name = weapon["variants"][0]["name"]
        self.variant = {**weapon["variants"][0]}
        self.traits = weapon["family"]["traits"]

    def allowed(self, identity, polarity):
        trait = CATALOG.trait(self.variant, identity)
        return (
            trait is not None
            and trait.get(polarity)
            and trait.get("value") is not None
            and self.traits.get(identity, {}).get(polarity) == "allowed"
        )

    def stat(self, identity, grade="B", polarity="positive", fmt="3p1n"):
        trait = CATALOG.trait(self.variant, identity)
        if trait.get("value") is None:  # no bundled baseline: any value
            return {"id": identity, "value": 12.3, "unit": trait["unit"],
                    "polarity": polarity}
        q = 1 + MID[grade] / 100
        value = trait_range(trait, self.variant["disposition"], fmt, polarity,
                            CATALOG.range_model, 8, [q, q])["low"]
        return {"id": identity, "value": value, "unit": trait["unit"],
                "polarity": polarity}

    def card(self, *stats, fmt="3p1n"):
        return {"weapon": self.name, "variantHint": self.name, "title": "Test",
                "format": fmt, "stats": list(stats), "complete": True,
                "rank": 8, "rankMode": "manual"}


def scenario(entry, splice):
    """Returns None on success, 'skip: ...' when not testable, or a failure."""
    w = Weapon(entry)
    kind = entry["kind"]
    pairs = [p for p in recipes(splice, kind)
             if any(w.allowed(p[0], s) for s in ("positive", "negative"))
             and any(w.allowed(p[1], s) for s in ("positive", "negative"))]
    if not pairs:
        return "skip: no rollable recipe"
    pair = pairs[0]
    first = pair[0] if w.allowed(pair[0], "positive") else pair[1]
    partner = pair[1] if first == pair[0] else pair[0]
    partner_sign = "positive" if w.allowed(partner, "positive") else "negative"
    used = set(pair) | {splice}
    positives = [t["id"] for t in CATALOG.definitions[kind]
                 if t["id"] not in used and w.allowed(t["id"], "positive")]
    negatives = [t["id"] for t in CATALOG.definitions[kind]
                 if t["id"] not in used and w.allowed(t["id"], "negative")]
    if len(positives) < 5 or len(negatives) < 2:
        return "skip: small pool"
    a, b, c, d, e = positives[:5]
    neg, neg2 = [n for n in negatives if n not in (a, b)][:2]
    prefs = copy.deepcopy(DEFAULTS)
    prefs.update(weapon=entry["id"], variant=w.variant["id"], format="3p1n",
                 positives=[splice, a, b], negative=neg, spliceGrade="S",
                 lockGrade="F")
    Planner(CATALOG, prefs)  # normalize as the app would
    if Planner(CATALOG, prefs).splice != splice:
        return "skip: planner rejects splice"
    roller = Roller(CATALOG, prefs, {"autoKeepNew": True})
    junk = w.card(w.stat(c), w.stat(d), w.stat(e), w.stat(neg2, polarity="negative"))
    game = Game(roller, junk)
    step = game.start()
    if roller.stage != "ingredient":
        return f"start: stage {roller.stage} {roller.message}"
    step, kept = game.roll(w.card(w.stat(first, "S"), w.stat(d), w.stat(e),
                                  w.stat(neg2, polarity="negative")))
    if not (kept and step.event == "paused" and roller.stage == "partner"):
        return f"ingredient: {step} stage={roller.stage}"
    game._apply(roller.resume(game.t))
    game.feed(screen("current", game.current))
    partner_stat = w.stat(partner, "F", partner_sign)
    step, kept = game.roll(w.card(w.stat(first, "S"), partner_stat, w.stat(e),
                                  w.stat(neg2, polarity="negative")
                                  if partner_sign == "positive"
                                  else w.stat(d)))
    if not (kept and step.event == "paused" and "Splice" in step.message):
        return f"partner: {step} stage={roller.stage}"
    spliced = w.card(w.stat(splice, "S"), w.stat(d), w.stat(e),
                     w.stat(neg2, polarity="negative"))
    game.current = spliced
    game._apply(roller.resume(game.t))
    game.feed(screen("current", spliced))
    if roller.phase != "await_dialog":
        return f"resume after splice: {roller.phase} {roller.message}"
    target = w.card(w.stat(splice, "S"), w.stat(a, "A"), w.stat(b, "B"),
                    w.stat(neg, "B", "negative"))
    step, kept = game.roll(target)
    if not (kept and step.event == "done"):
        return f"final: {step} {roller.message}"
    return None


class SweepTest(unittest.TestCase):
    def test_every_weapon_and_splice(self):
        failures, tested, skipped = [], 0, {}
        for entry in CATALOG.weapons:
            for row in splices_for(entry["kind"]):
                if row["id"] not in SPLICE_IDS:
                    continue
                result = scenario(entry, row["id"])
                if result is None:
                    tested += 1
                elif result.startswith("skip"):
                    skipped[result] = skipped.get(result, 0) + 1
                else:
                    failures.append((entry["id"], row["id"], result))
        print(f"\nsweep: {tested} flows passed, skipped {skipped}")
        self.assertFalse(failures, "\n".join(map(str, failures[:20])))
        self.assertGreater(tested, 1000)


if __name__ == "__main__":
    unittest.main()
