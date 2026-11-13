# Copyright (C) 2026 RivenRoller contributors.
# SPDX-License-Identifier: GPL-3.0-only

"""Phone companion: a read-only status page on your home network, plus push
notifications when the roller needs you.

Everything here only republishes what the roller already decided. It never
touches Warframe, sends no input and accepts no commands: the web server
answers GET requests for the page and its live data, nothing else.

This module has no Qt dependency so it can be tested headless.
"""

import copy
import hmac
import json
import os
import secrets
import socket
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

PAGE = Path(__file__).with_name("companion.html")
DEFAULT_PORT = 8765
PORT_TRIES = 10  # the next ports are tried if the first is taken
HISTORY = 100  # rolls kept for the phone page
KEEPALIVE_SECONDS = 15
NTFY_SERVER = "https://ntfy.sh"
DEFAULTS = {
    "enabled": False,
    "port": DEFAULT_PORT,
    "token": "",
    # Push notifications (both optional, both off until filled in).
    "ntfyTopic": "",
    "ntfyServer": NTFY_SERVER,
    "discordWebhook": "",
    "open": False,
}


def companion_settings(saved):
    """Sanitize saved companion settings; malformed values use defaults."""
    saved = saved if isinstance(saved, dict) else {}
    result = copy.deepcopy(DEFAULTS)
    for flag in ("enabled", "open"):
        if type(saved.get(flag)) is bool:
            result[flag] = saved[flag]
    port = saved.get("port")
    if type(port) is int and 1024 <= port <= 65535:
        result["port"] = port
    token = saved.get("token")
    if isinstance(token, str) and 16 <= len(token) <= 64 and _plain(token):
        result["token"] = token
    else:
        result["token"] = secrets.token_urlsafe(16)
    topic = saved.get("ntfyTopic")
    if isinstance(topic, str) and len(topic) <= 64 and _plain(topic):
        result["ntfyTopic"] = topic
    for name, prefixes in (
        ("ntfyServer", ("https://", "http://")),
        ("discordWebhook", ("https://",)),
    ):
        value = saved.get(name)
        if (
            isinstance(value, str)
            and len(value) <= 300
            and value.startswith(prefixes)
            and not any(c.isspace() for c in value)
        ):
            result[name] = value.rstrip("/") if name == "ntfyServer" else value
    return result


def _plain(text):
    return all(c.isascii() and (c.isalnum() or c in "-_") for c in text)


def new_topic():
    """An unguessable ntfy topic. Anyone who knows a topic can read it."""
    return "rivenroller-" + secrets.token_urlsafe(9)


class CompanionSettings:
    def __init__(self, directory):
        self.path = directory / "companion.json"
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        self.state = companion_settings(saved)

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


def lan_address():
    """This PC's address on the home network (no packet is actually sent)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


# ------------------------------------------------------------------ run state


class RunState:
    """What the phone shows: the run's status and its recent rolls."""

    def __init__(self):
        self.reset()

    def reset(self, plan=None):
        self.data = {
            "phase": "idle",
            "stage": None,
            "stageLabel": "",
            "message": "Auto roller idle.",
            "rolls": 0,
            "maxRolls": None,
            "plan": plan or {},
            "startedAt": time.time() if plan else None,
            "updatedAt": time.time(),
            "history": [],
        }

    def update(self, **fields):
        changed = any(self.data.get(k) != v for k, v in fields.items())
        if changed:
            self.data.update(fields, updatedAt=time.time())
        return changed

    def add_roll(self, record):
        history = self.data["history"]
        if history and history[0].get("roll") == record.get("roll"):
            return False
        history.insert(0, {**record, "at": time.time()})
        del history[HISTORY:]
        self.data["updatedAt"] = time.time()
        return True


# --------------------------------------------------------------------- server


