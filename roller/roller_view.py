# Copyright (C) 2026 RivenRoller contributors; based on RivenLens
# (C) 2026 remesis and RivenLens contributors.
# SPDX-License-Identifier: GPL-3.0-only

"""Auto roller controls. The plan itself comes from the Target roll planner."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QGridLayout, QLineEdit, QSpinBox

from grading import GRADE_NAMES
from roller import BUTTONS, STAGE_LABELS, STAGES, roller_settings
from ui_text import QPushButton
from widgets import Combo, Section, box, label, options

BINDING_LABELS = {
    "cycle": "Cycle",
    "confirmYes": "Confirm Yes",
    "keepOld": "Keep current",
    "keepNew": "Keep new",
}


class RollerView(Section):
    start_requested = Signal()
    resume_requested = Signal()
    stop_requested = Signal()
    changed = Signal()

    def __init__(self, store, parent=None):
        super().__init__("Auto roller", store.state["open"], parent)
        self.store = store
        settings = store.state
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        self.stage = Combo()
        options(self.stage, [(STAGE_LABELS[s], s) for s in STAGES], settings["startStage"])
        self.stage.activated.connect(self.save)
        self.final_grade = Combo()
        options(
            self.final_grade,
            [(f"{g} or better" if g != "F" else "Any grade", g) for g in GRADE_NAMES],
            settings["finalGrade"],
        )
        self.final_grade.activated.connect(self.save)
        self.max_rolls = QSpinBox()
        self.max_rolls.setRange(1, 10000)
        self.max_rolls.setValue(settings["maxRolls"])
        self.max_rolls.valueChanged.connect(self.save)
        rows = [
            ("Start from", self.stage),
            ("Final positives", self.final_grade),
            ("Stop after rolls", self.max_rolls),
        ]
        self.bindings = {}
        for action, text in BINDING_LABELS.items():
            edit = QLineEdit(" ".join(settings["bindings"][action]))
            edit.setToolTip("Buttons in order: " + ", ".join(BUTTONS))
            edit.editingFinished.connect(self.save)
            self.bindings[action] = edit
            rows.append((text, edit))
        for row, (text, widget) in enumerate(rows):
            grid.addWidget(label(text), row, 0)
            grid.addWidget(widget, row, 1)
        self.content.addLayout(grid)
        self.auto_keep = QCheckBox("Pick wanted rolls automatically (riskier)")
        self.auto_keep.setToolTip(
            "Off: when a wanted roll appears the roller pauses on the comparison "
            "screen and you pick the new card yourself. On: it presses 'Keep new' "
            "for you; a missed press could discard the roll."
        )
        self.auto_keep.setChecked(settings["autoKeepNew"])
        self.auto_keep.toggled.connect(self.save)
        self.content.addWidget(self.auto_keep)
        buttons, row = box(False, spacing=6)
        self.start = QPushButton("Start rolling")
        self.start.setObjectName("primary")
        self.resume = QPushButton("Resume")
        self.halt = QPushButton("Stop")
        self.start.clicked.connect(self.start_requested)
        self.resume.clicked.connect(self.resume_requested)
        self.halt.clicked.connect(self.stop_requested)
        for button in (self.start, self.resume, self.halt):
            row.addWidget(button)
        self.content.addWidget(buttons)
        self.status = label("Auto roller idle.", "status", wrap=True)
        self.content.addWidget(self.status)
        self.content.addWidget(
            label(
                "In Warframe, put the pointer on Cycle and press F8 to start or "
                "resume; F9 stops. "
                "Uses the planner's weapon, targets, splice and lock grades. "
                "Pauses for you to lock or splice. Alt-tab out of Warframe to "
                "stop instantly. Automated input breaks the Warframe EULA; "
                "use at your own risk.",
                "note",
                wrap=True,
            )
        )
        self.toggled.connect(self._remember_open)
        self.set_phase("idle")

    def _remember_open(self, opened):
        self.store.state["open"] = opened
        self.changed.emit()

    def save(self, *_):
        bindings = {}
        for action, edit in self.bindings.items():
            names = edit.text().lower().split()
            bindings[action] = names
        saved = roller_settings(
            {
                "bindings": bindings,
                "maxRolls": self.max_rolls.value(),
                "finalGrade": self.final_grade.currentData(),
                "startStage": self.stage.currentData(),
                "autoKeepNew": self.auto_keep.isChecked(),
                "open": self.opened,
            }
        )
        for action, edit in self.bindings.items():
            # Invalid entries fall back; show what will actually be pressed.
            edit.setText(" ".join(saved["bindings"][action]))
        self.store.state = saved
        self.changed.emit()

    def set_phase(self, phase, message=None):
        running = phase not in ("idle", "paused", "done", "stopped")
        self.start.setEnabled(phase in ("idle", "done", "stopped"))
        self.resume.setEnabled(phase == "paused")
        self.halt.setEnabled(running or phase == "paused")
        for widget in (
            self.stage,
            self.final_grade,
            self.max_rolls,
            self.auto_keep,
            *self.bindings.values(),
        ):
            widget.setEnabled(not running and phase != "paused")
        if message:
            self.status.setText(message)
        self.summary.setText({"paused": "Paused", "done": "Done"}.get(phase, "Rolling" if running else ""))
        self.refresh()
