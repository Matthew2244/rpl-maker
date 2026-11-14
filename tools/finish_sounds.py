"""Finish the sounds Matthew picked (2026-11-14) from the Magpie Sounds reels into assets/sounds.

    .venv/bin/python tools/finish_sounds.py

Picked by ear: done = pluck 1, failed = pluck 1, library made = pluck 2, waiting for you =
marimba 2. Each is finished from its ElevenLabs master (~/Downloads/magpie-sounds) the way
the candidates were (tools/make_sound_candidates.finish: float, mono, trimmed, faded, about
-18 dB average, peak capped before encoding), then written as .mp3 (Mac, afplay) and as a
16-bit .wav (Windows), and each finished file is checked: its peak must stay under -1 dBFS.
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import make_sound_candidates as msc  # noqa: E402

PICKS = {"done": "done - pluck 1", "failed": "failed - pluck 1",
         "library_made": "library made - pluck 2", "waiting": "waiting for you - marimba 2"}
OUT = os.path.join(ROOT, "assets", "sounds")


def main():
    os.makedirs(OUT, exist_ok=True)
    for event, master in PICKS.items():
        src = os.path.join(msc.MASTERS, master + ".mp3")
        mp3 = os.path.join(OUT, event + ".mp3")
        msc.finish(src, mp3)
        wav = os.path.join(OUT, event + ".wav")
        with tempfile.TemporaryDirectory() as t:
            # decode the finished mp3 in float, then 16-bit with dither for Windows
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", mp3, "-c:a", "pcm_s16le",
                            "-af", "aresample=osf=s16:dither_method=triangular", wav], check=True)
        for f in (mp3, wav):
            peak, mean = msc.levels(f)
            if peak > msc.ENCODED_LIMIT:
                sys.exit(f"{os.path.basename(f)} peaks at {peak} dBFS")
            print(f"{os.path.basename(f):22s} peak {peak:6.1f}  mean {mean:6.1f}")


if __name__ == "__main__":
    main()
