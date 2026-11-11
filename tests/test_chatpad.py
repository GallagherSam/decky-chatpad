import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from chatpad import keymap  # noqa: E402
from chatpad.core import ChatpadCore  # noqa: E402
from chatpad.keymap import KEY_ENTER, KEY_LEFTSHIFT, KEY_SLASH, normalize_text, text_to_strokes  # noqa: E402
from chatpad.netinfo import parse_ip_addr  # noqa: E402
from chatpad.security import FailureThrottle, RateLimiter, TokenManager  # noqa: E402
from chatpad.server import ChatpadServer  # noqa: E402
from chatpad.settings import DEFAULTS, Settings  # noqa: E402
from chatpad.uinput import INPUT_EVENT, USER_DEV, RecordingKeyboard, Typer  # noqa: E402


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def keys_to_text(events):
    """Decode recorded (code, down) events back into text using the US keymap."""
    rev = {}
    for ch, s in keymap.KEYMAP.items():
        rev[(s.code, s.shift)] = ch
    shift = False
    out = []
    for code, down in events:
        if code == KEY_LEFTSHIFT:
            shift = down
        elif code == KEY_ENTER:
            if down:
                out.append("<ENTER>")
        elif down:
            out.append(rev[(code, shift)])
    return "".join(out)


class KeymapTests(unittest.TestCase):
    def test_all_printable_ascii_mapped(self):
        for c in range(0x20, 0x7F):
            self.assertIn(chr(c), keymap.KEYMAP, repr(chr(c)))
        self.assertEqual(len(keymap.KEYMAP), 95)

    def test_known_codes(self):
        self.assertEqual(keymap.KEYMAP["a"], (30, False))
        self.assertEqual(keymap.KEYMAP["A"], (30, True))
        self.assertEqual(keymap.KEYMAP["1"], (2, False))
        self.assertEqual(keymap.KEYMAP["!"], (2, True))
        self.assertEqual(keymap.KEYMAP["0"], (11, False))
        self.assertEqual(keymap.KEYMAP["/"], (53, False))
        self.assertEqual(keymap.KEYMAP["?"], (53, True))
        self.assertEqual(keymap.KEYMAP[" "], (57, False))
        self.assertEqual(keymap.KEYMAP['"'], (40, True))
        self.assertEqual(keymap.KEYMAP["|"], (43, True))
        self.assertEqual(keymap.KEYMAP["~"], (41, True))

    def test_unique_code_shift_pairs(self):
        pairs = list(keymap.KEYMAP.values())
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_roundtrip_every_char(self):
        text = "".join(chr(c) for c in range(0x20, 0x7F))
        kb = RecordingKeyboard()
        Typer(kb, sleep=lambda s: None).type_message(text_to_strokes(text), open_key="none", press_enter=False)
        self.assertEqual(keys_to_text(kb.events), text)

    def test_smart_punctuation(self):
        out, rep = normalize_text("I’m “ok” — wait…")
        self.assertEqual(out, 'I\'m "ok" - wait...')
        self.assertEqual(rep, 0)

    def test_accents_stripped(self):
        out, rep = normalize_text("café naïve")
        self.assertEqual((out, rep), ("cafe naive", 0))

    def test_unmappable_replaced(self):
        out, rep = normalize_text("hi \U0001F600 你")
        self.assertEqual((out, rep), ("hi ? ?", 2))

    def test_newlines_become_spaces(self):
        self.assertEqual(normalize_text("a\nb\tc")[0], "a b c")

    def test_text_to_strokes_rejects_unmapped(self):
        with self.assertRaises(ValueError):
            text_to_strokes("é")


