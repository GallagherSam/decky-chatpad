"""Chatpad application logic, independent of HTTP and of Decky."""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from .keymap import normalize_text, text_to_strokes
from .security import FailureThrottle, RateLimiter, TokenManager
from .settings import MAX_ITEM_LEN, MAX_LIST, MODES, Settings
from .uinput import KEY_ACTIONS, Typer

MAX_CHARS = 255  # WoW chat message limit
HISTORY_SIZE = 10
KEY_MIN_INTERVAL = 0.25  # key-row buttons: one press per tap, but Tab-Tab-Tab shouldn't feel sluggish

# Settings the phone page may change (everything else is QAM-only).
PHONE_PREFS = {"mode": "mode", "clearBefore": "clear_before_typing"}

Result = Tuple[int, Dict[str, Any]]


class ChatpadCore:
    def __init__(self, settings: Settings, keyboard, *, sleep=time.sleep, clock=time.monotonic,
                 min_interval: float = 1.0, key_min_interval: float = KEY_MIN_INTERVAL) -> None:
        self.settings = settings
        self.keyboard = keyboard
        self.typer = Typer(keyboard, sleep=sleep)
        self.tokens = TokenManager()
        self.limiter = RateLimiter(min_interval, clock=clock)
        self.key_limiter = RateLimiter(key_min_interval, clock=clock)
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
            "mode": s["mode"],
            "clearBefore": s["clear_before_typing"],
            "clearMethod": s["clear_method"],
            "keys": list(KEY_ACTIONS),
            "lastSend": self.last_send,
        }

    # ---- sending ----------------------------------------------------------
    def send(self, text: Any, press_enter: Any = True, mode: Any = None, clear: Any = None) -> Result:
        """Type `text`. mode: 'chat' (open chat first) or 'field' (type into the focused field);
        None uses the saved mode. clear: Field mode only, empty the field first; None uses the setting."""
        if mode is None:
            mode = self.settings.get("mode")
        if mode not in MODES:
            return 400, {"ok": False, "error": "mode must be chat or field"}
        if clear is not None and not isinstance(clear, bool):
            return 400, {"ok": False, "error": "clear must be true or false"}
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
            body = ascii_text
            clear_method = None
            if mode == "field":
                open_key = "none"
                if clear if clear is not None else s["clear_before_typing"]:
                    clear_method = s["clear_method"]
            else:
                open_key = s["open_key"]
                if open_key == "slash":
                    if body.startswith("/"):
                        body = body[1:]
                    else:
                        open_key = "enter"  # plain text: '/' would corrupt it, so open with Enter
            strokes = text_to_strokes(body)
            started = time.time()
            try:
                self.typer.type_message(strokes, open_key=open_key, press_enter=bool(press_enter),
                                        key_delay_ms=s["key_delay_ms"], open_delay_ms=s["open_delay_ms"],
                                        clear=clear_method, clear_count=s["clear_backspace_count"])
            except Exception as e:  # uinput failures etc.
                self._record(ascii_text, replaced, False, f"{type(e).__name__}: {e}", mode=mode)
                return 503, {"ok": False, "error": f"Typing failed on the Deck: {e}"}
            self._record(ascii_text, replaced, True, None, time.time() - started, mode=mode)
            return 200, {"ok": True, "typed": ascii_text, "replaced": replaced, "mode": mode,
                         "cleared": clear_method is not None, "history": list(self.history)}
        finally:
            self._busy.release()

    def press_key(self, key: Any) -> Result:
        """Press one key-row button: tab, shift_tab, enter, esc or clear. Nothing else."""
        if key not in KEY_ACTIONS:
            return 400, {"ok": False, "error": "key must be one of " + ", ".join(KEY_ACTIONS)}
        if not self._busy.acquire(blocking=False):
            return 409, {"ok": False, "error": "Still typing the previous message"}
        try:
            if not self.key_limiter.try_acquire():
                return 429, {"ok": False, "error": "Slow down", "retryAfter": round(self.key_limiter.retry_after(), 2)}
            s = self.settings.snapshot()
            try:
                self.typer.press(key, key_delay_ms=s["key_delay_ms"], clear_method=s["clear_method"],
                                 clear_count=s["clear_backspace_count"])
            except Exception as e:
                return 503, {"ok": False, "error": f"Key press failed on the Deck: {e}"}
            return 200, {"ok": True, "key": key}
        finally:
            self._busy.release()

    def set_prefs(self, data: Any) -> Result:
        """Phone-side preferences (mode, clearBefore). Persisted, so the QAM sees them too."""
        if not isinstance(data, dict):
            return 400, {"ok": False, "error": "Expected a JSON object"}
        changes = {PHONE_PREFS[k]: v for k, v in data.items() if k in PHONE_PREFS}
        if not changes:
            return 400, {"ok": False, "error": "Nothing to change (mode, clearBefore)"}
        for k, v in changes.items():  # validate everything before saving anything
            if k == "clear_before_typing" and not isinstance(v, bool):
                return 400, {"ok": False, "error": "clearBefore must be true or false"}
            if k == "mode" and v not in MODES:
                return 400, {"ok": False, "error": "mode must be chat or field"}
        for k, v in changes.items():
            self.settings.set(k, v)
        return 200, self.public_state()

    def _record(self, text: str, replaced: int, ok: bool, error: Optional[str],
                duration: float = 0.0, mode: str = "chat") -> None:
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
                "mode": mode,
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
