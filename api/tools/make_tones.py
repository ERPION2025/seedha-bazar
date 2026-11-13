"""Make Seedha Bazar's own sounds: a soft alarm chime for critical alerts, a short notification tune, and "breeze":
wind moving through a standing crop, played quietly for notifications and when something is done.

    python tools/make_tones.py
Writes web/static/web/sounds/alert.wav, notify.wav and breeze.wav (mono, 22.05 kHz). Pure Python, no extra packages.
"""
import random
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


def breeze(dur=2.6, seed=7):
    """A gust passing through a field: filtered air that swells and settles, its tone drifting with the gust, and the dry
    rustle of leaves and ears brushing together, thicker at the height of the gust. No attack click, no tune."""
    rnd = random.Random(seed)
    n = int(RATE * dur)
    out = [0.0] * n
    low = band = 0.0  # state-variable band-pass filter for the air
    hp_prev_in = hp_prev_out = 0.0  # one-pole high-pass for the rustle
    rustle = [0.0] * n
    for i in range(n):
        t = i / dur / RATE  # 0..1
        env = (math.sin(math.pi * min(t / 0.42, 1) / 2) ** 2) * (1 - max(0, (t - 0.42) / 0.58)) ** 1.6  # rise ~1.1 s, long settle
        env *= 1 + 0.18 * math.sin(2 * math.pi * 1.7 * i / RATE + 0.6)  # the gust breathes
        fc = 450 + 750 * env  # the air brightens as the gust grows
        f = 2 * math.sin(math.pi * fc / RATE)
        x = rnd.uniform(-1, 1)
        high = x - low - 0.9 * band
        band += f * high
        low += f * band
        out[i] = band * env
        # leaves: short dry crackles, more of them when the wind is strongest
        if rnd.random() < 0.0026 * env:
            length = int(RATE * rnd.uniform(0.004, 0.016))
            amp = rnd.uniform(0.15, 0.5) * env
            for k in range(min(length, n - i)):
                rustle[i + k] += amp * rnd.uniform(-1, 1) * math.exp(-5 * k / length)
    leaves = []
    for v in rustle:  # keep only the high, papery part of the crackles
        y = 0.86 * (hp_prev_out + v - hp_prev_in)
        hp_prev_in, hp_prev_out = v, y
        leaves.append(y)
    mix = [0.75 * a + 0.45 * b for a, b in zip(out, leaves)]
    peak = max(abs(v) for v in mix) or 1
    return [0.32 * v / peak for v in mix]  # quiet by design; the page plays it softer still


if __name__ == "__main__":
    write("breeze.wav", breeze())
    chime = note(659.25, 0.45) + note(783.99, 0.45) + note(1046.5, 0.9, decay=3)  # E5 G5 C6
    write("alert.wav", chime + silence(0.35) + chime)
    write("notify.wav", note(880, 0.18, 0.3, 6) + note(1318.5, 0.5, 0.3, 5))  # A5 then E6, short and light
    print("written", OUT)