class TyperTests(unittest.TestCase):
    def run_typer(self, text, **kw):
        kb = RecordingKeyboard()
        Typer(kb, sleep=lambda s: None).type_message(text_to_strokes(text), **kw)
        return kb

    def test_enter_open_and_submit(self):
        kb = self.run_typer("Hi", open_key="enter", press_enter=True)
        self.assertEqual(keys_to_text(kb.events), "<ENTER>Hi<ENTER>")
        self.assertTrue(kb.opened)

    def test_type_only(self):
        kb = self.run_typer("hi", open_key="enter", press_enter=False)
        self.assertEqual(keys_to_text(kb.events), "<ENTER>hi")

    def test_shift_balanced(self):
        kb = self.run_typer("A!b", open_key="none", press_enter=False)
        downs = [e for e in kb.events if e == (KEY_LEFTSHIFT, True)]
        ups = [e for e in kb.events if e == (KEY_LEFTSHIFT, False)]
        self.assertEqual(len(downs), 2)
        self.assertEqual(len(ups), 2)
        # every key press is released
        held = set()
        for code, down in kb.events:
            (held.add if down else held.discard)(code)
        self.assertEqual(held, set())

    def test_delays_applied(self):
        sleeps = []
        Typer(RecordingKeyboard(), sleep=sleeps.append).type_message(
            text_to_strokes("ab"), open_key="enter", press_enter=True, key_delay_ms=10, open_delay_ms=100)
        self.assertIn(0.1, sleeps)
        self.assertTrue(all(abs(s - 0.01) < 1e-9 or abs(s - 0.005) < 1e-9 or s == 0.1 for s in sleeps))

    def test_shift_released_on_error(self):
        class Boom(RecordingKeyboard):
            def key(self, code, down):
                super().key(code, down)
                if code == 30 and down:
                    raise OSError("device gone")
        kb = Boom()
        with self.assertRaises(OSError):
            Typer(kb, sleep=lambda s: None).type_message(text_to_strokes("A"), open_key="none")
        self.assertEqual(kb.events[-1], (KEY_LEFTSHIFT, False))


class StructTests(unittest.TestCase):
    def test_struct_sizes_x86_64(self):
        self.assertEqual(INPUT_EVENT.size, 24)
        self.assertEqual(USER_DEV.size, 1116)


