"""Finish a release from the Studio: python tools/release_mac.py v0.2.0 [--notes NOTES.md] [--no-upload]

The release and its tag must already exist on GitHub. CI builds the Windows installer from the
tag and attaches it. This, run on the Mac that holds the keys (they never go to CI):

1. builds with PyInstaller, signing every binary with the Developer ID and the hardened runtime;
2. notarizes with the App Store Connect API key in the Keychain, staples, checks Gatekeeper,
   runs the signed app's self-test;
3. writes appcast.xml (Mac) and, once CI has attached the installer, appcast-windows.xml,
   both signed with this app's EdDSA key (tools/appcast.py);
4. uploads the Mac zip and both update lists to the release (not with --no-upload).
"""
import argparse
import base64
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from rplmaker import APP_NAME, VERSION  # noqa: E402

REPO = "Matthew2244/rpl-maker"


def run(cmd, **kw):
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=True, text=True, **kw)


def developer_id() -> str:
    out = subprocess.run(["security", "find-identity", "-v", "-p", "codesigning"], capture_output=True, text=True).stdout
    ids = re.findall(r'"(Developer ID Application: [^"]+)"', out)
    if not ids:
        sys.exit("No Developer ID Application certificate in the Keychain.")
    return ids[0]


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("tag")
    p.add_argument("--notes", help="release notes as plain Markdown, for the update window")
    p.add_argument("--key-id", default="44L73HXU2W")
    p.add_argument("--issuer", default="4eeb658c-79f1-4dc6-bb6f-54db15d61ce8")
    p.add_argument("--keychain-service", default="asc-api-key")
    p.add_argument("--no-upload", action="store_true")
    p.add_argument("--windows-only", action="store_true",
                   help="only the Windows update list, once CI has attached the installer (no rebuild)")
    a = p.parse_args()
    if a.tag.lstrip("v") != VERSION:
        sys.exit(f"The tag says {a.tag} but the app says {VERSION}.")
    os.chdir(ROOT)
    if a.windows_only:
        windows_list(a)
        return
    ident = developer_id()
    print("Signing as:", ident)
    # .venv-release: python-build-standalone 3.13 (macOS 11+), not Homebrew's (macOS 26 only)
    py = os.path.join(ROOT, ".venv-release", "bin", "python")
    run([py if os.path.exists(py) else sys.executable, "build_app.py"], env=dict(os.environ, RPLMAKER_SIGN_ID=ident))
    app = os.path.join("dist", f"{APP_NAME}.app")
    run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", app])
    with tempfile.TemporaryDirectory() as tmp:
        p8 = os.path.join(tmp, f"AuthKey_{a.key_id}.p8")
        b64 = subprocess.run(["security", "find-generic-password", "-s", a.keychain_service, "-a", a.key_id, "-w"],
                             capture_output=True, text=True, check=True).stdout.strip()
        with open(p8, "wb") as f:
            f.write(base64.b64decode(b64))
        os.chmod(p8, 0o600)
        upload = os.path.join(tmp, "notarize.zip")
        run(["ditto", "-c", "-k", "--keepParent", app, upload])
        res = subprocess.run(["xcrun", "notarytool", "submit", upload, "--key", p8, "--key-id", a.key_id,
                              "--issuer", a.issuer, "--wait"], capture_output=True, text=True)
        print(res.stdout, res.stderr)
        if "status: Accepted" not in res.stdout:
            sub = re.search(r"id: ([0-9a-f-]{36})", res.stdout)
            if sub:
                subprocess.run(["xcrun", "notarytool", "log", sub.group(1), "--key", p8, "--key-id", a.key_id,
                                "--issuer", a.issuer])
            sys.exit("Apple did not accept the app. The log above says why.")
    run(["xcrun", "stapler", "staple", app])
    run(["spctl", "--assess", "--type", "execute", "--verbose=2", app])
    out = os.path.join("dist", f"{APP_NAME}-mac.zip")
    if os.path.exists(out):
        os.remove(out)
    run(["ditto", "-c", "-k", "--keepParent", app, out])
    with tempfile.TemporaryFile("w+") as log:
        subprocess.run([os.path.join(app, "Contents", "MacOS", APP_NAME), "--self-test"], stdout=log,
                       stderr=subprocess.STDOUT, timeout=120)
        log.seek(0)
        text = log.read().strip()
    print(text.splitlines()[-1] if text else "(no self-test output)")
    if "Self-test: OK" not in text:
        sys.exit("The signed app did not pass its self-test.")

    base = f"https://github.com/{REPO}/releases/download/{a.tag}"
    notes = ["--notes", a.notes] if a.notes else []
    cast = os.path.join("dist", "appcast.xml")
    with open(cast, "w") as f:
        run([sys.executable, os.path.join("tools", "appcast.py"), out, VERSION, f"{base}/{os.path.basename(out)}"]
            + notes, stdout=f)
    if not a.no_upload:
        run(["gh", "release", "upload", a.tag, "-R", REPO, out, cast, "--clobber"])
    windows_list(a)


def windows_list(a):
    """appcast-windows.xml for the installer CI attached to the release, signed and uploaded."""
    base = f"https://github.com/{REPO}/releases/download/{a.tag}"
    notes = ["--notes", a.notes] if a.notes else []
    setup = os.path.join("dist", f"{APP_NAME}-Setup.exe")
    if os.path.exists(setup):
        os.remove(setup)
    got = subprocess.run(["gh", "release", "download", a.tag, "-R", REPO, "-p", f"{APP_NAME}-Setup.exe", "-D", "dist"],
                         capture_output=True, text=True)
    if got.returncode != 0 or not os.path.exists(setup):
        print("The Windows installer isn't on the release yet (CI still building?). When it is, run: "
              f"tools/release_mac.py {a.tag} --windows-only" + (f" --notes {a.notes}" if a.notes else ""))
        return
    wcast = os.path.join("dist", "appcast-windows.xml")
    with open(wcast, "w") as f:
        run([sys.executable, os.path.join("tools", "appcast.py"), setup, VERSION, f"{base}/{APP_NAME}-Setup.exe",
             "--windows"] + notes, stdout=f)
    if not a.no_upload:
        run(["gh", "release", "upload", a.tag, "-R", REPO, wcast, "--clobber"])
    print("Done: appcast-windows.xml" + (" built." if a.no_upload else f" on {a.tag}."))


if __name__ == "__main__":
    main()
