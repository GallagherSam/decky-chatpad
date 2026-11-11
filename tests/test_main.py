"""Exercise main.py's Plugin lifecycle against a stub `decky` module and a fake keyboard."""

import asyncio
import importlib.util
import json
import logging
import os
import sys
import tempfile
import types
import unittest
import urllib.request

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "py_modules"))

from chatpad.uinput import RecordingKeyboard  # noqa: E402


class FakeKb(RecordingKeyboard):
    def __init__(self):
        super().__init__()
        self.fd = None

    def open(self):
        super().open()
        self.fd = 99

    def close(self):
        super().close()
        self.fd = None


class PluginLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        decky = types.ModuleType("decky")
        decky.DECKY_PLUGIN_SETTINGS_DIR = self.tmp.name
        decky.logger = logging.getLogger("chatpad-test")
        sys.modules["decky"] = decky
        spec = importlib.util.spec_from_file_location("chatpad_main", os.path.join(ROOT, "main.py"))
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.mod.UInputKeyboard = FakeKb
        # use an ephemeral port so tests never collide with a real 8765
        with open(os.path.join(self.tmp.name, "settings.json"), "w") as f:
            json.dump({"port": 18765}, f)

    def tearDown(self):
        self.tmp.cleanup()
        sys.modules.pop("decky", None)

    def test_lifecycle(self):
        async def scenario():
            p = self.mod.Plugin()
            await p._main()
            st = await p.get_status()
            self.assertTrue(st["running"])
            self.assertTrue(st["uinputOk"])
            self.assertIn(f":{st['port']}/?t={st['token']}", st["url"])

            def post():
                req = urllib.request.Request(
                    f"http://127.0.0.1:{st['port']}/api/send", data=json.dumps({"text": "hi"}).encode(),
                    method="POST", headers={"X-Chatpad-Token": st["token"], "Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=5) as r:
                    return r.status
            self.assertEqual(await asyncio.to_thread(post), 200)
            st = await p.get_status()
            self.assertEqual(st["sends"], 1)

            old = st["token"]
            st = await p.rotate_token()
            self.assertNotEqual(old, st["token"])

            st = await p.set_setting("key_delay_ms", 20)
            self.assertEqual(st["keyDelayMs"], 20)
            with self.assertRaises(ValueError):
                await p.set_setting("enabled_evil", 1)

            self.assertEqual(st["mode"], "chat")
            st = await p.set_setting("mode", "field")
            self.assertEqual(st["mode"], "field")
            st = await p.set_setting("clear_method", "backspace")
            st = await p.set_setting("clear_backspace_count", 40)
            st = await p.set_setting("clear_before_typing", True)
            self.assertEqual((st["clearMethod"], st["clearBackspaceCount"], st["clearBefore"]),
                             ("backspace", 40, True))
            with self.assertRaises(ValueError):
                await p.set_setting("mode", "macro")
            # the phone sees the mode the QAM set
            def state():
                req = urllib.request.Request(f"http://127.0.0.1:{st['port']}/api/state",
                                             headers={"X-Chatpad-Token": st["token"]})
                with urllib.request.urlopen(req, timeout=5) as r:
                    return json.loads(r.read())
            self.assertEqual((await asyncio.to_thread(state))["mode"], "field")

            st = await p.set_enabled(False)
            self.assertFalse(st["running"])
            st = await p.set_enabled(True)
            self.assertTrue(st["running"])

            await p._unload()
            self.assertFalse(p.server.running)
            self.assertIsNone(p.keyboard.fd)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
