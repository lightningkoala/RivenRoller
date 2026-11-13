# Copyright (C) 2026 RivenRoller contributors.
# SPDX-License-Identifier: GPL-3.0-only

"""Narrow corrections to OCR text before RivenLens parses it.

Windows OCR reads a whole-second Combo Duration such as "+10s" as "+1 OS":
the zero becomes the letter O. RivenLens then can't parse the line, and the
card never completes. It also garbles the "x" prefix of faction multipliers.
Only those letter-for-digit confusions are corrected, only on those lines; no
digit OCR did read is changed, and RivenLens' own range and repeat-read checks
still apply afterwards.

Installed by wrapping the engine's recognizer factory; engine files are not
edited.
"""

import re

LINE = re.compile(r"COMBO\s+DURATION", re.I)
# A letter O directly after a digit and directly before the seconds unit.
ZERO = re.compile(r"(?<=\d)\s?[Oo]\s?(?=[sS](?:\s|$))")


# Faction multipliers ("x1.49 Damage to Corpus", "x0.58 Damage to Infested").
# Windows OCR often reads the leading "x1" as "XL", "x0" as "XO", or drops the
# "x" before a 0.xx penalty. Each card then needs many re-reads to verify.
FACTION = re.compile(r"DAMAGE\s+TO\s+[A-Z]", re.I)
X_ONE = re.compile(r"[xX\u00d7]\s?[LlI|]\s?[.,]\s?(?=\d{1,2}\s+DAMAGE\b)", re.I)
X_ZERO = re.compile(r"[xX\u00d7]\s?[Oo]\s?[.,]\s?(?=\d{1,2}\s+DAMAGE\b)", re.I)
BARE_ZERO = re.compile(r"(?<![\d.,xX\u00d7+\-])0\s?[.,]\s?(?=\d{1,2}\s+DAMAGE\b)", re.I)


def fix_text(text):
    if LINE.search(text):
        # "+1 OS" -> "+10S": RivenLens rejects a number with a space inside it.
        return ZERO.sub("0", text)
    if FACTION.search(text):
        text = X_ONE.sub("x1.", text)
        text = X_ZERO.sub("x0.", text)
        text = BARE_ZERO.sub("x0.", text)
    return text


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
