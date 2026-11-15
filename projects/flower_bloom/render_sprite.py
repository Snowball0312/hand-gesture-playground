# -*- coding: utf-8 -*-
"""贴图精灵渲染：按开放度在相邻玫瑰帧之间平滑过渡。素材存于 assets/rose_frames.npz。
帧图在加载时预缩放到显示尺寸，避免每帧 resize 占用渲染时间。"""
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
NPZ_PATH = ROOT / "assets" / "rose_frames.npz"

_TARGET_W = 440
_BLEND_WEIGHT = 0.12  # 只做轻微柔化，避免半开帧之间出现重影
_frames = []

if NPZ_PATH.exists():
    z = np.load(NPZ_PATH)
    # 必须按数字编号排序；字符串排序会把 f100 排到 f10 后面，导致大小乱跳
    keys = sorted(z.files, key=lambda name: int(name.replace("f", "")))
    raw = [z[k] for k in keys]
    for img in raw:
        h, w = img.shape[:2]
        scale = _TARGET_W / w
        _frames.append(cv2.resize(
            img, (_TARGET_W, int(h * scale)), interpolation=cv2.INTER_LINEAR))


def has_frames():
    return len(_frames) > 0


def draw_flower(canvas, cx, cy, openness):
    if not _frames:
        return
    n = len(_frames)
    f = float(np.clip(openness, 0.0, 1.0)) * (n - 1)
    i0 = int(f)
    i1 = min(i0 + 1, n - 1)
    frac = f - i0

    if i1 != i0 and frac > 0.001:
        w = _BLEND_WEIGHT * (1.0 - abs(2.0 * frac - 1.0))
        img = cv2.addWeighted(_frames[i0], 1.0 - w, _frames[i1], w, 0.0)
    else:
        img = _frames[i0]

    sh, sw = img.shape[:2]
    x = int(cx - sw / 2)
    y = int(cy - sh / 2)
    if x < 0 or y < 0 or x + sw > canvas.shape[1] or y + sh > canvas.shape[0]:
        return
    canvas[y:y + sh, x:x + sw] = img
