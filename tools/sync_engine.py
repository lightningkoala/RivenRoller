# Copyright (C) 2026 RivenRoller contributors.
# SPDX-License-Identifier: GPL-3.0-only
"""Refresh engine/ from a RivenLens checkout or extracted release, unmodified.

    python tools/sync_engine.py PATH_TO_RIVENLENS

Only reads PATH_TO_RIVENLENS. Replaces engine/ and writes MANIFEST.json (file
hashes) and UPSTREAM.json. Run the tests afterwards: upstream changes to the
tracker, worker or window may need the roller adjusted.
"""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engine"
COPY = ["app", "native", "LICENSE", "docs/THIRD_PARTY_NOTICES.md", "docs/licenses"]
SKIP_NAMES = {"__pycache__", "update-pending.json"}
SKIP_SUFFIXES = {".pyc"}


def files(base):
    for item in COPY:
        path = base / item
        if path.is_file():
            yield path
        elif path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and not (
                    SKIP_NAMES & set(child.relative_to(base).parts)
                    or child.suffix in SKIP_SUFFIXES
                ):
                    yield child


def write_manifest(base, upstream):
    manifest = {
        relative.as_posix(): hashlib.sha256((base / relative).read_bytes()).hexdigest()
        for relative in (p.relative_to(base) for p in files(base))
    }
    (base / "MANIFEST.json").write_text(
        json.dumps({"files": manifest}, indent=1, sort_keys=True) + "\n"
    )
    (base / "UPSTREAM.json").write_text(json.dumps(upstream, indent=2) + "\n")


def main(source):
    source = Path(source).resolve()
    if not (source / "native/data/release.json").is_file():
        raise SystemExit("Not a RivenLens folder: native/data/release.json is missing.")
    if source == ENGINE.resolve() or ENGINE.resolve() in source.parents:
        raise SystemExit("Point this at a RivenLens folder, not at engine/.")
    commit = None
    if (source / ".git").exists():
        result = subprocess.run(
            ["git", "-C", str(source), "status", "--porcelain", "--", *COPY],
            capture_output=True, text=True,
        )
        if result.stdout.strip():
            raise SystemExit("The RivenLens checkout has local changes; use a clean copy.")
        commit = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip() or None
    release = json.loads((source / "native/data/release.json").read_text())
    if ENGINE.exists():
        shutil.rmtree(ENGINE)
    for path in files(source):
        target = ENGINE / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    shutil.copy2(source / "requirements.txt", ROOT / "requirements.txt")
    write_manifest(
        ENGINE,
        {
            "repository": release.get("repository"),
            "commit": commit,
            "version": release.get("version"),
            "note": "Unmodified copy. Refresh with tools/sync_engine.py; never edit files here.",
        },
    )
    print(f"engine/ now matches RivenLens {release.get('version')} ({commit or 'no git'}).")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
