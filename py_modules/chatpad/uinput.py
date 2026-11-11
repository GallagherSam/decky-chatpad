"""Minimal pure-Python virtual keyboard over /dev/uinput (no python-evdev needed).

Uses the legacy uinput setup path (write struct uinput_user_dev, then
UI_DEV_CREATE), which every kernel that has uinput supports.
"""

from __future__ import annotations

import os
import struct
import threading
import time
from typing import Callable, Iterable, List, Optional, Tuple

from .keymap import (ALL_KEYCODES, KEY_A, KEY_BACKSPACE, KEY_END, KEY_ENTER, KEY_ESC, KEY_LEFTCTRL,
                     KEY_LEFTSHIFT, KEY_SLASH, KEY_TAB, Stroke)

EV_SYN = 0x00
EV_KEY = 0x01
SYN_REPORT = 0
BUS_USB = 0x03

# ioctl numbers from linux/uinput.h ('U' = 0x55)
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565

UINPUT_MAX_NAME_SIZE = 80
ABS_CNT = 64
# struct input_event on 64-bit Linux: struct timeval (2 x long), u16 type, u16 code, s32 value
INPUT_EVENT = struct.Struct("@llHHi")
USER_DEV = struct.Struct("@%dsHHHHI%di" % (UINPUT_MAX_NAME_SIZE, ABS_CNT * 4))

DEVICE_NAME = b"Chatpad Virtual Keyboard"


def _make_ioctl() -> Callable[[int, int, int], None]:
    try:
        import fcntl

        def _ioctl(fd: int, req: int, arg: int) -> None:
            fcntl.ioctl(fd, req, arg)

        return _ioctl
    except Exception:  # pragma: no cover - fallback for frozen runtimes without fcntl
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)

        def _ioctl(fd: int, req: int, arg: int) -> None:
            if libc.ioctl(fd, ctypes.c_ulong(req), ctypes.c_int(arg)) != 0:
                err = ctypes.get_errno()
                raise OSError(err, os.strerror(err))

        return _ioctl


class UInputKeyboard:
    """A real virtual keyboard. Requires write access to /dev/uinput (root)."""

    def __init__(self, path: str = "/dev/uinput", keycodes: Iterable[int] = ALL_KEYCODES,
                 settle_s: float = 0.5) -> None:
        self.path = path
        self.keycodes = list(keycodes)
        self.settle_s = settle_s
        self.fd: Optional[int] = None

    def open(self) -> None:
        if self.fd is not None:
            return
        ioctl = _make_ioctl()
        fd = os.open(self.path, os.O_WRONLY | os.O_NONBLOCK)
        try:
            ioctl(fd, UI_SET_EVBIT, EV_KEY)
            ioctl(fd, UI_SET_EVBIT, EV_SYN)
            for code in self.keycodes:
                ioctl(fd, UI_SET_KEYBIT, code)
            dev = USER_DEV.pack(DEVICE_NAME, BUS_USB, 0x1209, 0xC4A7, 1, 0, *([0] * (ABS_CNT * 4)))
            os.write(fd, dev)
            ioctl(fd, UI_DEV_CREATE, 0)
        except Exception:
            os.close(fd)
            raise
        self.fd = fd
        # Give udev / the compositor time to notice the new device.
        time.sleep(self.settle_s)

    def emit(self, etype: int, code: int, value: int) -> None:
        if self.fd is None:
            raise RuntimeError("keyboard not open")
        now = time.time()
        sec = int(now)
        os.write(self.fd, INPUT_EVENT.pack(sec, int((now - sec) * 1e6), etype, code, value))

    def key(self, code: int, down: bool) -> None:
        self.emit(EV_KEY, code, 1 if down else 0)
        self.emit(EV_SYN, SYN_REPORT, 0)

    def close(self) -> None:
        if self.fd is None:
            return
        try:
            _make_ioctl()(self.fd, UI_DEV_DESTROY, 0)
        except Exception:
            pass
        try:
            os.close(self.fd)
        finally:
            self.fd = None


class RecordingKeyboard:
    """Test double: records (code, down) tuples instead of touching /dev/uinput."""

    def __init__(self) -> None:
        self.events: List[tuple] = []
        self.opened = False

    def open(self) -> None:
        self.opened = True

    def key(self, code: int, down: bool) -> None:
        self.events.append((code, down))

    def close(self) -> None:
        self.opened = False


