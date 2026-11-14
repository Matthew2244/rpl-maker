"""Build the app for the system this runs on: python build_app.py

Mac:     dist/Magpie.app (Sparkle inside), zipped to dist/Magpie-mac.zip. Ad-hoc signed unless
         RPLMAKER_SIGN_ID names a Developer ID (tools/release_mac.py sets it, with the hardened
         runtime).
Windows: dist/Magpie/ (the app folder, WinSparkle and Prism inside), and dist/Magpie-Setup.exe
         when Inno Setup is installed. No portable zip: only an installed copy can update.
Ends by running the built app's --self-test.
"""
import os
import shutil
import subprocess
import sys
import tempfile

from rplmaker import APP_NAME, VERSION

BUNDLE_ID = "io.github.matthew2244.rplmaker"   # stays the same whatever the app is called
SIGN_ID = os.environ.get("RPLMAKER_SIGN_ID")
WIN = sys.platform == "win32"
args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", APP_NAME,
        "--add-data", os.path.join("rplmaker", "worker.lua") + os.pathsep + "rplmaker",
        "--hidden-import", "rplmaker.gui", "--hidden-import", "rplmaker.cli", "--hidden-import", "rplmaker.selftest"]
icon = os.path.join("assets", "icon.ico" if WIN else "icon.icns")
if os.path.exists(icon):
    args += ["--icon", icon]
if WIN:
    from build_app_support import winsparkle_dll
    import importlib.util
    args += ["--add-binary", winsparkle_dll() + os.pathsep + "."]
    # Prism: speech through NVDA, JAWS and the others, or Narrator through UI Automation. Its
    # compiled part isn't a file type the packager collects, so its folder is copied by hand.
    native = os.path.join(importlib.util.find_spec("prism").submodule_search_locations[0], "_native")
    args += ["--collect-all", "prism", "--hidden-import", "_cffi_backend"]
    for f in os.listdir(native):
        args += ["--add-binary", os.path.join(native, f) + os.pathsep + "prism/_native"]
else:
    args += ["--osx-bundle-identifier", BUNDLE_ID]
    if SIGN_ID:
        args += ["--codesign-identity", SIGN_ID]
subprocess.run(args + ["app.py"], check=True)


def embed_sparkle(app: str, sign_id: str | None) -> None:
    from build_app_support import sparkle_dir
    fw_dir = os.path.join(app, "Contents", "Frameworks")
    os.makedirs(fw_dir, exist_ok=True)
    dest = os.path.join(fw_dir, "Sparkle.framework")
    shutil.rmtree(dest, ignore_errors=True)
    subprocess.run(["ditto", os.path.join(sparkle_dir(), "Sparkle.framework"), dest], check=True)
    shutil.rmtree(os.path.join(dest, "Versions", "B", "XPCServices"), ignore_errors=True)   # for sandboxed apps
    link = os.path.join(dest, "XPCServices")
    if os.path.islink(link):
        os.remove(link)   # it pointed at what was just removed
    sign = ["codesign", "--force", "--sign", sign_id or "-"]
    if sign_id:
        sign += ["--options", "runtime", "--timestamp"]
    b = os.path.join(dest, "Versions", "B")
    for part in (os.path.join(b, "Autoupdate"), os.path.join(b, "Updater.app"), dest):   # inside out
        subprocess.run(sign + [part], check=True)


os.chdir("dist")
if WIN:
    exe = os.path.join(APP_NAME, APP_NAME + ".exe")
    out = None
    iscc = shutil.which("ISCC") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if os.path.exists(iscc):
        subprocess.run([iscc, "/Q", f"/DAppVersion={VERSION}", f"/DSourceDir={os.path.abspath(APP_NAME)}",
                        os.path.join("..", "packaging", "windows", "installer.iss")], check=True)
        out = os.path.abspath(f"{APP_NAME}-Setup.exe")
    else:
        print("Inno Setup isn't installed, so no installer this time.")
else:
    from build_app_support import FEED, SPARKLE_PUBLIC_KEY
    app = f"{APP_NAME}.app"
    plist = f"{app}/Contents/Info.plist"
    embed_sparkle(app, SIGN_ID)
    for key, kind, value in (("CFBundleShortVersionString", "-string", VERSION), ("CFBundleVersion", "-string", VERSION),
                             ("SUFeedURL", "-string", FEED), ("SUPublicEDKey", "-string", SPARKLE_PUBLIC_KEY),
                             # the app looks for updates itself and says so (updates.py); Sparkle's
                             # window comes only from Help, Check for Updates
                             ("SUEnableAutomaticChecks", "-bool", "NO"),
                             ("SUAllowsAutomaticUpdates", "-bool", "NO"),
                             ("NSHumanReadableCopyright", "-string",
                              "Free and open source, MIT license. Not affiliated with Cockos or any plug-in maker."),
                             # macOS shows these in its questions before the app reads those places
                             ("NSDocumentsFolderUsageDescription", "-string",
                              "to find plug-in presets kept in your Documents folder"),
                             ("NSRemovableVolumesUsageDescription", "-string", "to find plug-in presets kept on other drives"),
                             ("NSNetworkVolumesUsageDescription", "-string", "to find plug-in presets kept on network drives"),
                             ("NSDesktopFolderUsageDescription", "-string", "to find plug-in presets kept on your Desktop")):
        subprocess.run(["plutil", "-replace", key, kind, value, plist], check=True)
    if SIGN_ID:
        subprocess.run(["codesign", "--force", "--options", "runtime", "--timestamp", "--sign", SIGN_ID, app], check=True)
    else:
        subprocess.run(["codesign", "--force", "--sign", "-", app], check=True)
    out = os.path.abspath(f"{APP_NAME}-mac.zip")
    if os.path.exists(out):
        os.remove(out)
    subprocess.run(["ditto", "-c", "-k", "--keepParent", app, out], check=True)
    exe = f"{app}/Contents/MacOS/{APP_NAME}"

with tempfile.TemporaryFile("w+") as log:   # a file, not a pipe, with a time limit (Wavelength's lesson)
    subprocess.run([exe, "--self-test"], stdout=log, stderr=subprocess.STDOUT, timeout=180)
    log.seek(0)
    lines = log.read().strip().splitlines()
for line in lines[:-1]:
    print("  " + line)
print(lines[-1] if lines else "Self-test: no output")
if not lines or "Self-test: OK" not in lines[-1]:
    sys.exit("The built app failed its self-test.")
print("Built", out or os.path.abspath(APP_NAME))
