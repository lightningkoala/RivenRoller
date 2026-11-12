# RivenRoller setup and usage guide

RivenRoller rolls a Warframe Riven for you until it finds the stats you asked
for. It reads the screen with RivenLens' OCR, presses buttons through a virtual
PlayStation controller, and pauses whenever you need to lock or splice a stat.

> **Before you start:** automated input breaks section 2.f of the Warframe
> EULA and can get your account banned. RivenRoller does nothing to hide what
> it is. Using it is your decision and your risk.

It has been tested against a simulated game, not against Warframe itself.
Follow [the first-run check](#5-first-run-check-do-this-once) before trusting it
with a Riven you care about.

---

## 1. What you need

- Windows 10 or 11, 64-bit.
- 64-bit **Python 3.13 or 3.14** from python.org. Keep "py launcher" ticked in
  the installer.
- Warframe in **windowed or borderless** mode, in a language RivenLens supports.
- An internet connection for the first launch (it downloads its dependencies).

Your existing RivenLens install isn't needed and isn't changed. RivenRoller has
its own copy of the RivenLens engine and keeps its settings in
`%LOCALAPPDATA%\RivenRoller`.

## 2. Install

1. Extract `RivenRoller.zip` to a folder you'll keep, for example
   `C:\Tools\RivenRoller`.
2. Double-click **Launch RivenRoller.cmd**.
3. The first launch takes a few minutes. It creates a private Python
   environment (`.venv` inside the folder) and installs the dependencies.
4. Partway through, a **ViGEmBus** installer opens and asks for administrator
   permission. This is the driver that creates the virtual controller. Accept
   it. If it asks to restart, restart and launch again.
5. The RivenRoller window opens. It looks like RivenLens with an extra
   **Auto roller** panel under the planner. If you have RivenLens installed,
   your plans and capture settings are copied over once.

If no window appears, run **Launch RivenRoller (show errors).cmd** and read
the message. See [Troubleshooting](#8-troubleshooting).

## 3. Set up the capture (once)

1. Pick the monitor Warframe is on from the dropdown at the top.
2. Choose your game language in the picker at the bottom.
3. Press **Start OCR**.
4. In Warframe, open a Riven's Cycle screen (the one with the **Cycle** button).
   Within a second or two the **CURRENT ROLL** card in RivenRoller should show
   the Riven's stats with grades. If it doesn't, the roller can't work; fix
   this first (keep the whole card, the "Fits In" label and the Cycle button
   visible, and make sure Warframe's "Show Ranked" is on).

## 4. Tell it what you want

Everything about the target is set in the **Target roll planner**, exactly as
in RivenLens:

| Planner setting | What the roller does with it |
|---|---|
| Weapon | Must match the Riven on screen, or the roller won't start |
| Format (2 or 3 positives, with/without negative) | The final roll must have this layout |
| Positive stats, negative stat | The final roll must have these. You can tick several acceptable stats per slot, or **Any** |
| A spliced stat among the positives (e.g. Ammo Efficiency, Viral) | Adds the two splice stages |
| **Splice grade** | The better ingredient must be this grade or higher (the spliced stat takes the higher ingredient's grade) |
| **Lock** on a stat, and **lock grade** | Adds the manual-lock stage: that stat at this grade or better |

The **Auto roller** panel adds:

| Setting | Meaning |
|---|---|
| **Start from** | Leave on *Auto*. It reads the card and picks the right stage. Choose a stage yourself only to override that |
| **Final positives** | Optional minimum grade for the *other* positives on the final roll (not the locked or spliced ones, which have their own grades) |
| **Stop after rolls** | Hard limit for one run. Start low |
| **Pick wanted rolls automatically** | Off by default. See [section 6](#6-the-two-ways-to-handle-a-wanted-roll) |
| **Bindings** | Which buttons to press for each action. See below |

### Button bindings

Buttons are typed in order, separated by spaces. Allowed names:
`cross circle square triangle l1 r1`.

| Action | Default | When it's pressed |
|---|---|---|
| Cycle | `cross` | On the Cycle screen. **The cursor must already be on the Cycle button** |
| Confirm Yes | `cross` | When a Yes/No dialog appears after Cycle, or after choosing a card |
| Keep current | `l1 cross` | The new roll isn't wanted: select the left card and confirm |
| Keep new | `r1 cross` | Only used if "Pick wanted rolls automatically" is on |

If your game needs a different sequence (for example an extra press to
confirm), change it here.

## 5. First-run check (do this once)

Use a Riven you don't care about.

1. Set **Stop after rolls** to **2**.
2. In Warframe, open the Riven's cycle screen. Using your real controller,
   move the cursor onto **Cycle**, then put the controller down.
3. In RivenRoller, press **Start rolling**, then click back into Warframe.
   The roller only presses buttons while Warframe is the focused window. It
   shows "Click into Warframe to begin" and waits up to 20 seconds for you.
4. Watch two rolls. Each should go: Cycle → Yes → new card appears →
   **left (old) card** selected → confirmed → back on the Cycle screen.
5. It should then stop with "Reached the 2-roll limit".

If it stops early, the status line says why:

| Message | Likely fix |
|---|---|
| "The Cycle press didn't open the confirmation dialog" | Cursor wasn't on Cycle, or Cross isn't the right button. Fix the *Cycle* binding |
| "No verified new roll appeared" | The Yes press didn't land. Fix *Confirm Yes* |
| "A different card was kept than intended" | L1 isn't selecting the left card. Fix *Keep current* |
| "Warframe isn't the focused window (focused: …)" | Click into Warframe after pressing Start |

Once two rolls go through cleanly, raise the limit.

## 6. The two ways to handle a wanted roll

**Default (recommended): you pick it.** When a roll you want appears, the
roller presses nothing. It plays the alert sound, leaves both cards on screen
and tells you to keep the new one. You select the new card yourself. A missed
or misread button press can never throw away a good roll.

**Automatic:** tick *Pick wanted rolls automatically* and it presses
*Keep new* for you. This saves one manual step per stage, but if that press is
dropped, the old card is kept and the roll is gone. The roller notices and
stops, but can't undo it. Only use this after the default mode has worked
reliably for you.

Either way, unwanted rolls are discarded automatically. That's the part that
saves the time.

## 7. A full run, step by step

Example: a Boar Riven with **Multishot, Fire Rate, Ammo Efficiency** and
**−Impact**, with Multishot locked.

Planner: weapon Boar; format 3 positives + negative; positives Multishot, Fire
Rate, Ammo Efficiency; negative Impact; lock on Multishot; pick your splice
grade and lock grade.

1. Open the cycle screen, cursor on Cycle. Press **Start rolling**, click into
   Warframe.
2. **It rolls for an ingredient.** Ammo Efficiency on a shotgun splices from
   Magazine Capacity + Reload Speed, or Weapon Recoil + Ammo Maximum. It rolls
   until any one of those appears at your splice grade.
   - *Pause:* "Keep the NEW roll yourself. Found +Magazine Capacity at S. Lock
     it, then Resume…"
   - **You:** select the new card, lock Magazine Capacity in-game, get back to
     the Cycle screen with the cursor on Cycle, press **Resume**, click into
     Warframe.
3. **It rolls for the partner** (Reload Speed here, any grade).
   - *Pause:* "Partner found (…). Splice Ammo Efficiency now, then Resume."
   - **You:** keep the new card, splice in-game, return to the Cycle screen,
     **Resume**.
4. **It rolls for the lock stat** (Multishot at your lock grade or better).
   - *Pause:* "Found +Multishot at A. Lock it, then Resume…"
   - **You:** keep the new card, lock Multishot, **Resume**.
5. **It rolls for the final target.** When the whole roll matches it stops:
   "Target roll found after N rolls." Keep the new card. Done.

Things that make it shorter:

- No splice in the plan: it skips steps 2–3.
- No lock in the plan: it skips step 4.
- Both ingredients land on the same roll: it skips straight to "splice now".
- You start with a useful stat already on the card: it pauses *before
  rolling* and asks you to make sure that stat is locked.

Every time you press **Resume**, it re-reads the card first. If the stat you
were meant to lock or splice isn't there, it tells you instead of rolling.
What it can't see is whether a stat is actually *locked*, only that it's on
the card. If you resume without locking, the stat disappears on the next roll
and the roller stops, but that stat is gone. Lock before you resume.

### Stopping it

- **Alt-tab** out of Warframe: it stops before the next button press.
- Press **Stop** in the panel.
- Press **Pause OCR**.

To continue after any stop, press **Start rolling** again. On *Auto* it works
out the stage from the card and asks you to confirm any stat that needs to be
locked.

### When it stops on its own

It stops and plays the warning sound, without choosing a card, when:

- OCR can't read the new roll, or a stat's value doesn't fit any grade. Look
  at the roll yourself.
- A stat that should be locked or spliced is missing from the new roll.
- The Riven on screen isn't for the planner's weapon.
- A screen doesn't appear in time (for example you're out of Kuva).
- The roll limit is reached.
- Warframe loses focus, or capture is paused.

## 8. Troubleshooting

**Nothing opens.** Run *Launch RivenRoller (show errors).cmd*. Errors from a
normal launch are also logged to
`%LOCALAPPDATA%\RivenRoller\logs\rivenroller.log`.

**"Install 64-bit Python…" / "Python 3.13 or 3.14 was not found".** Install
Python from python.org with the py launcher, then launch again.

**"Installing vgamepad failed" or "Couldn't create the virtual controller. Is
ViGEmBus installed?"** The driver didn't install. Install ViGEmBus from its
official GitHub releases page (nefarius/ViGEmBus), restart, then launch again.

**CURRENT ROLL stays empty.** This is the RivenLens side. Check the monitor
and language, keep the card unobstructed, try Settings → capture method, and
make sure the game isn't in exclusive fullscreen.

**Warframe ignores the presses.** Check Warframe's controller support is
enabled. Steam Input can also swallow or remap a virtual controller; try
disabling Steam Input for Warframe. Your real controller can stay connected,
but don't touch it during a run.

**"Warframe isn't the focused window" while it is.** The roller looks for a
window titled exactly `Warframe`; the message shows the title it saw. If yours
differs, change `GAME_TITLE` near the top of `roller\gamepad.py`.

**It keeps stopping with "No verified new roll appeared".** The roll animation
or OCR took longer than 12 seconds. Try the other capture method in Settings,
or raise `"roll"` in `TIMEOUTS` at the top of `roller\roller.py`.

**The roller refuses a splice: "No rollable splice recipe".** That weapon
can't roll one of the ingredients, so the splice isn't obtainable by rolling.

## 9. Updating and removing

- **New RivenLens release** (new weapons or stat data): download and extract
  it somewhere, then run
  `.venv\Scripts\python tools\sync_engine.py C:\path\to\RivenLens` followed by
  `.venv\Scripts\python -m unittest discover -s tests`. If the tests pass,
  you're up to date.
- **Remove RivenRoller:** delete its folder and `%LOCALAPPDATA%\RivenRoller`.
  ViGEmBus can be removed from Windows' installed apps list.
