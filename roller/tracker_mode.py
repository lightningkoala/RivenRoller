# Copyright (C) 2026 RivenRoller contributors.
# SPDX-License-Identifier: GPL-3.0-only

"""RivenLens' tracker, plus the screen mode the roller needs.

Subclassed instead of edited, so the engine folder stays an exact upstream copy.
"""

from tracker import RollTracker


class ModeTracker(RollTracker):
    def update(self, result, now):
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
