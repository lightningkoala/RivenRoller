# Copyright (C) 2026 RivenRoller contributors.
# SPDX-License-Identifier: GPL-3.0-only
"""Phone companion: settings, the read-only server, live updates, notifications."""

import http.client
import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "roller")]

import companion  # noqa: E402
from companion import (  # noqa: E402
    Companion, CompanionSettings, Notifier, RunState, companion_settings,
    notification_requests,
)

TOKEN = "t" * 22


class SettingsTests(unittest.TestCase):
    def test_defaults_are_off_with_a_fresh_token(self):
        first, second = companion_settings(None), companion_settings({})
        self.assertFalse(first["enabled"])
        self.assertEqual((first["ntfyTopic"], first["discordWebhook"]), ("", ""))
        self.assertEqual(len(first["token"]), companion.CODE_LENGTH)
        self.assertTrue(set(first["token"]) <= set(companion.CODE_ALPHABET))
        self.assertFalse(set("01IO") & set(companion.CODE_ALPHABET))
        self.assertNotEqual(first["token"], second["token"])

    def test_malformed_values_fall_back(self):
        saved = companion_settings({
            "enabled": "yes", "port": 80, "token": "short",
            "ntfyTopic": "has space/slash", "ntfyServer": "ftp://x",
            "discordWebhook": "http://not-https.example/hook",
        })
        self.assertFalse(saved["enabled"])
        self.assertEqual(saved["port"], companion.DEFAULT_PORT)
        self.assertNotEqual(saved["token"], "short")
        self.assertEqual(saved["ntfyTopic"], "")
        self.assertEqual(saved["ntfyServer"], companion.NTFY_SERVER)
        self.assertEqual(saved["discordWebhook"], "")

    def test_round_trip_keeps_the_token(self):
        with tempfile.TemporaryDirectory() as folder:
            store = CompanionSettings(Path(folder))
            store.state.update(enabled=True, ntfyTopic=companion.new_topic())
            store.save()
            again = CompanionSettings(Path(folder))
            self.assertEqual(again.state, store.state)


