# -*- coding: utf-8 -*-
"""把礼物 5 的人物从白色背景中抠成透明 PNG。

思路：
1. HSV 里「低饱和 + 高亮度」判定为背景候选（白底 + 脚下浅灰阴影）。
2. 从图像四边做 flood fill，只删除与边缘连通的候选背景。
   人物内部的白色牙齿、眼球高光被深色包围，不与边缘连通 → 完整保留。
3. 边缘 alpha 羽化 + 去白边，避免旋转/缩放时出现白色毛边。
4. 按人物包围盒裁剪并留少量透明边距。
"""
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    r"C:\Users\21254\Desktop\59211c29ea363729e4cbdb09fcfc30c4.jpg"
)
OUT = ROOT / "assets" / "gift5_character.png"


def imread_unicode(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"读不到图片: {path}")
    return img


def imwrite_unicode(path: Path, img: np.ndarray) -> None:
    ok, buf = cv2.imencode(path.suffix, img)
    if not ok:
        raise SystemExit(f"编码失败: {path}")
    buf.tofile(str(path))


def main() -> None:
    bgr = imread_unicode(SRC)
    h, w = bgr.shape[:2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    s = hsv[:, :, 1].astype(np.float32)
    v = hsv[:, :, 2].astype(np.float32)

    # 背景候选：几乎无彩色 + 很亮（白色底、浅灰阴影）
    candidate = ((s < 46) & (v > 188)).astype(np.uint8)

    # 从四边 flood fill，标记「与边缘连通」的背景
    flood = candidate.copy()
    mask = np.zeros((h + 2, w + 2), np.uint8)
    seeds = []
    step = max(1, min(h, w) // 200)
    for x in range(0, w, step):
        seeds.append((x, 0))
        seeds.append((x, h - 1))
    for y in range(0, h, step):
        seeds.append((0, y))
        seeds.append((w - 1, y))
    for seed in seeds:
        if flood[seed[1], seed[0]] == 1:
            cv2.floodFill(flood, mask, seed, 2)

    bg = flood == 2
    alpha = np.where(bg, 0, 255).astype(np.uint8)

    # 去掉孤立的极小背景噪点：前景里若出现小的空洞，尽量不开洞
    fg = (alpha > 0).astype(np.uint8)
    num, labels, stats, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
    if num > 1:
        # 只保留最大的前景连通域（人物），其余视为噪点
        areas = stats[1:, cv2.CC_STAT_AREA]
        keep = 1 + int(np.argmax(areas))
        fg = (labels == keep).astype(np.uint8) * 255

    # 边缘羽化：先做 3x3 高斯让边界柔和
    fg_soft = cv2.GaussianBlur(fg, (3, 3), 0.7)

    # 去白边：把 alpha 直接乘到 BGR 上会得到偏白的半透明边，
    # 这里对边缘做轻微「颜色向内部收缩」——用腐蚀后的实心色填充边缘。
    kernel = np.ones((3, 3), np.uint8)
    fg_core = cv2.erode(fg, kernel, iterations=1)
    bgr_clean = bgr.copy()
    # 对边缘一圈（alpha 介于 0~255 且原 alpha>0）用附近实心颜色替换
    edge = (fg_soft > 0) & (fg_core == 0)
    if edge.any():
        core_bgr = cv2.bitwise_and(bgr, bgr, mask=fg_core)
        # 用 3x3 最大滤波把颜色向边缘扩张
        dil_bgr = cv2.dilate(core_bgr, kernel, iterations=2)
        dil_mask = cv2.dilate(fg_core, kernel, iterations=2)
        use = edge & (dil_mask > 0)
        bgr_clean[use] = dil_bgr[use]

    out = cv2.cvtColor(bgr_clean, cv2.COLOR_BGR2BGRA)
    out[:, :, 3] = fg_soft

    # 裁剪到包围盒，留 2% 透明边距
    ys, xs = np.where(fg_soft > 8)
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    pad_x = int((x1 - x0) * 0.02) + 4
    pad_y = int((y1 - y0) * 0.02) + 4
    y0 = max(0, y0 - pad_y)
    x0 = max(0, x0 - pad_x)
    y1 = min(h - 1, y1 + pad_y)
    x1 = min(w - 1, x1 + pad_x)
    out = out[y0:y1 + 1, x0:x1 + 1]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    imwrite_unicode(OUT, out)
    print(f"原始尺寸: {w}x{h}  裁剪后: {out.shape[1]}x{out.shape[0]}")
    print(f"输出: {OUT}")


if __name__ == "__main__":
    main()
