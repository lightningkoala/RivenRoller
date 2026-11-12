# Copyright (C) 2026 RivenRoller contributors.
# SPDX-License-Identifier: GPL-3.0-only

"""RivenRoller's own data folder and roller settings file.

Nothing here reads from or writes to RivenLens' data folder, except a one-time,
read-only copy of its preferences on first launch so your plans carry over.
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from roller import roller_settings


def _base():
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    configured = os.environ.get("XDG_DATA_HOME", "")
    return (
        Path(configured)
        if configured and Path(configured).is_absolute()
        else Path.home() / ".local/share"
    )


def data_directory():
    return _base() / "RivenRoller"


def rivenlens_directory():
    """RivenLens' own folder. Only ever read, never written."""
    if sys.platform == "win32":
        try:
            from instance import local_appdata

            return local_appdata() / "Arbitrations" / "RivenLens Native"
        except Exception:
            pass
    return _base() / "Arbitrations" / "RivenLens Native"


def import_rivenlens_preferences(directory):
    """Copy RivenLens' preferences once, if RivenRoller has none yet."""
    target = directory / "preferences.json"
    source = rivenlens_directory() / "preferences.json"
    if target.exists() or not source.is_file():
        return False
    directory.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(source, target)
    except OSError:
        return False
    return True


class RollerSettings:
    def __init__(self, directory):
        self.path = directory / "roller.json"
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        self.state = roller_settings(saved)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                json.dump(self.state, file, indent=2)
            os.replace(temporary, self.path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
