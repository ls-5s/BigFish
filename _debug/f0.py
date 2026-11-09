import sys
import wave

import numpy as np


def f0_median(path):
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        ch = w.getnchannels()
        sw = w.getsampwidth()
        raw = w.readframes(n)
    if sw != 2:
        return None
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    x /= 32768.0

    win = int(sr * 0.04)
    hop = int(sr * 0.02)
    vals = []
    for i in range(0, len(x) - win, hop):
        f = x[i:i + win]
        if np.sqrt(np.mean(f ** 2)) < 0.01:
            continue
        f = f - f.mean()
        ac = np.correlate(f, f, mode="full")[win - 1:]
        ac /= (ac[0] + 1e-9)
        lo, hi = int(sr / 400), int(sr / 70)
        seg = ac[lo:hi]
        if len(seg) == 0:
            continue
        k = int(np.argmax(seg)) + lo
        if ac[k] < 0.3:
            continue
        vals.append(sr / k)
    if not vals:
        return None
    return float(np.median(vals)), len(vals)


for p in sys.argv[1:]:
    r = f0_median(p)
    print(p, "->", r)