class _Handler(BaseHTTPRequestHandler):
    server_version = "RivenRoller"
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):  # no console under pythonw
        pass

    def do_GET(self):
        hub = self.server.hub
        url = urlsplit(self.path)
        given = parse_qs(url.query).get("k", [""])[0]
        if not hmac.compare_digest(given.encode(), hub.token.encode()):
            return self._send(403, "text/plain", b"Open the link from RivenRoller.")
        if url.path == "/":
            return self._send(200, "text/html; charset=utf-8", PAGE.read_bytes())
        if url.path == "/state":
            return self._send(200, "application/json", hub.payload()[1])
        if url.path == "/events":
            return self._events(hub)
        return self._send(404, "text/plain", b"Not found.")

    def _send(self, status, kind, body):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _events(self, hub):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        seen = -1
        try:
            while not hub.closed:
                version, body = hub.wait(seen, KEEPALIVE_SECONDS)
                if version == seen:
                    self.wfile.write(b": keepalive\n\n")
                else:
                    seen = version
                    self.wfile.write(b"data: " + body + b"\n\n")
                self.wfile.flush()
        except OSError:
            pass  # the phone went away


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class Companion:
    """Serves the page and pushes each published state to connected phones."""

    def __init__(self, token, port=DEFAULT_PORT, host="0.0.0.0"):
        self.token = token
        self.closed = False
        self._changed = threading.Condition()
        self._version = 0
        self._body = b"{}"
        self.server = None
        last = None
        for candidate in [port] if port == 0 else range(port, port + PORT_TRIES):
            try:
                self.server = _Server((host, candidate), _Handler)
                break
            except OSError as exc:
                last = exc
        if self.server is None:
            raise OSError(f"No free port from {port} to {port + PORT_TRIES - 1}: {last}")
        self.server.hub = self
        self.port = self.server.server_address[1]
        threading.Thread(
            target=self.server.serve_forever, name="companion", daemon=True
        ).start()

    def url(self, address=None):
        return f"http://{address or lan_address()}:{self.port}/?k={self.token}"

    def publish(self, data):
        body = json.dumps(data, separators=(",", ":")).encode("utf-8")
        with self._changed:
            if body == self._body:
                return
            self._body = body
            self._version += 1
            self._changed.notify_all()

    def payload(self):
        with self._changed:
            return self._version, self._body

    def wait(self, seen, timeout):
        with self._changed:
            if self._version == seen and not self.closed:
                self._changed.wait(timeout)
            return self._version, self._body

    def close(self):
        self.closed = True
        with self._changed:
            self._changed.notify_all()
        self.server.shutdown()
        self.server.server_close()


# -------------------------------------------------------------- notifications

EVENT_TITLES = {
    "done": "Target roll found",
    "paused": "Roller needs you",
    "stopped": "Roller stopped",
    "test": "RivenRoller test",
}
EVENT_TAGS = {
    "done": "tada",
    "paused": "bell",
    "stopped": "warning",
    "test": "white_check_mark",
}


def notification_requests(settings, event, message):
    """The HTTP requests that announce one roller event (possibly none)."""
    title = EVENT_TITLES.get(event, "RivenRoller")
    requests = []
    if settings.get("ntfyTopic"):
        requests.append(
            urllib.request.Request(
                f"{settings.get('ntfyServer') or NTFY_SERVER}/{settings['ntfyTopic']}",
                data=message.encode("utf-8"),
                headers={
                    "Title": title,
                    "Priority": "default" if event == "test" else "high",
                    "Tags": EVENT_TAGS.get(event, "game_die"),
                },
                method="POST",
            )
        )
    if settings.get("discordWebhook"):
        requests.append(
            urllib.request.Request(
                settings["discordWebhook"],
                data=json.dumps(
                    {"content": f"**{title}**\n{message}"[:1900]}
                ).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "RivenRoller",
                },
                method="POST",
            )
        )
    return requests


class Notifier:
    """Sends notifications off the GUI thread; failures never touch the run."""

    def __init__(self, opener=None, on_result=None):
        self.opener = opener or (lambda request: urllib.request.urlopen(request, timeout=10))
        self.on_result = on_result or (lambda problem: None)

    def send(self, settings, event, message):
        requests = notification_requests(settings, event, message)
        if not requests:
            return None
        thread = threading.Thread(
            target=self._deliver, args=(requests,), name="notify", daemon=True
        )
        thread.start()
        return thread

    def _deliver(self, requests):
        problems = []
        for request in requests:
            try:
                response = self.opener(request)
                if hasattr(response, "close"):
                    response.close()
            except Exception as exc:  # offline, bad topic, bad webhook...
                host = urlsplit(request.full_url).hostname
                problems.append(f"{host}: {exc}")
        self.on_result("; ".join(problems))
