import sys
import wave

import numpy as np


def frames(path):
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        raw = w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return sr, x / 32768.0


def f0s(path):
    sr, x = frames(path)
    win = int(sr * 0.05)
    hop = int(sr * 0.01)
    out = []
    for i in range(0, len(x) - win, hop):
        f = x[i:i + win]
        if np.sqrt(np.mean(f ** 2)) < 0.015:
            continue
        f = f - f.mean()
        ac = np.correlate(f, f, mode="full")[win - 1:]
        ac /= (ac[0] + 1e-9)
        lo, hi = int(sr / 400), int(sr / 70)
        seg = ac[lo:hi]
        if len(seg) < 3:
            continue
        k = int(np.argmax(seg)) + lo
        if ac[k] < 0.35:
            continue
        # parabolic interpolation
        a, b, c = ac[k - 1], ac[k], ac[k + 1]
        denom = (a - 2 * b + c)
        delta = 0.5 * (a - c) / denom if abs(denom) > 1e-9 else 0.0
        lag = k + delta
        out.append(sr / lag)
    return np.array(out)


for p in sys.argv[1:]:
    v = f0s(p)
    if len(v) == 0:
        print(p, "no voiced frames")
        continue
    print(f"{p}\n  frames={len(v)} median={np.median(v):.1f} p10={np.percentile(v,10):.1f} p90={np.percentile(v,90):.1f}")
