# -*- coding: utf-8 -*-
"""
手势作画 · 摄像头画面叠加版
  只伸食指   → 画笔
  捏合       → 选中最近一笔并拖动
  张开手掌   → 光标下笔画爆炸消散
  其他/握拳  → 悬停
ESC 退出；按键 c 清空画布
"""
import sys
import time
import math
from pathlib import Path
import numpy as np
import cv2

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

from gesture_core import ModeHold
from strokes import StrokeManager
from paint_rules import classify, PAINT, GRAB, ERASE, HOVER
from paint_detector import PaintDetector
from particles import ExplosionParticles

MODEL_PATH = str(ROOT / "assets" / "hand_landmarker.task")

W, H = 960, 720
BG = (18, 14, 12)
HIT_RADIUS = 34
ERASE_RADIUS = 42
EMA_ALPHA = 0.5
MODE_HOLD = 2          # 同一候选手势持续 N 帧才切换，防抖
TARGET_FPS = 60
MIN_PAINT_STEP = 2.0

CURSOR = {
    PAINT: (120, 220, 120),
    GRAB:  (0, 220, 255),
    ERASE: (80, 80, 255),
    HOVER: (170, 170, 170),
}

latest = {"hands": None, "frame": None}


def on_hands(hands, frame):
    latest["hands"] = hands
    latest["frame"] = frame


def main():
    manager = StrokeManager()
    particles = ExplosionParticles()
    det = PaintDetector(MODEL_PATH, on_hands=on_hands)
    det.start()

    smooth = None
    grabbed = None
    grab_prev = None
    mode_hold = ModeHold(HOVER, hold=MODE_HOLD)

    vx, vy = 0.0, 0.0
    last_valid_t = 0.0

    last_t = time.perf_counter()
    fps_ema = 60.0

    cv2.namedWindow("手势作画", cv2.WINDOW_AUTOSIZE)

    while True:
        now = time.perf_counter()
        dt = now - last_t
        last_t = now
        if dt > 0:
            fps_ema = 0.92 * fps_ema + 0.08 * (1.0 / dt)

        # ---- 读手势并平滑光标 ----
        hands = latest["hands"]
        raw_mode = HOVER
        sx, sy = W // 2, H // 2
        show_cursor = False

        if hands:
            lm = hands[0]
            raw_mode, nx, ny = classify(lm)
            rx, ry = nx * W, ny * H
            if smooth is None:
                smooth = [rx, ry]
            else:
                old_x, old_y = smooth[0], smooth[1]
                smooth[0] = EMA_ALPHA * rx + (1 - EMA_ALPHA) * smooth[0]
                smooth[1] = EMA_ALPHA * ry + (1 - EMA_ALPHA) * smooth[1]
                vx = smooth[0] - old_x
                vy = smooth[1] - old_y
            sx, sy = int(smooth[0]), int(smooth[1])
            last_valid_t = now
            show_cursor = True
        elif smooth is not None and now - last_valid_t < 0.2:
            # 快速移动时短暂丢手，按速度外推一小段，避免光标瞬间消失
            sx = int(smooth[0] + vx * 2)
            sy = int(smooth[1] + vy * 2)
            show_cursor = True

        # ---- 手势防抖：候选持续几帧才真正切换 ----
        mode = mode_hold.update(raw_mode)

        # ---- 状态机 ----
        if mode == PAINT:
            if manager.current is None or \
                    math.hypot(sx - manager.current.points[-1][0],
                               sy - manager.current.points[-1][1]) >= MIN_PAINT_STEP:
                manager.extend(sx, sy)
            grabbed, grab_prev = None, None
        elif mode == GRAB:
            manager.end()
            if grabbed is None:
                grabbed = manager.hit(sx, sy, HIT_RADIUS)
                grab_prev = (sx, sy)
            elif grabbed:
                dx = sx - grab_prev[0]
                dy = sy - grab_prev[1]
                manager.move(grabbed, dx, dy)
                grab_prev = (sx, sy)
        elif mode == ERASE:
            manager.end()
            stroke = manager.hit(sx, sy, ERASE_RADIUS)
            if stroke:
                particles.explode(stroke.points)
                manager.strokes.remove(stroke)
                if manager.current is stroke:
                    manager.current = None
            grabbed, grab_prev = None, None
        else:
            manager.end()
            grabbed, grab_prev = None, None

        particles.update(dt)

        # ---- 纯深色画布，不显示摄像头画面 ----
        canvas = np.full((H, W, 3), BG, dtype=np.uint8)

        manager.render(canvas)
        particles.render(canvas)

        # 光标
        if show_cursor:
            color = CURSOR[mode]
            r = 10 if mode != ERASE else ERASE_RADIUS // 2
            cv2.circle(canvas, (sx, sy), r, color, 2, cv2.LINE_AA)
            cv2.circle(canvas, (sx, sy), 2, color, -1)

        # ---- HUD ----
        label = {"paint": "画笔", "grab": "拖动",
                 "erase": "爆炸擦除", "hover": "悬停"}.get(mode, mode)
        hud = (f"mode: {label}   strokes: {len(manager.strokes)}   "
               f"FPS: {fps_ema:.0f}   infer: {det.last_infer_ms:.0f}ms")
        cv2.putText(canvas, hud, (12, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(canvas, hud, (12, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 0, 0), 1, cv2.LINE_AA)
        cv2.putText(canvas, "食指画 / 捏合拖动 / 张掌爆炸擦除 / c清空 / ESC退出",
                    (12, H - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (230, 230, 230), 1, cv2.LINE_AA)

        cv2.imshow("手势作画", canvas)
        key = cv2.waitKey(1) & 0xFF
        if key == 27:
            break
        elif key == ord("c"):
            manager.strokes.clear()

        # 渲染节奏锁 60FPS
        elapsed = time.perf_counter() - now
        sleep = (1.0 / TARGET_FPS) - elapsed
        if sleep > 0:
            time.sleep(sleep)

    det.stop()
    det.join(2000)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
