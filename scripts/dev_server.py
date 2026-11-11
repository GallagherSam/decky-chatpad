#!/usr/bin/env python3
"""Run the phone page + API on your PC with a fake keyboard that prints what it would type.

    python3 scripts/dev_server.py [port]

Then open the printed URL on your phone (same network) or desktop browser.
"""
import logging
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "py_modules"))

from chatpad.core import ChatpadCore  # noqa: E402
from chatpad.keymap import KEY_ENTER, KEY_LEFTSHIFT, KEYMAP  # noqa: E402
from chatpad.netinfo import primary_ip  # noqa: E402
from chatpad.server import ChatpadServer  # noqa: E402
from chatpad.settings import Settings  # noqa: E402

REV = {(s.code, s.shift): ch for ch, s in KEYMAP.items()}


class PrintKeyboard:
    fd = 1

    def __init__(self):
        self.shift = False

    def open(self):
        pass

    def close(self):
        pass

    def key(self, code, down):
        if code == KEY_LEFTSHIFT:
            self.shift = down
        elif down:
            sys.stdout.write("⏎\n" if code == KEY_ENTER else REV.get((code, self.shift), "?"))
            sys.stdout.flush()


def main():
    logging.basicConfig(level=logging.INFO)
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    settings = Settings(os.path.join(tempfile.gettempdir(), "chatpad-dev-settings.json"))
    core = ChatpadCore(settings, PrintKeyboard())
    srv = ChatpadServer(core)
    srv.start("0.0.0.0", port)
    print(f"Open: http://{primary_ip()}:{port}/?t={core.tokens.token}")
    try:
        srv.thread.join()
    except KeyboardInterrupt:
        srv.stop()


if __name__ == "__main__":
    main()
