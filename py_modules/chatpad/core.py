"""Chatpad application logic, independent of HTTP and of Decky."""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from .keymap import normalize_text, text_to_strokes
from .security import FailureThrottle, RateLimiter, TokenManager
from .settings import MAX_ITEM_LEN, MAX_LIST, Settings
from .uinput import Typer

MAX_CHARS = 255  # WoW chat message limit
HISTORY_SIZE = 10

Result = Tuple[int, Dict[str, Any]]


class ChatpadCore:
    def __init__(self, settings: Settings, keyboard, *, sleep=time.sleep, clock=time.monotonic,
                 min_interval: float = 1.0) -> None:
        self.settings = settings
        self.keyboard = keyboard
        self.typer = Typer(keyboard, sleep=sleep)
        self.tokens = TokenManager()
        self.limiter = RateLimiter(min_interval, clock=clock)
        self.throttle = FailureThrottle(clock=clock)
        self.history: List[str] = []
        self.last_send: Optional[Dict[str, Any]] = None
        self.sends = 0
        self._busy = threading.Lock()
        self._state_lock = threading.Lock()

    # ---- auth -------------------------------------------------------------
    def authorize(self, token: Optional[str], ip: str) -> Optional[Result]:
        """Return an error Result if the request must be rejected, else None."""
        if self.throttle.blocked(ip):
            return 429, {"ok": False, "error": "Too many bad tokens. Wait a minute."}
        if not self.tokens.check(token):
            self.throttle.record(ip)
            return 401, {"ok": False, "error": "Bad or expired token. Rescan the QR code on the Deck."}
        return None

    def rotate_token(self) -> str:
        self.throttle.reset()
        return self.tokens.rotate()

    # ---- state ------------------------------------------------------------
    def public_state(self) -> Dict[str, Any]:
        s = self.settings.snapshot()
        return {
            "ok": True,
            "chips": s["chips"],
            "phrases": s["phrases"],
            "history": list(self.history),
            "maxChars": MAX_CHARS,
            "openKey": s["open_key"],
            "lastSend": self.last_send,
        }

    # ---- sending ----------------------------------------------------------
    def send(self, text: Any, press_enter: Any = True) -> Result:
        if not isinstance(text, str):
            return 400, {"ok": False, "error": "text must be a string"}
        ascii_text, replaced = normalize_text(text)
        ascii_text = ascii_text.strip()
        if not ascii_text:
            return 400, {"ok": False, "error": "Nothing to send"}
        if len(ascii_text) > MAX_CHARS:
            return 413, {"ok": False, "error": f"Too long ({len(ascii_text)}/{MAX_CHARS})"}
        if not self._busy.acquire(blocking=False):
            return 409, {"ok": False, "error": "Still typing the previous message"}
        try:
            if not self.limiter.try_acquire():
                wait = self.limiter.retry_after()
                return 429, {"ok": False, "error": "Slow down (1 message per second)",
                             "retryAfter": round(wait, 2)}
            s = self.settings.snapshot()
            open_key = s["open_key"]
            body = ascii_text
            if open_key == "slash":
                if body.startswith("/"):
                    body = body[1:]
                else:
                    open_key = "enter"  # plain text: '/' would corrupt it, so open with Enter
            strokes = text_to_strokes(body)
            started = time.time()
            try:
                self.typer.type_message(strokes, open_key=open_key, press_enter=bool(press_enter),
                                        key_delay_ms=s["key_delay_ms"], open_delay_ms=s["open_delay_ms"])
            except Exception as e:  # uinput failures etc.
                self._record(ascii_text, replaced, False, f"{type(e).__name__}: {e}")
                return 503, {"ok": False, "error": f"Typing failed on the Deck: {e}"}
            self._record(ascii_text, replaced, True, None, time.time() - started)
            return 200, {"ok": True, "typed": ascii_text, "replaced": replaced,
                         "history": list(self.history)}
        finally:
            self._busy.release()

    def _record(self, text: str, replaced: int, ok: bool, error: Optional[str],
                duration: float = 0.0) -> None:
        with self._state_lock:
            if ok:
                self.sends += 1
                if text in self.history:
                    self.history.remove(text)
                self.history.insert(0, text)
                del self.history[HISTORY_SIZE:]
            self.last_send = {
                "time": time.time(),
                "chars": len(text),
                "preview": text[:40],
                "replaced": replaced,
                "ok": ok,
                "error": error,
                "duration": round(duration, 2),
            }

    # ---- phrases / chips --------------------------------------------------
    def edit_list(self, kind: Any, action: Any, item: Any) -> Result:
        if kind not in ("phrases", "chips"):
            return 400, {"ok": False, "error": "kind must be phrases or chips"}
        if action not in ("add", "remove"):
            return 400, {"ok": False, "error": "action must be add or remove"}
        current = self.settings.get(kind)
        if kind == "phrases":
            if not isinstance(item, str) or not item.strip():
                return 400, {"ok": False, "error": "phrase must be non-empty text"}
            item = item.strip()[:MAX_ITEM_LEN]
            if action == "add":
                if item in current:
                    current.remove(item)
                current.append(item)
            else:
                current = [p for p in current if p != item]
        else:
            if not isinstance(item, dict) or not str(item.get("prefix", "")).strip():
                return 400, {"ok": False, "error": "chip needs a prefix"}
            prefix = str(item["prefix"])
            if action == "add":
                if prefix and not prefix.endswith(" "):
                    prefix += " "
                current = [c for c in current if c["prefix"] != prefix]
                current.append({"label": str(item.get("label") or prefix.strip()), "prefix": prefix})
            else:
                current = [c for c in current if c["prefix"] != prefix]
        if action == "add" and len(current) > MAX_LIST:
            return 400, {"ok": False, "error": f"Max {MAX_LIST} items"}
        self.settings.set(kind, current)
        return 200, self.public_state()
