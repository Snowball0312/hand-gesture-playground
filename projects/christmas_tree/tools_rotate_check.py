# -*- coding: utf-8 -*-
"""生成「平面 2D 卡片绕竖轴自转」的示意拼图，用于确认镜像背面的观感。

仅做水平缩放（cos）+ 镜像 + 侧对变暗，不改变人物本身。
"""
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "assets" / "gift5_character.png"
OUT = ROOT / "assets" / "_rotate_check.png"

TARGET_H = 380
FRAMES = 8


def main() -> None:
    data = np.fromfile(str(SRC), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise SystemExit("读不到素材")
    h, w = img.shape[:2]
    scale = TARGET_H / h
    nw, nh = int(w * scale), TARGET_H
    sprite = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)

    cell_w, cell_h = nw + 80, nh + 90
    canvas = np.full((cell_h * 2, cell_w * 4, 3), 18, np.uint8)

    for i in range(FRAMES):
        ang = i / FRAMES * 2 * np.pi
        c = float(np.cos(ang))
        sx = max(abs(c), 0.04)
        fw = max(2, int(nw * sx))
        f = cv2.resize(sprite, (fw, nh), interpolation=cv2.INTER_AREA)
        if c < 0:
            f = cv2.flip(f, 1)
        shade = 0.45 + 0.55 * abs(c)
        rgb = (f[:, :, :3].astype(np.float32) * shade).astype(np.uint8)
        alpha = f[:, :, 3:4].astype(np.float32) / 255.0

        r, cx = divmod(i, 4)
        ox = cx * cell_w + (cell_w - fw) // 2
        oy = r * cell_h + 20
        roi = canvas[oy:oy + nh, ox:ox + fw]
        canvas[oy:oy + nh, ox:ox + fw] = (
            rgb.astype(np.float32) * alpha + roi.astype(np.float32) * (1 - alpha)
        ).astype(np.uint8)
        cv2.putText(canvas, f"{int(np.degrees(ang))}deg", (ox, oy + nh + 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1, cv2.LINE_AA)

    ok, buf = cv2.imencode(".png", canvas)
    buf.tofile(str(OUT))
    print("输出:", OUT)


if __name__ == "__main__":
    main()
