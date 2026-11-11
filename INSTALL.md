# Installing Chatpad

Chatpad isn't in the Decky plugin store, so you install it from a zip file. It takes about 10 minutes the first time, and most of that is installing Decky Loader.

You need:

- A Steam Deck (or another SteamOS device)
- A phone on the same Wi-Fi as the Deck (any phone with a browser and a camera works)
- A sudo password set on the Deck, for the Decky installer. If you've never set one, open Konsole in Desktop Mode and run `passwd`.

## 1. Install Decky Loader

Skip this step if you already have Decky.

1. Press the **Steam** button, then **Power**, then **Switch to Desktop**.
2. In a browser, go to <https://decky.xyz> and click **Download**.
3. Open your Downloads folder in Dolphin and double-click `decky_installer.desktop`. If it asks, choose **Execute**.
4. Type your sudo password when asked, then choose **Release**.
5. When it finishes, double-click **Return to Gaming Mode** on the desktop.

## 2. Turn on Decky developer mode

Developer mode is what allows installing plugins from a zip.

1. In Gaming Mode, press the **...** button to open the Quick Access Menu (QAM).
2. Open the Decky tab (the plug icon), then the **gear** icon in the top right.
3. Under **General**, switch on **Developer mode**.

## 3. Download Chatpad

Download `Chatpad.zip` from the [latest release](https://github.com/GallagherSam/decky-chatpad/releases/latest) and save it to the Deck, for example to `~/Downloads`.

Two easy ways to get it onto the Deck:

- **On the Deck itself:** in Desktop Mode, open the release page in the browser and download the zip. Or, in Gaming Mode, use the Steam browser.
- **From another computer:** run `scp Chatpad.zip deck@steamdeck.local:/home/deck/Downloads/`. This needs SSH enabled on the Deck (`sudo systemctl enable --now sshd` in Konsole).

Don't unzip it. Decky installs the zip as-is.

## 4. Install the plugin

1. Open the QAM, then **Decky**, then the **gear** icon, then **Developer**.
2. Choose **Install Plugin from ZIP File**, browse to `Chatpad.zip` and confirm with **Install**.
3. Open the Decky tab again. **Chatpad** should be in the list with a keyboard icon. If it isn't, reboot the Deck once.

## 5. Pair your phone

1. Open **Chatpad** in the QAM and make sure **Phone keyboard** is on. It should say "Listening on port 8765".
2. Scan the QR code with your phone's camera and open the link. A dark Chatpad page opens with a green dot in the top-left corner.
3. Optional: add the page to your home screen. On iPhone, tap **Share** then **Add to Home Screen**. On Android, use the browser menu then **Add to Home screen**.

## 6. Use it

1. Launch your game.
2. **Close the QAM.** Keys go to whatever has focus, and while the QAM or the Steam overlay is open, that isn't the game.
3. Type or dictate on your phone and tap **Send**. Chatpad opens chat, types the text and presses Enter.

The first time, send a test message somewhere quiet. In WoW, `/s` is visible to players nearby.

## Troubleshooting

| Problem | Fix |
|---|---|
| Phone page won't load, or the dot is red | Check that the phone and Deck are on the same Wi-Fi and that the phone hasn't fallen back to cellular. Turn Chatpad off and on in the QAM. |
| "Bad or expired token" | Scan the QR code again. A new pairing code is made on every reboot, on every plugin reload, and when you tap **New pairing code**. |
| Sent, but nothing typed in the game | The QAM or Steam overlay was probably open. Close it and try again, then check **Last send** in the QAM for an error. |
| Letters dropped | Raise **Key delay** in the QAM (try 25 ms). |
| First few letters missing | Raise **Wait after opening chat** (try 250 ms). |
| Symbols come out wrong | Chatpad types using a US keyboard layout. Set the Deck's keyboard layout to US English. |
| "Could not listen on port 8765" | Another app is using that port. Reboot the Deck, and open an issue if it keeps happening. |
| A "Retry virtual keyboard" button appears | Tap it. If it keeps failing, open an issue and include the error text shown under the button. |

Using Tailscale? The QAM also shows your Tailscale IP. Open `http://<that IP>:8765/?t=<token>` on your phone, using the same `t=` value as in the QR link.

## Updating and removing

- **Update:** download the new zip and install it the same way. It replaces the old version.
- **Remove:** open the QAM, then **Decky**, then the **gear** icon, then **Plugins**, and uninstall Chatpad.

## Before you use it on public Wi-Fi

The phone page uses plain HTTP on your local network. Anyone on the same network who is sniffing traffic could read your messages and the pairing token. That's fine at home, but on hotel or café Wi-Fi either turn Chatpad off or connect over Tailscale.
