"""Check a published release from outside, as an installed copy would see it:

    .venv/bin/python tools/verify_release.py [vX.Y.Z] [--mac-only]

1. Both update lists at releases/latest/download name this version, with this tag's files.
2. Each download is the length the list says and matches its EdDSA signature against the
   app's public key (what Sparkle and WinSparkle check before installing).
3. The Mac zip's app passes codesign and Gatekeeper, and says this version.

Everything is downloaded into one temporary folder that's always removed at the end, and the
unzipped app is taken out of macOS's app list (LaunchServices) first. It's never run. A
copy left behind in the temporary folder caused a "Magpie.app is damaged" message on
2026-11-15: macOS registers any app it sees, then clears old temporary files a piece at a
time, and what's left looks damaged.
"""
import argparse
import base64
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from build_app_support import SPARKLE_PUBLIC_KEY  # noqa: E402
from rplmaker import APP_NAME, VERSION  # noqa: E402

REPO = "Matthew2244/rpl-maker"
LATEST = f"https://github.com/{REPO}/releases/latest/download/"
LSREGISTER = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/"
              "Support/lsregister")
ED25519_DER_PREFIX = bytes.fromhex("302a300506032b6570032100")


def fetch(url: str, dest: str | None = None) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}-release-check"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    if dest:
        with open(dest, "wb") as f:
            f.write(data)
        return None
    return data


def openssl() -> str:
    for c in ("/opt/homebrew/bin/openssl", "/usr/local/bin/openssl", shutil.which("openssl")):
        if c and os.path.exists(c):
            return c
    sys.exit("No openssl to check the EdDSA signatures with.")


def check_signature(path: str, sig_b64: str, tmp: str) -> bool:
    pub = os.path.join(tmp, "public.der")
    with open(pub, "wb") as f:
        f.write(ED25519_DER_PREFIX + base64.b64decode(SPARKLE_PUBLIC_KEY))
    sig = os.path.join(tmp, "signature")
    with open(sig, "wb") as f:
        f.write(base64.b64decode(sig_b64))
    r = subprocess.run([openssl(), "pkeyutl", "-verify", "-pubin", "-inkey", pub, "-keyform", "DER", "-rawin",
                        "-in", path, "-sigfile", sig], capture_output=True, text=True)
    return r.returncode == 0


def check_list(name: str, tag: str, tmp: str, problems: list) -> str | None:
    """One update list: version, link, length, signature. Returns the downloaded file."""
    # GitHub can serve the previous release's list for a minute or two after an upload
    for attempt in range(12):
        try:
            xml = fetch(LATEST + name).decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            problems.append(f"{name}: couldn't be read ({e})")
            return None
        if f"<sparkle:shortVersionString>{tag.lstrip('v')}<" in xml:
            break
        print(f"{name}: not showing {tag} yet, looking again in 15 seconds")
        time.sleep(15)
    v = re.search(r"<sparkle:shortVersionString>([^<]+)<", xml)
    enc = re.search(r'<enclosure url="([^"]+)" sparkle:edSignature="([^"]+)" length="(\d+)"', xml)
    if not v or v.group(1) != tag.lstrip("v"):
        problems.append(f"{name}: names version {v.group(1) if v else 'none'}, not {tag.lstrip('v')}")
    if not enc:
        problems.append(f"{name}: no signed download in it")
        return None
    url, sig, length = enc.group(1), enc.group(2), int(enc.group(3))
    if f"/download/{tag}/" not in url:
        problems.append(f"{name}: points at {url}, not this release")
    path = os.path.join(tmp, os.path.basename(url))
    try:
        fetch(url, path)
    except Exception as e:  # noqa: BLE001
        problems.append(f"{name}: its download couldn't be fetched ({e})")
        return None
    if os.path.getsize(path) != length:
        problems.append(f"{name}: download is {os.path.getsize(path)} bytes, the list says {length}")
    if not check_signature(path, sig, tmp):
        problems.append(f"{name}: the download doesn't match its EdDSA signature")
    print(f"{name}: version {v.group(1) if v else '?'}, {os.path.basename(url)}, {length:,} bytes, "
          "signature checked")
    return path


def check_mac_app(zip_path: str, tmp: str, problems: list) -> None:
    out = os.path.join(tmp, "unzipped")
    app = os.path.join(out, f"{APP_NAME}.app")
    try:
        subprocess.run(["ditto", "-x", "-k", zip_path, out], check=True)
        cs = subprocess.run(["codesign", "--verify", "--deep", "--strict", app], capture_output=True, text=True)
        if cs.returncode:
            problems.append("codesign: " + (cs.stderr.strip() or "failed"))
        gk = subprocess.run(["spctl", "--assess", "--type", "execute", "-vv", app], capture_output=True, text=True)
        print(gk.stderr.strip())
        if gk.returncode or "Notarized Developer ID" not in gk.stderr:
            problems.append("Gatekeeper: " + gk.stderr.strip())
        pv = subprocess.run(["plutil", "-extract", "CFBundleShortVersionString", "raw",
                             os.path.join(app, "Contents", "Info.plist")], capture_output=True, text=True).stdout.strip()
        if pv != VERSION:
            problems.append(f"the Mac app says {pv}, not {VERSION}")
    finally:
        if os.path.isdir(app):
            subprocess.run([LSREGISTER, "-u", app], capture_output=True)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("tag", nargs="?", default="v" + VERSION)
    p.add_argument("--mac-only", action="store_true", help="skip the Windows update list")
    a = p.parse_args()
    problems: list = []
    tmp = tempfile.mkdtemp(prefix="rplmaker-verify-")
    try:
        z = check_list("appcast.xml", a.tag, tmp, problems)
        if z and sys.platform == "darwin":
            check_mac_app(z, tmp, problems)
        if not a.mac_only:
            check_list("appcast-windows.xml", a.tag, tmp, problems)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if os.path.exists(tmp):
        problems.append(f"the temporary folder {tmp} couldn't be removed")
    if problems:
        print("Release check FAILED:\n  " + "\n  ".join(problems))
        return 1
    print(f"Release check OK: {a.tag} as an installed copy sees it. Nothing left behind.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
