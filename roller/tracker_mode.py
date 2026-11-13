# Copyright (C) 2026 RivenRoller contributors.
# SPDX-License-Identifier: GPL-3.0-only

"""RivenLens' tracker, plus the screen mode the roller needs.

Subclassed instead of edited, so the engine folder stays an exact upstream copy.
"""

from tracker import RollTracker


def _center(card):
    title = card.get("titleBounds") or card.get("bounds")
    if not title:
        return None, None
    return title["x"] + title["w"] / 2, max(title["w"], title["h"] * 8)


class ModeTracker(RollTracker):
    # RivenLens places cards relative to the Cycle/Confirm label. Remember where
    # that label's center was, for frames where the controller cursor hides it.
    anchor = None

    def _place(self, result):
        """Fill in card positions the reader couldn't derive (screenX == -1)."""
        cards = result.get("cards", [])
        if result.get("mode") in ("hover", "inspection") or not cards:
            return result
        for card in cards:
            center, width = _center(card)
            if center is not None and card.get("screenX", -1) >= 0:
                ModeTracker.anchor = center - (card["screenX"] - 0.5) * width * 6
        if all(card.get("screenX", 0) >= 0 for card in cards):
            return result
        placed = []
        ordered = sorted(
            range(len(cards)), key=lambda i: _center(cards[i])[0] or 0
        )
        for index, card in enumerate(cards):
            center, width = _center(card)
            if card.get("screenX", 0) >= 0 or center is None:
                placed.append(card)
            elif ModeTracker.anchor is not None:
                position = 0.5 + (center - ModeTracker.anchor) / (width * 6)
                placed.append({**card, "screenX": max(0.0, position)})
            elif len(cards) == 1:
                placed.append({**card, "screenX": 0.5})
            else:
                # No reference yet: left-to-right order is what assigns roles.
                rank = ordered.index(index)
                placed.append({**card, "screenX": 0.3 + 0.4 * rank / (len(cards) - 1)})
        return {**result, "cards": placed}

    def update(self, result, now):
        result = self._place(result)
        raw = result.get("cards", [])
        if (
            result.get("mode", "unknown") == "unknown"
            and self.view_mode != "hover"
            and len(raw) == 2
            and all(card.get("complete") for card in raw)
            and raw[0].get("weapon") == raw[1].get("weapon")
        ):
            # Two readable cards of one weapon side by side is the comparison
            # screen, even when the controller cursor covers its Confirm label.
            result = {**result, "mode": "comparison"}
        published = super().update(result, now)
        mode = result.get("mode", "unknown")
        if self.view_mode == "hover" and mode in ("hover", "unknown"):
            mode = "hover"
        published["mode"] = mode
        return published


def install():
    """Make the capture worker build ModeTracker in place of RollTracker."""
    import worker

    worker.RollTracker = ModeTracker
