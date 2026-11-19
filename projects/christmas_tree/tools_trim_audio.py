# -*- coding: utf-8 -*-
"""把开礼物音效开头的静音切掉。

原始 laugh.wav 前面有 1.675 秒纯静音（RMS 一直是 0.000）。QSoundEffect 其实
是"立刻开始播"的，但前 1.7 秒听不见，手感上就成了"打开盒子以后过一会儿才笑"。

这个脚本按 RMS 找到真正的起声点，往前留 LEAD 秒做缓冲，再加一小段淡入
（避免波形从中间开始导致"啪"的一下爆音），另存为 *_open.wav。
原始文件不动，随时可以重跑。
"""
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SRC = HERE / "assets" / "laugh.wav"
DST = HERE / "assets" / "laugh_open.wav"

LEAD = 0.03        # 起声点前面保留多少秒
FADE_IN = 0.008    # 淡入时长（秒）
THRESH_RATIO = 0.01  # 判定有声：超过峰值的 1%


def main():
    with wave.open(str(SRC), "rb") as w:
        n, sr, ch, sw = w.getnframes(), w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(n)
    if sw != 2:
        raise SystemExit("只处理 16bit PCM")

    a = np.frombuffer(raw, dtype=np.int16).reshape(-1, ch).astype(np.float32) / 32768.0
    mono = np.abs(a).max(axis=1)
    peak = float(mono.max()) or 1.0
    idx = np.where(mono > peak * THRESH_RATIO)[0]
    if len(idx) == 0:
        raise SystemExit("整段音频都是静音")

    start = max(0, int((idx[0] / sr - LEAD) * sr))
    out = a[start:].copy()
    print(f"原长 {n / sr:.3f}s，起声点 {idx[0] / sr:.3f}s → 从 {start / sr:.3f}s 开始，"
          f"新长 {len(out) / sr:.3f}s")

    nf = max(1, int(FADE_IN * sr))
    ramp = np.linspace(0.0, 1.0, nf, dtype=np.float32)[:, None]
    out[:nf] *= ramp

    pcm = np.clip(out * 32767.0, -32768, 32767).astype(np.int16)
    with wave.open(str(DST), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(sw)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())

    size = DST.stat().st_size
    print(f"已写出 {DST.name}: {size / 1024:.0f} KB，{sr}Hz/{ch}ch/{sw * 8}bit")


if __name__ == "__main__":
    main()
