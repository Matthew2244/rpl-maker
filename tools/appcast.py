"""Write a Sparkle update list (appcast) for one release, signed with this app's EdDSA key.

    .venv/bin/python tools/appcast.py FILE VERSION URL [--notes NOTES.md] [--windows] > appcast.xml

FILE is the Mac zip (Sparkle) or, with --windows, the Windows installer (WinSparkle). The key
is this app's own (Studio login Keychain, Sparkle's account rpl-maker), never Wavelength's or
XK-7D Companion's. Only Sparkle's generate_keys can read it without a Keychain prompt, so it
exports the key into a private temporary folder for sign_update, and the file is overwritten
and removed straight after: nothing secret stays on disk.
"""
import argparse
import html
import os
import re
import subprocess
import sys
import tempfile
from email.utils import formatdate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from build_app_support import sparkle_bin  # noqa: E402

ACCOUNT = "rpl-maker"
MIN_MACOS = "12.0"   # the newest any bundled library needs (wxWidgets); checked with otool
WINDOWS_ARGS = "/SILENT /SP- /SUPPRESSMSGBOXES /NORESTART /relaunch=1"   # see installer.iss


def signature(path: str) -> str:
    b = sparkle_bin()
    d = tempfile.mkdtemp(prefix="rplmaker-sign-")
    os.chmod(d, 0o700)
    key = os.path.join(d, "k")
    try:
        old = os.umask(0o077)
        try:
            subprocess.run([os.path.join(b, "generate_keys"), "--account", ACCOUNT, "-x", key], check=True,
                           capture_output=True)
        finally:
            os.umask(old)
        out = subprocess.run([os.path.join(b, "sign_update"), "--ed-key-file", key, path], check=True,
                             capture_output=True, text=True).stdout.strip()
    finally:
        if os.path.exists(key):
            with open(key, "r+b") as f:
                f.write(b"\0" * max(64, os.path.getsize(key)))
            os.remove(key)
        os.rmdir(d)
    if not re.fullmatch(r'sparkle:edSignature="[A-Za-z0-9+/=]+" length="\d+"', out):
        sys.exit("sign_update gave no signature: " + out)
    return out


def notes_html(md: str) -> str:
    out = []
    for block in re.split(r"\n\s*\n", md.strip()):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        if all(ln.startswith("- ") for ln in lines):
            out.append("<ul>%s</ul>" % "".join("<li>%s</li>" % html.escape(ln[2:]) for ln in lines))
        else:
            out.append("<p>%s</p>" % html.escape(" ".join(lines)))
    return "\n".join(out)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("file")
    p.add_argument("version")
    p.add_argument("url")
    p.add_argument("--notes")
    p.add_argument("--windows", action="store_true")
    a = p.parse_args()
    sig = signature(a.file)
    notes = open(a.notes, encoding="utf-8").read() if a.notes else ""
    extra = (' sparkle:os="windows" sparkle:installerArguments="%s"' % WINDOWS_ARGS) if a.windows else ""
    minsys = "" if a.windows else "\n      <sparkle:minimumSystemVersion>%s</sparkle:minimumSystemVersion>" % MIN_MACOS
    print("""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
  <channel>
    <title>Magpie</title>
    <item>
      <title>Version {v}</title>
      <pubDate>{date}</pubDate>
      <sparkle:version>{v}</sparkle:version>
      <sparkle:shortVersionString>{v}</sparkle:shortVersionString>{minsys}
      <description><![CDATA[{notes}]]></description>
      <enclosure url="{url}" {sig} type="application/octet-stream"{extra}/>
    </item>
  </channel>
</rss>""".format(v=html.escape(a.version), date=formatdate(usegmt=True), minsys=minsys, notes=notes_html(notes),
                 url=html.escape(a.url, quote=True), sig=sig, extra=extra))


if __name__ == "__main__":
    main()
