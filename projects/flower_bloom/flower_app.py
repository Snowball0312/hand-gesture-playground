# -*- coding: utf-8 -*-
"""
花开交互 · 玫瑰帧序列版
  张开手掌 → 开花；握拳 → 合花；手势消失保持当前状态
  花朵固定中央；开放/收拢缓慢平滑过渡；目标 60FPS 渲染
ESC 退出
"""
import sys
import time
from pathlib import Path
import numpy as np
import cv2

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from flower_engine import BloomEngine
from flower_detector import FlowerDetector
from flower_rules import classify, OPEN, FIST

try:
    import render_sprite as _sprite
    # render_sprite 在 npz 缺失时不报错，只是帧列表为空、draw_flower 直接 return，
    # 画面会全黑，所以必须显式检查，不能只靠 except 兜。
    if not _sprite.has_frames():
        raise RuntimeError("assets/rose_frames.npz 不存在或为空")
    draw_flower = _sprite.draw_flower
except Exception as _err:
    from render_placeholder import draw_flower
    print(f"[花开] 未找到玫瑰帧序列（{_err}）→ 已改用程序化占位花型。")
    print("       要换成真实玫瑰：见 projects/flower_bloom/README.txt 的素材生成一节")

MODEL_PATH = str(ROOT / "assets" / "hand_landmarker.task")

W, H = 800, 720
TARGET_FPS = 60
FRAME_DT = 1.0 / TARGET_FPS

latest = {"hands": None}


def main():
    engine = BloomEngine()
    detect_events = 0
    detect_fps = 0.0
    detect_t = time.perf_counter()

    def handle_hands(hands):
        nonlocal detect_events
        latest["hands"] = hands
        detect_events += 1

    det = FlowerDetector(MODEL_PATH, on_hands=handle_hands)
    det.start()

    cv2.namedWindow("花开", cv2.WINDOW_AUTOSIZE)
    canvas = np.zeros((H, W, 3), dtype=np.uint8)

    last_t = time.perf_counter()
    fps_ema = 60.0

    while True:
        hands = latest["hands"]
        if hands:
            action = classify(hands[0])
            if action == OPEN:
                engine.open()
            elif action == FIST:
                engine.close()

        engine.update()

        canvas[:] = 0
        draw_flower(canvas, W // 2, int(H * 0.46), engine.openness)

        # 状态文字
        if abs(engine.target - engine.openness) < 0.01:
            state = "已盛开" if engine.target == 1.0 else "已收拢"
        elif engine.target == 1.0:
            state = "开放中"
        else:
            state = "收拢中"
        # 检测频率统计（0.5 秒更新一次）
        now_det = time.perf_counter()
        det_dt = now_det - detect_t
        if det_dt >= 0.5:
            detect_fps = detect_events / det_dt
            detect_events = 0
            detect_t = now_det

        hud = f"开放度 {engine.openness * 100:3.0f}%   状态: {state}   FPS: {fps_ema:.0f}"
        cv2.putText(canvas, hud, (16, 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.68, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(canvas, f"推理 {det.last_infer_ms:.0f}ms   检测 {detect_fps:.0f}fps",
                    (16, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (180, 180, 190), 1, cv2.LINE_AA)
        cv2.putText(canvas, "张开手掌开花 / 握拳合花 / ESC退出",
                    (16, H - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (170, 170, 170), 1, cv2.LINE_AA)

        cv2.imshow("花开", canvas)
        key = cv2.waitKey(1) & 0xFF
        if key == 27:
            break

        # 显示帧节奏控制在约 60FPS；检测线程在后台独立运行
        now = time.perf_counter()
        dt = now - last_t
        last_t = now
        if dt > 0:
            fps_ema = 0.92 * fps_ema + 0.08 * (1.0 / dt)
        sleep = FRAME_DT - dt
        if sleep > 0:
            time.sleep(sleep)

    det.stop()
    det.join(2000)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
