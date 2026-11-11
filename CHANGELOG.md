# Changelog

## 0.2.0 (2026-11-11)

- **Field mode.** A Chat / Field switch at the top of the phone page. Field mode types into whatever text box is focused (Auction House search, mail, etc.) without pressing the open-chat key. The mode is saved on the Deck and shown in the QAM, and each send carries the mode, so a stale phone page can't type in the wrong one.
- **Clear first** (Field mode): empties the focused field before typing.
- **Key row** on the phone page: Tab, Shift+Tab, Enter, Esc and Clear. One tap presses one key; token-checked and rate-limited (4 per second). There's still no arbitrary key or macro API.
- **Clear method** setting in the QAM: Ctrl+A then Backspace (default), or End then Backspace N times for edit boxes that ignore Ctrl+A.
- The Enter checkbox is remembered per mode (on for Chat, off for Field by default).
- The virtual keyboard now also advertises Left Ctrl and End.
- New API endpoints: `POST /api/key`, `POST /api/prefs`. `POST /api/send` accepts `mode` and `clear`.

## 0.1.0

- First release: type on your phone, Chatpad opens chat in the game and types it. Channel chips, quick phrases, recent messages, QR pairing, rate limiting. Tested on a Steam Deck in World of Warcraft.
