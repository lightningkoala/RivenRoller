# Copyright (C) 2026 RivenRoller contributors.
# SPDX-License-Identifier: GPL-3.0-only

"""Phone companion controls: the status page link and notification settings."""

import io

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QCheckBox, QGridLayout, QLabel, QLineEdit

from companion import companion_settings, new_topic
from ui_text import QPushButton
from widgets import Section, box, label


def qr_pixmap(text):
    """A QR code for the link, or None if the optional 'segno' isn't installed."""
    try:
        import segno
    except ImportError:
        return None
    data = io.BytesIO()
    segno.make(text, error="m").save(data, kind="png", scale=4, border=2)
    pixmap = QPixmap()
    pixmap.loadFromData(data.getvalue(), "PNG")
    return pixmap


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
            "Wi-Fi can open it with the link below; it can't control anything."
        )
        self.enabled.setChecked(settings["enabled"])
        self.enabled.toggled.connect(self.save)
        self.content.addWidget(self.enabled)
        self.qr = QLabel()
        self.qr.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.content.addWidget(self.qr)
        self.link = label("", "note", wrap=True)
        self.link.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.content.addWidget(self.link)
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

    def show_link(self, url, problem=None):
        pixmap = qr_pixmap(url) if url else None
        self.qr.setPixmap(pixmap or QPixmap())
        self.qr.setVisible(bool(pixmap))
        if problem:
            self.link.setText(problem)
        elif url:
            self.link.setText(
                ("Scan with your phone (same Wi-Fi), or open: " if pixmap else "Open on your phone (same Wi-Fi): ")
                + url
            )
        else:
            self.link.setText("Status page is off.")
        self.summary.setText("On" if url else "")
        self.refresh()

    def show_notify_result(self, problem, pending=False):
        if pending:
            self.status.setText(problem)
        else:
            self.status.setText(
                "Notification failed: " + problem if problem else "Notification sent."
            )
