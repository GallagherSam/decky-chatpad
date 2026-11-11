#!/usr/bin/env python3
"""Build the "Install plugin from ZIP" archive without the Decky CLI.

Mirrors what `decky plugin build` (SteamDeckHomebrew/cli, src/cli/plugin/build.rs) puts in the zip:

    Chatpad/LICENSE, README.md, main.py, package.json, plugin.json
    Chatpad/dist/index.js
    Chatpad/py_modules/...   (no __pycache__)

Run `pnpm run build` first so dist/index.js exists. Output: out/Chatpad.zip
"""
import json
import os
import sys
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FILES = ["LICENSE", "README.md", "main.py", "package.json", "plugin.json"]
DIRS = ["dist", "py_modules", "defaults", "bin"]
SKIP_EXT = (".map", ".pyc")


def main() -> int:
    name = json.load(open(os.path.join(ROOT, "plugin.json")))["name"]
    if not os.path.isfile(os.path.join(ROOT, "dist", "index.js")):
        print("dist/index.js missing: run `pnpm run build` first", file=sys.stderr)
        return 1
    out_dir = os.path.join(ROOT, "out")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{name}.zip")

    entries = []
    for f in FILES:
        entries.append((os.path.join(ROOT, f), f"{name}/{f}"))
    for d in DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(x for x in dirnames if x != "__pycache__")
            for fn in sorted(filenames):
                if fn.endswith(SKIP_EXT) or (d == "defaults" and fn == "defaults.txt"):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, ROOT)
                if d == "defaults":  # CLI flattens defaults/ into the plugin root
                    rel = os.path.relpath(full, base)
                entries.append((full, f"{name}/{rel}"))

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for full, arc in entries:
            info = zipfile.ZipInfo(arc, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if arc.endswith((".py",)) or "/bin/" in arc else 0o644) << 16
            with open(full, "rb") as fh:
                z.writestr(info, fh.read())

    # Same check Decky Loader does on install (browser.py): exactly one <dir>/plugin.json at depth 1.
    with zipfile.ZipFile(out) as z:
        pj = [n for n in z.namelist() if n.endswith("/plugin.json") and n.count("/") == 1]
        assert len(pj) == 1, pj
        for f in z.namelist():
            print(f)
    print(f"\nWrote {out} ({os.path.getsize(out)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
