import asyncio
import os

# Decky injects the `decky` module and appends this plugin's py_modules/ to sys.path.
import decky

from chatpad.core import ChatpadCore
from chatpad.netinfo import all_ips, primary_ip
from chatpad.server import ChatpadServer
from chatpad.settings import Settings
from chatpad.uinput import UInputKeyboard

SETTABLE = ("open_key", "key_delay_ms", "open_delay_ms", "port", "mode", "clear_before_typing",
            "clear_method", "clear_backspace_count")


class Plugin:
    core: ChatpadCore = None
    server: ChatpadServer = None
    keyboard: UInputKeyboard = None
    server_error: str = None
    uinput_error: str = None

    # ---- lifecycle ---------------------------------------------------------
    async def _main(self):
        settings = Settings(os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json"))
        self.keyboard = UInputKeyboard()
        self.core = ChatpadCore(settings, self.keyboard)
        self.server = ChatpadServer(self.core, decky.logger)
        # Create the virtual keyboard up front so the compositor has seen it before the first send.
        await asyncio.to_thread(self._open_keyboard)
        if settings.get("enabled"):
            await self._start_server()
        decky.logger.info("Chatpad loaded")

    async def _unload(self):
        if self.server:
            await asyncio.to_thread(self.server.stop)
        if self.keyboard:
            await asyncio.to_thread(self.keyboard.close)
        decky.logger.info("Chatpad unloaded")

    async def _uninstall(self):
        pass

    # ---- helpers -----------------------------------------------------------
    def _open_keyboard(self):
        try:
            self.keyboard.open()
            self.uinput_error = None
        except Exception as e:
            self.uinput_error = f"{type(e).__name__}: {e}"
            decky.logger.error("uinput open failed: %s", self.uinput_error)

    async def _start_server(self):
        port = self.core.settings.get("port")
        try:
            await asyncio.to_thread(self.server.start, "0.0.0.0", port)
            self.server_error = None
        except OSError as e:
            self.server_error = f"Could not listen on port {port}: {e.strerror or e}"
            decky.logger.error(self.server_error)

    # ---- frontend API ------------------------------------------------------
    async def get_status(self):
        s = self.core.settings.snapshot()
        ips = await asyncio.to_thread(all_ips)
        ip = ips[0]["ip"] if ips else primary_ip()
        port = self.server.port or s["port"]
        token = self.core.tokens.token
        return {
            "enabled": s["enabled"],
            "running": self.server.running,
            "serverError": self.server_error,
            "uinputOk": self.keyboard.fd is not None,
            "uinputError": self.uinput_error,
            "ip": ip,
            "ips": ips,
            "port": port,
            "url": f"http://{ip}:{port}/?t={token}",
            "token": token,
            "openKey": s["open_key"],
            "keyDelayMs": s["key_delay_ms"],
            "openDelayMs": s["open_delay_ms"],
            "mode": s["mode"],
            "clearBefore": s["clear_before_typing"],
            "clearMethod": s["clear_method"],
            "clearBackspaceCount": s["clear_backspace_count"],
            "sends": self.core.sends,
            "lastSend": self.core.last_send,
        }

    async def set_enabled(self, enabled: bool):
        self.core.settings.set("enabled", bool(enabled))
        if enabled:
            await self._start_server()
        else:
            await asyncio.to_thread(self.server.stop)
            self.server_error = None
        return await self.get_status()

    async def rotate_token(self):
        self.core.rotate_token()
        decky.logger.info("token rotated")
        return await self.get_status()

    async def set_setting(self, key: str, value):
        if key not in SETTABLE:
            raise ValueError(f"unknown setting {key}")
        self.core.settings.set(key, value)
        if key == "port" and self.server.running:
            await asyncio.to_thread(self.server.stop)
            await self._start_server()
        return await self.get_status()

    async def retry_uinput(self):
        await asyncio.to_thread(self._open_keyboard)
        return await self.get_status()
