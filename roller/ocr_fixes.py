# Copyright (C) 2026 RivenRoller contributors.
# SPDX-License-Identifier: GPL-3.0-only

"""One narrow correction to OCR text before RivenLens parses it.

Windows OCR reads a whole-second Combo Duration such as "+10s" as "+1 OS":
the zero becomes the letter O. RivenLens then can't parse the line, and the
card never completes. Only that confusion is corrected, only on Combo Duration
lines, and RivenLens' own range and repeat-read checks still apply afterwards.

Installed by wrapping the engine's recognizer factory; engine files are not
edited.
"""

import re

LINE = re.compile(r"COMBO\s+DURATION", re.I)
# A letter O directly after a digit and directly before the seconds unit.
ZERO = re.compile(r"(?<=\d)\s?[Oo]\s?(?=[sS](?:\s|$))")


def fix_text(text):
    if not LINE.search(text):
        return text
    # "+1 OS" -> "+10S": RivenLens rejects a number with a space inside it.
    return ZERO.sub("0", text)


def fix_lines(lines):
    for line in lines:
        text = line.get("text")
        if isinstance(text, str):
            fixed = fix_text(text)
            if fixed != text:
                line["text"] = fixed
    return lines


def install():
    import worker

    original = worker.LocalOCR

    def recognizer(language="en"):
        engine = original(language)
        read = engine.read

        async def corrected(image):
            return fix_lines(await read(image))

        engine.read = corrected
        return engine

    worker.LocalOCR = recognizer
