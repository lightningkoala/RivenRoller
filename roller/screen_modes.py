# Copyright (C) 2026 RivenRoller contributors.
# SPDX-License-Identifier: GPL-3.0-only

"""Screen recognition that also works with controller prompts.

RivenLens recognises the rolling screens from mouse-and-keyboard labels. With a
controller, Warframe draws a button glyph beside YES/NO (read as "X YES"), and
the controller cursor sits on top of the Cycle/Confirm label. These rules add
controller-safe cues and otherwise defer to RivenLens' own detection.

Installed by replacing reader.mode_from_lines at startup; the engine folder is
not edited.
"""

import re

from parser import clean_text

# An optional misread glyph (one character) before the word.
YES = re.compile(r"^\W*(?:[A-Z0-9]{1,2}\W+|[XO0Q@]\W*)?YES\W*$")
NO = re.compile(r"^\W*(?:[A-Z0-9]{1,2}\W+|[XO0Q@C]\W*)?NO\W*$")
# Both buttons read as one line.
YES_NO = re.compile(r"^.{0,6}\bYES\b.{0,12}\bNO\W*$")
DIALOG = re.compile(r"ARE YOU SURE YOU WANT TO CYCLE|INTO CURRENT SELECTION")
CYCLE = re.compile(r"\bCYCLE\s+FOR\b|\bREMAINING\s*KUVA\b")
# The controller cursor sits on the middle of the label, so OCR often reads
# only its start: "CON", "CONF", "CONFI".
CONFIRM = re.compile(r"^\W*CON(?:F(?:I(?:R(?:M)?)?)?)?\W*$")


def _same_row(first, second):
    if not all(key in line for line in (first, second) for key in ("y", "h")):
        return True
    return abs(first["y"] - second["y"]) <= max(first["h"], second["h"])


# Short on-screen lines from the latest frame, for the roller's run log only.
last_texts = []


def install():
    import reader

    original = reader.mode_from_lines

    def mode_from_lines(lines):
        texts = [(clean_text(line["text"]).upper().strip(), line) for line in lines]
        last_texts[:] = [text for text, _ in texts if len(text) <= 32][:30]
        yes = [line for text, line in texts if YES.match(text)]
        no = [line for text, line in texts if NO.match(text)]
        if any(_same_row(a, b) for a in yes for b in no):
            return "transition"
        if any(YES_NO.match(text) for text, _ in texts):
            return "transition"
        if any(DIALOG.search(text) for text, _ in texts):
            return "transition"
        if any(CYCLE.search(text) for text, _ in texts):
            return "current"
        if any(CONFIRM.match(text) for text, _ in texts):
            return "comparison"
        return original(lines)

    reader.mode_from_lines = mode_from_lines
    return mode_from_lines
