# -*- coding: utf-8 -*-
"""一次性素材提取：从玫瑰延时视频抽取 16 帧，裁掉手机状态栏/播放控件，存成 npz。
重新生成时：设置环境变量 ROSE_VIDEO 指向新视频后运行本脚本。
"""
import os
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
VIDEO = os.environ.get(
    "ROSE_VIDEO",
    r"C:\Users\21254\xwechat_files\wxid_x5834mplskok22_673d\msg\video\2026-11\34b1e40992e54d585511218487ac8616.mp4",
)
OUT = ROOT / "assets"
OUT.mkdir(parents=True, exist_ok=True)

# 固定裁剪框：避开顶部状态栏与底部播放控件，只保留花主体
CROP = (225, 930, 1050, 1790)
FRAME_COUNT = 120
SAVE_WIDTH = 512
# 结尾几帧是播放器悬浮 UI，不取；只取花苞到盛开的主体区间
RATIO_START = 0.03
RATIO_END = 0.92


def main():
    cap = cv2.VideoCapture(VIDEO)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    targets = set()
    for i in range(FRAME_COUNT):
        p = RATIO_START + (RATIO_END - RATIO_START) * i / (FRAME_COUNT - 1)
        targets.add(int(round(p * (n - 1))))
    frames = {}
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx in targets:
            x1, y1, x2, y2 = CROP
            crop = frame[y1:y2, x1:x2]
            # 压掉纯黑噪声，避免黑边发灰
            b, g, r = cv2.split(crop)
            dark = (b < 14) & (g < 14) & (r < 14)
            crop[dark] = 0
            h, w = crop.shape[:2]
            small = cv2.resize(
                crop, (SAVE_WIDTH, int(h * SAVE_WIDTH / w)),
                interpolation=cv2.INTER_LANCZOS4)
            frames[f"f{len(frames):02d}"] = small
        idx += 1
    cap.release()

    np.savez_compressed(OUT / "rose_frames.npz", **frames)
    print(f"saved {len(frames)} frames -> {OUT / 'rose_frames.npz'}")


if __name__ == "__main__":
    main()
