# RivenRoller

Auto-rolls Warframe Rivens toward a target. It's built on
[RivenLens](https://github.com/remesis/RivenLens), which grades rolls from
screen OCR, and adds a staged roller that presses buttons through a virtual
DualShock 4.

RivenRoller is **standalone**. It carries its own unmodified copy of the
RivenLens engine (`engine/`, see `engine/UPSTREAM.json`) and has its own Python
environment, settings folder and lock file. It never runs RivenLens' updater.
An installed RivenLens, and its settings, are not touched. On first launch
RivenRoller makes a one-time, read-only **copy** of your RivenLens preferences
so your plans carry over.


## Setup and use

See **[GUIDE.md](GUIDE.md)** for installation, the first-run check, a full
worked example and troubleshooting. In short (Windows): install 64-bit Python
3.13 or 3.14, double-click **Launch RivenRoller.cmd**, press **Start OCR**, set
the plan in the planner, open the Riven's Cycle screen, put the pointer on
**Cycle** and press **F8** (F9 stops).

## How a run works

The plan comes from the planner. It works for every weapon in the catalog and
every splice its type supports.

1. **Splice ingredient:** rolls until any ingredient of the planned splice
   reaches the splice grade, then pauses so you can keep and **lock** it. The
   spliced stat takes the higher ingredient grade (S + F splices to S).
2. **Splice partner:** rolls until the partner appears at any grade, then
   pauses so you can **splice**.
3. **Manual lock** (if planned): rolls until the lock stat appears at the lock
   grade or better, then pauses so you can lock it.
4. **Final:** rolls until the whole target matches, then stops.

Safety rules the roller follows:

- By default it **never presses anything on a roll you want**. It pauses on the
  comparison screen and you pick the card. (Automatic picking is optional.)
- It never assumes a stat is locked: starting with a useful stat already on
  the card pauses for you to confirm first, and every Resume re-reads the card.
- It stops, without choosing a card, on an OCR warning, an ungradable stat, a
  missing locked or spliced stat, the wrong weapon, a timeout (for example no
  Kuva), the roll limit, paused capture, or when Warframe isn't the focused
  window (checked before every button; alt-tab to stop).
- Timing is fixed and driven by the screen. Nothing is randomized or disguised.

## Layout

| Path | What |
|---|---|
| `engine/` | Unmodified RivenLens copy, with `MANIFEST.json` file hashes |
| `roller/main.py` | Entry point: own app identity and data folder, no updater |
| `roller/roller.py` | Staged roller state machine (no Qt or controller code) |
| `roller/gamepad.py` | Virtual DS4 output and the Warframe focus check |
| `roller/roller_window.py`, `roller_view.py` | RivenLens window subclass and panel |
| `roller/tracker_mode.py` | Tracker subclass that reports the current screen |
| `roller/settings.py` | `%LOCALAPPDATA%\RivenRoller` and `roller.json` |
| `tools/sync_engine.py` | Refresh `engine/` from a newer RivenLens |
| `tests/` | Headless tests: every weapon × splice, and full runs against a simulated game through RivenLens' real tracker |

## Updating the engine

```
python tools/sync_engine.py C:\path\to\RivenLens
python -m unittest discover -s tests
```

This reads the RivenLens folder (it must be a clean copy), replaces `engine/`
and rewrites the manifest. If upstream changed the tracker, worker or window,
the tests show what needs adjusting.

## License

GPL-3.0-only, the same as RivenLens, which it includes and modifies by
extension. See `LICENSE` and `engine/docs/THIRD_PARTY_NOTICES.md`. Not
affiliated with or endorsed by Digital Extremes or the RivenLens authors.