OPEN_KEYS = ("enter", "slash", "none")
CLEAR_METHODS = ("select_all", "backspace")

# The only standalone keys the phone can press. Each maps to (keycode, modifiers).
# "clear" is handled separately because it is a short fixed sequence.
NAMED_KEYS = {
    "tab": (KEY_TAB, ()),
    "shift_tab": (KEY_TAB, (KEY_LEFTSHIFT,)),
    "enter": (KEY_ENTER, ()),
    "esc": (KEY_ESC, ()),
}
KEY_ACTIONS = tuple(NAMED_KEYS) + ("clear",)
MODIFIERS = (KEY_LEFTCTRL, KEY_LEFTSHIFT)


class Typer:
    """Turns a send request into key presses on a keyboard object (real or fake)."""

    def __init__(self, keyboard, sleep: Callable[[float], None] = time.sleep) -> None:
        self.kb = keyboard
        self.sleep = sleep
        self.lock = threading.Lock()

    def _combo(self, code: int, mods: Tuple[int, ...], delay_s: float) -> None:
        for m in mods:
            self.kb.key(m, True)
            self.sleep(delay_s / 2)
        self.kb.key(code, True)
        self.sleep(delay_s / 2)
        self.kb.key(code, False)
        for m in reversed(mods):
            self.sleep(delay_s / 2)
            self.kb.key(m, False)
        self.sleep(delay_s)

    def _tap(self, code: int, shift: bool, delay_s: float) -> None:
        self._combo(code, (KEY_LEFTSHIFT,) if shift else (), delay_s)

    def _clear(self, method: str, count: int, delay_s: float) -> None:
        """Empty the focused text field.

        select_all: Ctrl+A then BackSpace.
        backspace:  End, then BackSpace `count` times (for edit boxes without Ctrl+A).
        """
        if method == "select_all":
            self._combo(KEY_A, (KEY_LEFTCTRL,), delay_s)
            self._combo(KEY_BACKSPACE, (), delay_s)
        elif method == "backspace":
            self._combo(KEY_END, (), delay_s)
            for _ in range(max(0, int(count))):
                self._combo(KEY_BACKSPACE, (), delay_s)
        else:
            raise ValueError(f"unknown clear method {method!r}")

    def _release_modifiers(self) -> None:
        for m in MODIFIERS:
            try:
                self.kb.key(m, False)
            except Exception:
                pass

    def type_message(self, strokes: List[Stroke], *, open_key: str = "enter", press_enter: bool = True,
                     key_delay_ms: float = 12, open_delay_ms: float = 120,
                     clear: Optional[str] = None, clear_count: int = 64) -> None:
        """open_key: 'enter' presses Enter first; 'slash' presses '/' first and expects
        strokes to already exclude that leading slash; 'none' types straight away.
        clear: None, or a CLEAR_METHODS entry to empty the field before typing."""
        if clear and clear not in CLEAR_METHODS:
            raise ValueError(f"unknown clear method {clear!r}")
        delay = max(0.0, key_delay_ms) / 1000.0
        with self.lock:
            self.kb.open()
            try:
                if open_key == "enter":
                    self._tap(KEY_ENTER, False, delay)
                    self.sleep(open_delay_ms / 1000.0)
                elif open_key == "slash":
                    self._tap(KEY_SLASH, False, delay)
                    self.sleep(open_delay_ms / 1000.0)
                if clear:
                    self._clear(clear, clear_count, delay)
                for s in strokes:
                    self._tap(s.code, s.shift, delay)
                if press_enter:
                    self.sleep(delay)
                    self._tap(KEY_ENTER, False, delay)
            except Exception:
                # Never leave a modifier stuck down if something goes wrong mid-message.
                self._release_modifiers()
                raise

    def press(self, action: str, *, key_delay_ms: float = 12, clear_method: str = "select_all",
              clear_count: int = 64) -> None:
        """Press one of KEY_ACTIONS."""
        if action not in KEY_ACTIONS:
            raise ValueError(f"unknown key {action!r}")
        if action == "clear" and clear_method not in CLEAR_METHODS:
            raise ValueError(f"unknown clear method {clear_method!r}")
        delay = max(0.0, key_delay_ms) / 1000.0
        with self.lock:
            self.kb.open()
            try:
                if action == "clear":
                    self._clear(clear_method, clear_count, delay)
                else:
                    code, mods = NAMED_KEYS[action]
                    self._combo(code, mods, delay)
            except Exception:
                self._release_modifiers()
                raise