class SecurityTests(unittest.TestCase):
    def test_token_check_and_rotate(self):
        tm = TokenManager()
        t = tm.token
        self.assertGreaterEqual(len(t), 16)
        self.assertTrue(tm.check(t))
        self.assertFalse(tm.check(t + "x"))
        self.assertFalse(tm.check(""))
        self.assertFalse(tm.check(None))
        self.assertFalse(tm.check(123))
        t2 = tm.rotate()
        self.assertNotEqual(t, t2)
        self.assertFalse(tm.check(t))
        self.assertTrue(tm.check(t2))

    def test_tokens_random(self):
        self.assertEqual(len({TokenManager().token for _ in range(50)}), 50)

    def test_rate_limiter(self):
        clk = FakeClock()
        rl = RateLimiter(1.0, clock=clk)
        self.assertTrue(rl.try_acquire())
        self.assertFalse(rl.try_acquire())
        clk.t += 0.5
        self.assertFalse(rl.try_acquire())
        self.assertAlmostEqual(rl.retry_after(), 0.5)
        clk.t += 0.5
        self.assertTrue(rl.try_acquire())

    def test_failure_throttle(self):
        clk = FakeClock()
        ft = FailureThrottle(max_failures=3, window=60, clock=clk)
        for _ in range(3):
            self.assertFalse(ft.blocked("1.2.3.4"))
            ft.record("1.2.3.4")
        self.assertTrue(ft.blocked("1.2.3.4"))
        self.assertFalse(ft.blocked("5.6.7.8"))
        clk.t += 61
        self.assertFalse(ft.blocked("1.2.3.4"))


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "sub", "settings.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_defaults_and_persist(self):
        s = Settings(self.path)
        self.assertEqual(s.get("port"), 8765)
        s.set("key_delay_ms", 25)
        s.set("open_key", "slash")
        s2 = Settings(self.path)
        self.assertEqual(s2.get("key_delay_ms"), 25)
        self.assertEqual(s2.get("open_key"), "slash")

    def test_validation(self):
        s = Settings(self.path)
        self.assertEqual(s.set("key_delay_ms", 9999), 100)
        self.assertEqual(s.set("key_delay_ms", 0), 2)
        with self.assertRaises(ValueError):
            s.set("open_key", "tab")
        with self.assertRaises(KeyError):
            s.set("nope", 1)

    def test_corrupt_file_ignored(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as f:
            f.write("{not json")
        self.assertEqual(Settings(self.path).get("chips"), DEFAULTS["chips"])


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.kb = RecordingKeyboard()
        self.clock = FakeClock()
        self.core = ChatpadCore(Settings(os.path.join(self.dir.name, "s.json")), self.kb,
                                sleep=lambda s: None, clock=self.clock)

    def tearDown(self):
        self.dir.cleanup()

    def test_send_types_text(self):
        code, r = self.core.send("/p hello", True)
        self.assertEqual(code, 200)
        self.assertEqual(keys_to_text(self.kb.events), "<ENTER>/p hello<ENTER>")
        self.assertEqual(self.core.history, ["/p hello"])
        self.assertTrue(self.core.last_send["ok"])

    def test_slash_open_key(self):
        self.core.settings.set("open_key", "slash")
        self.core.send("/g hi", True)
        self.assertEqual(self.kb.events[0], (KEY_SLASH, True))
        self.assertEqual(keys_to_text(self.kb.events), "/g hi<ENTER>")
        # plain text in slash mode falls back to Enter so the '/' doesn't corrupt it
        self.kb.events.clear()
        self.clock.t += 2
        self.core.send("hi", True)
        self.assertEqual(keys_to_text(self.kb.events), "<ENTER>hi<ENTER>")

    def test_none_open_key_type_only(self):
        self.core.settings.set("open_key", "none")
        self.core.send("hi", False)
        self.assertEqual(keys_to_text(self.kb.events), "hi")

    def test_rate_limit(self):
        self.assertEqual(self.core.send("one")[0], 200)
        code, r = self.core.send("two")
        self.assertEqual(code, 429)
        self.clock.t += 1.0
        self.assertEqual(self.core.send("three")[0], 200)

    def test_length_limit(self):
        self.assertEqual(self.core.send("x" * 255)[0], 200)
        self.clock.t += 2
        self.assertEqual(self.core.send("x" * 256)[0], 413)

    def test_empty_and_bad_type(self):
        self.assertEqual(self.core.send("   ")[0], 400)
        self.assertEqual(self.core.send(None)[0], 400)
        self.assertEqual(self.core.send(["a"])[0], 400)
        self.assertEqual(self.kb.events, [])

    def test_non_ascii_replaced(self):
        code, r = self.core.send("hi \U0001F600")
        self.assertEqual((code, r["typed"], r["replaced"]), (200, "hi ?", 1))

    def test_history_dedup_and_cap(self):
        for i in range(12):
            self.clock.t += 2
            self.core.send(f"m{i}")
        self.clock.t += 2
        self.core.send("m5")
        self.assertEqual(len(self.core.history), 10)
        self.assertEqual(self.core.history[0], "m5")
        self.assertEqual(self.core.history.count("m5"), 1)

    def test_uinput_failure_reported(self):
        def boom():
            raise PermissionError(13, "Permission denied")
        self.kb.open = boom
        code, r = self.core.send("hi")
        self.assertEqual(code, 503)
        self.assertFalse(self.core.last_send["ok"])
        self.assertEqual(self.core.history, [])

    def test_busy_rejected(self):
        self.core._busy.acquire()
        try:
            self.assertEqual(self.core.send("hi")[0], 409)
        finally:
            self.core._busy.release()

    def test_edit_lists(self):
        code, st = self.core.edit_list("phrases", "add", "  need heals  ")
        self.assertEqual(code, 200)
        self.assertIn("need heals", st["phrases"])
        code, st = self.core.edit_list("phrases", "remove", "need heals")
        self.assertNotIn("need heals", st["phrases"])
        code, st = self.core.edit_list("chips", "add", {"prefix": "/3", "label": "LFG"})
        self.assertIn({"label": "LFG", "prefix": "/3 "}, st["chips"])
        code, st = self.core.edit_list("chips", "remove", {"prefix": "/3 "})
        self.assertNotIn("/3 ", [c["prefix"] for c in st["chips"]])
        self.assertEqual(self.core.edit_list("bogus", "add", "x")[0], 400)
        self.assertEqual(self.core.edit_list("phrases", "add", "")[0], 400)
        # persisted
        self.assertEqual(Settings(self.core.settings.path).get("phrases"), self.core.settings.get("phrases"))


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.kb = RecordingKeyboard()
        self.clock = FakeClock()
        self.core = ChatpadCore(Settings(os.path.join(self.dir.name, "s.json")), self.kb,
                                sleep=lambda s: None, clock=self.clock)
        self.server = ChatpadServer(self.core)
        self.server.start("127.0.0.1", 0)
        self.base = f"http://127.0.0.1:{self.server.port}"

    def tearDown(self):
        self.server.stop()
        self.dir.cleanup()

    def req(self, method, path, body=None, token="__default__", raw=None):
        headers = {}
        if token == "__default__":
            token = self.core.tokens.token
        if token is not None:
            headers["X-Chatpad-Token"] = token
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        if data is not None:
            headers["Content-Type"] = "application/json"
        r = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def test_page_served(self):
        code, headers, body = self.req("GET", "/?t=whatever", token=None)
        self.assertEqual(code, 200)
        self.assertIn(b"<title>Chatpad</title>", body)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertNotIn(b"http://", body.replace(b"http://www.w3.org", b""))  # no external resources

    def test_state_requires_token(self):
        self.assertEqual(self.req("GET", "/api/state", token=None)[0], 401)
        self.assertEqual(self.req("GET", "/api/state", token="wrong")[0], 401)
        code, _, body = self.req("GET", "/api/state")
        self.assertEqual(code, 200)
        st = json.loads(body)
        self.assertEqual(st["maxChars"], 255)
        self.assertTrue(st["chips"])

    def test_token_in_query_not_accepted_for_api(self):
        code = self.req("GET", "/api/state?t=" + self.core.tokens.token, token=None)[0]
        self.assertEqual(code, 401)

    def test_send(self):
        code, _, body = self.req("POST", "/api/send", {"text": "/s hello world", "enter": True})
        self.assertEqual(code, 200, body)
        self.assertEqual(keys_to_text(self.kb.events), "<ENTER>/s hello world<ENTER>")
        self.assertEqual(json.loads(body)["history"], ["/s hello world"])

    def test_send_bad_token_types_nothing(self):
        code, _, _ = self.req("POST", "/api/send", {"text": "hi"}, token="nope")
        self.assertEqual(code, 401)
        self.assertEqual(self.kb.events, [])

    def test_rotated_token_invalidates_old(self):
        old = self.core.tokens.token
        self.core.rotate_token()
        self.assertEqual(self.req("POST", "/api/send", {"text": "hi"}, token=old)[0], 401)
        self.assertEqual(self.req("POST", "/api/send", {"text": "hi"})[0], 200)

    def test_rate_limit_over_http(self):
        self.assertEqual(self.req("POST", "/api/send", {"text": "a"})[0], 200)
        self.assertEqual(self.req("POST", "/api/send", {"text": "b"})[0], 429)

    def test_too_long(self):
        self.assertEqual(self.req("POST", "/api/send", {"text": "x" * 300})[0], 413)

    def test_bad_json(self):
        self.assertEqual(self.req("POST", "/api/send", raw=b"{nope")[0], 400)
        self.assertEqual(self.req("POST", "/api/send", raw=b"[1,2]")[0], 400)

    def test_body_too_large(self):
        self.assertEqual(self.req("POST", "/api/send", raw=b"{" + b" " * 9000 + b"}")[0], 413)

    def test_brute_force_throttled(self):
        for _ in range(20):
            self.req("GET", "/api/state", token="bad")
        self.assertEqual(self.req("GET", "/api/state")[0], 429)
        self.core.rotate_token()  # rotating clears the throttle
        self.assertEqual(self.req("GET", "/api/state")[0], 200)

    def test_list_endpoint(self):
        code, _, body = self.req("POST", "/api/list", {"kind": "phrases", "action": "add", "item": "wts ore"})
        self.assertEqual(code, 200)
        self.assertIn("wts ore", json.loads(body)["phrases"])
        self.assertEqual(self.req("POST", "/api/list", {"kind": "phrases", "action": "add", "item": "x"},
                                  token=None)[0], 401)

    def test_unknown_path(self):
        self.assertEqual(self.req("GET", "/etc/passwd", token=None)[0], 404)
        self.assertEqual(self.req("POST", "/api/keys", {"k": 1})[0], 404)

    def test_concurrent_sends_one_wins(self):
        results = []

        def go():
            results.append(self.req("POST", "/api/send", {"text": "hi"})[0])
        ts = [threading.Thread(target=go) for _ in range(5)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(results.count(200), 1)
        self.assertEqual(keys_to_text(self.kb.events), "<ENTER>hi<ENTER>")


class NetinfoTests(unittest.TestCase):
    def test_parse_ip_addr(self):
        out = ("1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever\n"
               "3: wlan0    inet 192.168.86.42/24 brd 192.168.86.255 scope global dynamic wlan0\n"
               "5: tailscale0    inet 100.101.102.103/32 scope global tailscale0\n")
        self.assertEqual(parse_ip_addr(out), [("lo", "127.0.0.1"), ("wlan0", "192.168.86.42"),
                                              ("tailscale0", "100.101.102.103")])


if __name__ == "__main__":
    unittest.main()