class RunStateTests(unittest.TestCase):
    def test_history_is_newest_first_deduplicated_and_capped(self):
        run = RunState()
        run.reset({"weapon": "Boar"})
        self.assertTrue(run.add_roll({"roll": 1, "wanted": False}))
        self.assertFalse(run.add_roll({"roll": 1, "wanted": False}))
        for number in range(2, companion.HISTORY + 20):
            run.add_roll({"roll": number, "wanted": False})
        history = run.data["history"]
        self.assertEqual(len(history), companion.HISTORY)
        self.assertEqual(history[0]["roll"], companion.HISTORY + 19)
        self.assertTrue(run.update(phase="paused"))
        self.assertFalse(run.update(phase="paused"))
        run.reset({"weapon": "Lex"})
        self.assertEqual(run.data["history"], [])


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.hub = Companion(TOKEN, port=0, host="127.0.0.1")
        self.addCleanup(self.hub.close)

    def get(self, path, key=TOKEN):
        url = f"http://127.0.0.1:{self.hub.port}{path}?k={key}"
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.read()

    def test_run_data_needs_the_code(self):
        self.hub.publish({"phase": "paused", "message": "secret roll"})
        for key in ("", "wrong"):
            for path in ("/state", "/events"):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    self.get(path, key)
                self.assertEqual(caught.exception.code, 403)
        # The page itself opens without a code (it asks for one) and holds no data.
        page = self.get("/", "")
        self.assertIn(b'id="pair"', page)
        self.assertNotIn(b"secret roll", page)

    def test_typed_code_ignores_case_and_spaces(self):
        hub = Companion("QX7MPA", port=0, host="127.0.0.1")
        self.addCleanup(hub.close)
        self.assertEqual(hub.check("phone", " qx7mpa "), 200)
        self.assertEqual(hub.check("phone", "QX7MPB"), 403)
        self.assertEqual(hub.address("192.168.1.23"), f"http://192.168.1.23:{hub.port}")
        self.assertEqual(hub.url("192.168.1.23"), f"http://192.168.1.23:{hub.port}/?k=QX7MPA")

    def test_wrong_codes_lock_out_only_that_device(self):
        limit, wait = companion.WRONG_CODE_LIMIT, companion.LOCKOUT_SECONDS
        for attempt in range(limit):
            self.assertEqual(self.hub.check("guesser", "NOPE", now=attempt), 403)
        # Locked out: even the right code is refused, so guessing can't succeed.
        self.assertEqual(self.hub.check("guesser", TOKEN, now=limit), 429)
        self.assertEqual(self.hub.check("phone", TOKEN, now=limit), 200)
        self.assertEqual(self.hub.check("guesser", TOKEN, now=wait + limit), 200)
        # A right code clears earlier slips.
        for attempt in range(limit - 1):
            self.hub.check("phone", "typo", now=200 + attempt)
        self.assertEqual(self.hub.check("phone", TOKEN, now=210), 200)
        self.assertEqual(self.hub.check("phone", "typo", now=211), 403)

    def test_lockout_over_http(self):
        for _ in range(companion.WRONG_CODE_LIMIT):
            with self.assertRaises(urllib.error.HTTPError):
                self.get("/state", "wrong")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/state")
        self.assertEqual(caught.exception.code, 429)

    def test_serves_page_and_state(self):
        self.hub.publish({"phase": "paused", "rolls": 12})
        self.assertIn(b"<title>RivenRoller</title>", self.get("/"))
        self.assertEqual(json.loads(self.get("/state")), {"phase": "paused", "rolls": 12})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/other")
        self.assertEqual(caught.exception.code, 404)

    def test_accepts_no_commands(self):
        for method in ("POST", "PUT", "DELETE"):
            link = http.client.HTTPConnection("127.0.0.1", self.hub.port, timeout=5)
            link.request(method, f"/state?k={TOKEN}", body=b"{}")
            self.assertEqual(link.getresponse().status, 501)
            link.close()

    def test_live_updates_reach_a_connected_phone(self):
        self.hub.publish({"rolls": 1})
        link = http.client.HTTPConnection("127.0.0.1", self.hub.port, timeout=5)
        link.request("GET", f"/events?k={TOKEN}")
        stream = link.getresponse()
        self.assertEqual(stream.getheader("Content-Type"), "text/event-stream")

        def event():
            line = stream.readline()
            self.assertEqual(stream.readline(), b"\n")
            return json.loads(line.removeprefix(b"data: "))

        self.assertEqual(event(), {"rolls": 1})  # the state on connecting
        self.hub.publish({"rolls": 1})  # unchanged: nothing is sent
        self.hub.publish({"rolls": 2, "phase": "done"})
        self.assertEqual(event(), {"rolls": 2, "phase": "done"})
        link.close()

    def test_page_never_builds_html_from_roll_text(self):
        page = companion.PAGE.read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", page)
        self.assertNotIn("http://", page.split("<script>")[1])
        self.assertNotIn("https://", page)  # loads nothing from the internet


class NotificationTests(unittest.TestCase):
    def test_nothing_is_sent_unless_configured(self):
        self.assertEqual(notification_requests(companion_settings({}), "done", "x"), [])
        self.assertIsNone(Notifier(opener=self.fail).send(companion_settings({}), "done", "x"))

    def test_ntfy_and_discord_requests(self):
        settings = companion_settings({
            "ntfyTopic": "rivenroller-abc",
            "discordWebhook": "https://discord.com/api/webhooks/1/abc",
        })
        message = "Found −Recoil at S. Lock it, then Resume."
        ntfy, discord = notification_requests(settings, "paused", message)
        self.assertEqual(ntfy.full_url, "https://ntfy.sh/rivenroller-abc")
        self.assertEqual(ntfy.get_method(), "POST")
        self.assertEqual(ntfy.data.decode("utf-8"), message)
        self.assertEqual(ntfy.headers["Title"], "Roller needs you")
        self.assertEqual(ntfy.headers["Priority"], "high")
        for value in ntfy.headers.values():
            value.encode("latin-1")  # HTTP headers can't carry the minus sign
        self.assertEqual(discord.full_url, settings["discordWebhook"])
        self.assertIn(message, json.loads(discord.data)["content"])

    def test_delivery_runs_off_thread_and_reports_failures(self):
        settings = companion_settings({"ntfyTopic": "rivenroller-abc"})
        sent, results = [], []
        thread = Notifier(opener=sent.append, on_result=results.append).send(
            settings, "done", "Target roll found after 40 rolls.")
        thread.join(5)
        self.assertEqual(len(sent), 1)
        self.assertEqual(results, [""])

        def offline(request):
            raise OSError("no route")

        thread = Notifier(opener=offline, on_result=results.append).send(
            settings, "done", "x")
        thread.join(5)
        self.assertIn("ntfy.sh: no route", results[1])


if __name__ == "__main__":
    unittest.main()
