"""Generate sound candidates for Matthew to pick by ear. Nothing here is wired into the app.

    .venv/bin/python tools/make_sound_candidates.py [--families bird,marimba,pluck] [--takes 2]

ElevenLabs sound generation (key: Keychain `elevenlabs-api-key`), then each one finished the
Wavelength way: mono, 25 Hz high-pass, silence trimmed, 8 ms fade in, a fade out, peak at
-1.5 dBFS (pushover-sound refuses anything under -6). Masters in ~/Downloads/magpie-sounds/;
finished candidates and audition reels in iCloud Drive, Magpie Sounds/. Each reel speaks a
candidate's name before playing it, so name and sound arrive together. This script never
plays anything aloud.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

HOME = os.path.expanduser("~")
MASTERS = os.path.join(HOME, "Downloads", "magpie-sounds")
ICLOUD = os.path.join(HOME, "Library", "Mobile Documents", "com~apple~CloudDocs", "Magpie Sounds")

EVENTS = {   # what it means, how long, which way it moves (descending = trouble, ascending = all clear)
    "done": ("the whole run is finished, all clear: a short bright ascending three-note phrase that resolves", 1.6),
    "failed": ("something failed: a gentle descending two-note phrase, soft and not harsh or alarming", 1.3),
    "library made": ("one small task succeeded: a single tiny bright note or quick two-note blip, very short", 0.6),
    "waiting for you": ("asking for your attention, waiting for an answer: a gentle two-note questioning call "
                        "that rises at the end", 1.2),
}
FAMILIES = {
    "bird": "a cheerful whistled bird call, like a magpie or songbird chirp, clean and close, no background",
    "marimba": "a warm wooden marimba, soft mallets, dry studio recording, no reverb tail",
    "pluck": "a soft rounded synth pluck, gentle and bright, clean, no reverb, user interface sound",
}


def key():
    return subprocess.run(["security", "find-generic-password", "-s", "elevenlabs-api-key", "-w"],
                          capture_output=True, text=True, check=True).stdout.strip()


def generate(text, seconds, out):
    body = json.dumps({"text": text, "duration_seconds": seconds, "prompt_influence": 0.6}).encode()
    req = urllib.request.Request("https://api.elevenlabs.io/v1/sound-generation", data=body, method="POST",
                                 headers={"xi-api-key": key(), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r, open(out, "wb") as f:
        f.write(r.read())


def levels(path):
    """(peak dB, mean dB) of the decoded audio."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    pk = re.search(r"max_volume: (-?[\d.]+) dB", r.stderr)
    mn = re.search(r"mean_volume: (-?[\d.]+) dB", r.stderr)
    return (float(pk.group(1)) if pk else 0.0), (float(mn.group(1)) if mn else -20.0)


TARGET_MEAN = -18.0   # every candidate about as loud as the next, so a reel favours none
MAX_PEAK = -3.0       # before encoding: bright sounds overshoot by 1.5 dB or more in MP3
ENCODED_LIMIT = -1.0  # checked on the finished file; Matthew hears clipping that meters miss


def finish(src, out):
    """Mono, high-passed, trimmed, faded, then levelled so the true peak sits at -1.5 dBFS."""
    with tempfile.TemporaryDirectory() as t:
        mid = os.path.join(t, "mid.wav")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-ac", "1", "-ar", "44100",
                        "-c:a", "pcm_f32le", "-af",
                        "highpass=f=25,silenceremove=start_periods=1:start_threshold=-50dB,"
                        "areverse,silenceremove=start_periods=1:start_threshold=-55dB,areverse,"
                        "afade=t=in:d=0.008", mid], check=True)
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mid],
                                   capture_output=True, text=True).stdout.strip() or 1)
        fade = min(0.15, dur / 3)
        peak, mean = levels(mid)
        gain = min(MAX_PEAK - peak, TARGET_MEAN - mean)
        for _try in range(4):
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", mid, "-af",
                            f"afade=t=out:st={max(0, dur - fade):.3f}:d={fade:.3f},volume={gain:.2f}dB,apad=pad_dur=0.04",
                            "-c:a", "libmp3lame", "-b:a", "192k", out], check=True)
            got = levels(out)[0]
            if got <= ENCODED_LIMIT:
                break
            gain -= got - ENCODED_LIMIT + 0.5


def spoken(text, out):
    aiff = out + ".aiff"
    subprocess.run(["say", "-o", aiff, text], check=True)   # renders to a file; nothing is heard
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", aiff, "-ac", "1", "-ar", "44100",
                    "-c:a", "pcm_f32le", out], check=True)
    os.remove(aiff)


def reel(parts, out):
    """Spoken name, half a second, the sound, a second and a half; mixed in float, mp3 out."""
    with tempfile.TemporaryDirectory() as t:
        pieces = []
        for i, (label, sound) in enumerate(parts):
            lab = os.path.join(t, f"l{i}.wav")
            spoken(label, lab)
            pieces += [lab, ("silence", 0.5), sound, ("silence", 1.5)]
        args, filt, n = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"], [], 0
        for p in pieces:
            if isinstance(p, tuple):
                args += ["-f", "lavfi", "-t", str(p[1]), "-i", "anullsrc=r=44100:cl=mono"]
            else:
                args += ["-i", p]
            filt.append(f"[{n}:a]aformat=sample_fmts=flt:sample_rates=44100:channel_layouts=mono[a{n}]")
            n += 1
        graph = ";".join(filt) + ";" + "".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[out]"
        subprocess.run(args + ["-filter_complex", graph, "-map", "[out]", "-c:a", "libmp3lame", "-b:a", "192k", out],
                       check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--families", default=",".join(FAMILIES))
    ap.add_argument("--takes", type=int, default=2)
    a = ap.parse_args()
    fams = a.families.split(",")
    os.makedirs(MASTERS, exist_ok=True)
    os.makedirs(os.path.join(ICLOUD, "Candidates"), exist_ok=True)
    made = {}
    for ev, (meaning, secs) in EVENTS.items():
        for fam in fams:
            for take in range(1, a.takes + 1):
                name = f"{ev} - {fam} {take}"
                master = os.path.join(MASTERS, name + ".mp3")
                if not os.path.exists(master):
                    print("generating", name, flush=True)
                    generate(f"{FAMILIES[fam]}; {meaning}", secs, master)
                done = os.path.join(ICLOUD, "Candidates", name + ".mp3")
                finish(master, done)
                made.setdefault(ev, []).append((f"{fam} {take}", done))
    for ev, items in made.items():
        out = os.path.join(ICLOUD, f"{ev.capitalize()} - audition.mp3")
        reel([(f"{ev.capitalize()}. Candidate {i + 1}, {label}.", path) for i, (label, path) in enumerate(items)], out)
        print("reel", out, flush=True)
    with open(os.path.join(ICLOUD, "What these are.txt"), "w") as f:
        f.write("Sound candidates for the preset library app (working title Magpie). Nothing is chosen yet.\n\n"
                "One audition file per sound. Each says the candidate's number and family, then plays it.\n"
                "Families: bird (a whistled call, for the magpie), marimba, pluck (a soft synth). Two takes each.\n\n"
                + "\n".join(f"{ev.capitalize()}: {m}" for ev, (m, _s) in EVENTS.items()) + "\n\n"
                "Each one is in Candidates, all about equally loud (average -18 dB, peaks under -1 dBFS).\n")


if __name__ == "__main__":
    sys.exit(main())
