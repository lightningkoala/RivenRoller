# Copyright (C) 2026 RivenRoller contributors.
# SPDX-License-Identifier: GPL-3.0-only

"""Phone companion controls: the status page link and notification settings."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication, QCheckBox, QGridLayout, QLineEdit

from companion import companion_settings, new_topic
from ui_text import QPushButton
from widgets import Section, box, label


class CompanionView(Section):
    changed = Signal()
    test_requested = Signal()

    def __init__(self, store, parent=None):
        super().__init__("Phone companion", store.state["open"], parent)
        self.store = store
        settings = store.state
        self.enabled = QCheckBox("Show a status page on my home network")
        self.enabled.setToolTip(
            "Starts a small read-only web page on this PC. Phones on the same "
            "Wi-Fi can open it with the address and code below; it can't "
            "control anything."
        )
        self.enabled.setChecked(settings["enabled"])
        self.enabled.toggled.connect(self.save)
        self.content.addWidget(self.enabled)
        self.link = label("", "status", wrap=True)
        self.link.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.content.addWidget(self.link)
        self.copy = QPushButton("Copy link")
        self.copy.setToolTip(
            "Copies the page's link with the code already in it, to send to "
            "your phone yourself (a note or a message to yourself)."
        )
        self.copy.clicked.connect(self.copy_link)
        self.content.addWidget(self.copy)
        self.full_link = None
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        self.topic = QLineEdit(settings["ntfyTopic"])
        self.topic.setPlaceholderText("off (press New topic to turn on)")
        self.topic.setToolTip(
            "Subscribe to this topic in the free ntfy app to get a notification "
            "when the roller pauses, finishes or stops. Keep it secret: anyone "
            "who knows the topic can read those messages."
        )
        self.topic.editingFinished.connect(self.save)
        self.webhook = QLineEdit(settings["discordWebhook"])
        self.webhook.setPlaceholderText("off (optional Discord webhook URL)")
        self.webhook.editingFinished.connect(self.save)
        grid.addWidget(label("ntfy topic"), 0, 0)
        grid.addWidget(self.topic, 0, 1)
        grid.addWidget(label("Discord"), 1, 0)
        grid.addWidget(self.webhook, 1, 1)
        self.content.addLayout(grid)
        buttons, row = box(False, spacing=6)
        self.generate = QPushButton("New topic")
        self.generate.clicked.connect(self.generate_topic)
        self.test = QPushButton("Send test")
        self.test.clicked.connect(self.send_test)
        row.addWidget(self.generate)
        row.addWidget(self.test)
        self.content.addWidget(buttons)
        self.status = label("", "status", wrap=True)
        self.content.addWidget(self.status)
        self.toggled.connect(self._remember_open)
        self.show_link(None)

    def _remember_open(self, opened):
        self.store.state["open"] = opened
        self.store.save()

    def generate_topic(self):
        self.topic.setText(new_topic())
        self.save()

    def send_test(self):
        self.save()
        self.test_requested.emit()

    def save(self, *_):
        saved = companion_settings(
            {
                **self.store.state,
                "enabled": self.enabled.isChecked(),
                "ntfyTopic": self.topic.text().strip(),
                "discordWebhook": self.webhook.text().strip(),
                "open": self.opened,
            }
        )
        # Invalid entries are dropped; show what will actually be used.
        self.topic.setText(saved["ntfyTopic"])
        self.webhook.setText(saved["discordWebhook"])
        if saved == self.store.state:
            return
        self.store.state = saved
        self.changed.emit()

    def copy_link(self):
        if self.full_link:
            QApplication.clipboard().setText(self.full_link)
            self.status.setText("Link copied.")

    def show_link(self, address, code=None, problem=None):
        self.full_link = f"{address}/?k={code}" if address else None
        self.copy.setVisible(bool(address))
        if problem:
            self.link.setText(problem)
        elif address:
            self.link.setText(
                f"On your phone (same Wi-Fi), open  {address.removeprefix('http://')}  "
                f"in the browser and enter the code  {code}"
            )
        else:
            self.link.setText("Status page is off.")
        self.summary.setText("On" if address else "")
        self.refresh()

    def show_notify_result(self, problem, pending=False):
        if pending:
            self.status.setText(problem)
        else:
            self.status.setText(
                "Notification failed: " + problem if problem else "Notification sent."
            )
