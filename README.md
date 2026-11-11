# Chatpad

A [Decky Loader](https://decky.xyz) plugin for the Steam Deck: **type on your phone, and the text is typed into the game on your Deck.**

Built for MMO chat. The motivating case is World of Warcraft played in Gaming Mode with WoW's native gamepad UI, where the on-screen keyboard is slow and unreliable. Nothing in it is WoW-specific, though. WoW slash commands are just the default channel chips, and it works in anything that takes keyboard input.

## How it works

1. The plugin's Python backend (running as root) creates a virtual USB keyboard through `/dev/uinput`. It is plain Python with `ioctl`/`struct` and no compiled dependencies.
2. It serves a small, self-contained web page on your LAN (default port `8765`).
3. You scan a QR code in the Quick Access Menu with your phone. The link includes a random pairing token.
4. You type or dictate on the phone and tap **Send**. The Deck presses Enter to open chat, types your text, and presses Enter again.

## Features

- Phone page: big text box that works with dictation and autocorrect. Return sends.
- Channel chips (`/s`, `/p`, `/g`, `/raid`, `/w`, `/r`, `/2` Trade, `/1` General, `/y`). Tap one to prefix your message. The list is editable.
- Quick phrases, stored on the Deck, that send in one tap. You can add and remove them from the phone.
- The last 10 sent messages, tap one to resend it.
- A "type only" mode: switch off **Enter** to type the text without submitting it.
- A warning when your text contains characters that can't be typed (see Limitations).
- QAM panel: on/off switch, QR code and URL (LAN and Tailscale IPs), new-pairing-code button, open-chat key (Enter, `/` or none), key delay, delay after opening chat, and the status of the last send.

## Install (sideload)

The plugin isn't in the Decky store yet.

1. Install Decky Loader: in Desktop Mode, download the installer from <https://decky.xyz> and run it.
2. Turn on developer mode: in Gaming Mode open the QAM (`...` button), go to Decky, then the gear icon, then General, and enable **Developer mode**.
3. Copy `Chatpad.zip` to the Deck, for example to `~/Downloads`.
4. In Decky settings, open **Developer**, choose **Install Plugin from ZIP File**, pick `Chatpad.zip` and confirm.

### Building the zip yourself

You need Node 18+ with pnpm 9, and Python 3.10+ for the tests and packaging.

```bash
pnpm install
pnpm run build             # -> dist/index.js
python3 scripts/package.py # -> out/Chatpad.zip
# or both in one go: pnpm run package
```

The official Decky CLI (`decky plugin build`) also works if your system can run it (it needs glibc 2.39 or newer plus Docker). `scripts/package.py` produces the same layout:

```
Chatpad/
  LICENSE  README.md  main.py  package.json  plugin.json
  dist/index.js
  py_modules/chatpad/{__init__,core,keymap,netinfo,security,server,settings,uinput}.py
  py_modules/chatpad/web/index.html
```

## Usage

1. Open the QAM, then Decky, then **Chatpad**. Make sure **Phone keyboard** is on.
2. Scan the QR code with your phone's camera and open the link. Your phone has to be on the same network as the Deck (same Wi-Fi, or both on your tailnet, in which case use the Tailscale IP shown).
3. **Close the QAM.** Keys go to whatever has focus, and while the QAM is open that's Steam, not the game.
4. Type on the phone and hit Send.

Tips:
- If letters go missing, raise **Key delay** (the default is 12 ms per key).
- If the first characters go missing, raise **Wait after opening chat**.
- **Open chat with**:
  - `Enter` is the default.
  - `/` presses slash to open chat and is only used for messages that start with `/`. Other messages still open with Enter.
  - `None` is for when you've already opened the chat box yourself.
- To whisper, tap **Whisper** and type `Name your message`.

## Security model

- The page and API are served over plain HTTP on your LAN. Anyone on the same network can load the page, but every API call needs the pairing token, sent in an `X-Chatpad-Token` header and compared in constant time.
- A new random token (96 bits) is generated every time the plugin loads. **New pairing code** in the QAM rotates it immediately, which disconnects any phone holding the old link.
- Bad tokens are counted per IP. After 20 failures in a minute that IP gets locked out for the rest of the minute.
- Because the token travels in a custom header, browsers send a CORS preflight that Chatpad never approves. Other websites open on your phone can't make requests to it.
- Limits: 1 message per second, 255 characters (WoW's chat limit), 8 KB request bodies, one message being typed at a time.
- The only thing the API can do is "type this text, optionally followed by Enter". It can't press arbitrary keys, use modifiers (other than Shift, for capitals and symbols), send macros or move the mouse.
- Plain HTTP means someone sniffing your Wi-Fi could read your messages and the token. Don't use Chatpad on networks you don't trust. Turn it off in the QAM when you aren't using it.
- The backend runs as root because only root can open `/dev/uinput`. That's the standard Decky `"flags": ["root"]` mechanism.

## Blizzard / anti-cheat note

Each tap on the phone types **one** message, exactly as if you'd typed it on a USB keyboard. It doesn't automate gameplay, run on a timer or loop, and it can't send anything you didn't tap Send for. The rate limit enforces this. Treat it like a physical keyboard plugged into the Deck. As always, how you use any input device is your responsibility under the game's terms of service.

## Limitations (v1)

- **ASCII only, US layout.** Curly quotes, dashes and the ellipsis that phone keyboards insert are converted to plain ASCII, and accents are stripped (`café` becomes `cafe`). Anything else, such as emoji or CJK text, is typed as `?`, and the page warns you before you send. If the Deck's keyboard layout isn't US, symbols may come out wrong.
- The phone and the Deck must be able to reach each other: same Wi-Fi, or a tailnet.
- Typing speed is about 40 characters per second at the default delay, so a 255-character message takes around 6 seconds.

## Development

```bash
python3 -m unittest discover -s tests   # backend tests, uinput mocked
python3 scripts/dev_server.py           # serve the phone page from your PC; the "keyboard" prints to stdout
```

Code layout:
- `main.py`: the Decky `Plugin` class (lifecycle and the callables the QAM panel uses).
- `py_modules/chatpad/`:
  - `keymap.py`: text to keycodes.
  - `uinput.py`: virtual keyboard and typer.
  - `security.py`: token, rate limiting, failure throttle.
  - `server.py`: stdlib `http.server`.
  - `core.py`: send logic, history, phrases.
  - `settings.py`: JSON settings.
  - `netinfo.py`: IP detection.
  - `web/index.html`: the phone page.
- `src/index.tsx`: the QAM panel. The QR code is generated on the Deck with the bundled [`uqr`](https://github.com/unjs/uqr).

The backend uses only the Python standard library. Decky's bundled interpreter ships `http.server` and `socketserver` explicitly (see decky-loader's `pyinstaller.spec`). If `fcntl` turns out to be unavailable in the frozen runtime, `ioctl` falls back to `ctypes`.

## License

MIT. See [LICENSE](LICENSE). The build scaffolding comes from [decky-plugin-template](https://github.com/SteamDeckHomebrew/decky-plugin-template) (BSD-3-Clause, notice included).
