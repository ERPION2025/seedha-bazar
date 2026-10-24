"""Make Seedha Bazar's own sounds: a soft alarm chime for critical alerts and a short notification tune.

    python tools/make_tones.py
Writes web/static/web/sounds/alert.wav and notify.wav (mono, 22.05 kHz). Pure Python, no extra packages.
"""
import math
import struct
import wave
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "web" / "static" / "web" / "sounds"
RATE = 22050


def note(freq, dur, vol=0.35, decay=4.0):
    n = int(RATE * dur)
    out = []
    for i in range(n):
        t = i / RATE
        env = math.exp(-decay * t) * min(1.0, t * 80)  # quick soft attack, gentle fade
        s = math.sin(2 * math.pi * freq * t) + 0.3 * math.sin(2 * math.pi * freq * 2 * t)  # a little brightness, like a bell
        out.append(vol * env * s / 1.3)
    return out


def silence(dur):
    return [0.0] * int(RATE * dur)


def write(name, samples):
    OUT.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT / name), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 32767)) for s in samples))


if __name__ == "__main__":
    chime = note(659.25, 0.45) + note(783.99, 0.45) + note(1046.5, 0.9, decay=3)  # E5 G5 C6
    write("alert.wav", chime + silence(0.35) + chime)
    write("notify.wav", note(880, 0.18, 0.3, 6) + note(1318.5, 0.5, 0.3, 5))  # A5 then E6, short and light
    print("written", OUT)
