# -*- coding: utf-8 -*-
"""隔空鼠标：张开手掌移动、捏合点击、握拳拖拽、两指滚动。

识别全部来自 gesture_core，本文件只负责“手势 → 鼠标动作”。
依赖：pyautogui（pip install pyautogui）
运行：双击根目录“启动隔空鼠标.bat”；窗口内 ESC 退出。
"""
import sys
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gesture_core import (  # noqa: E402
    ClickDebounce, HandTracker, OPEN_PALM, PINCH, FIST, TWO_FINGER,
    anchor, classify_gesture,
)

try:
    import pyautogui
except ImportError:                 # 只在真正运行时才提示，import 本模块不报错
    pyautogui = None

SCREEN_W = SCREEN_H = 0
MODEL_PATH = ROOT / "assets" / "hand_landmarker.task"

# 手感参数
ALPHA = 0.55                    # 光标平滑，抖就调小，延迟就调大
ROI_X, ROI_Y = 0.15, 0.18       # 只取画面中间这块映射到整屏，边缘留空防手出画
SCROLL_SENS, SCROLL_DEADZONE = 8.0, 3.0
PINCH_THRESHOLD = 0.28

latest = {"hands": None, "frame": None}


def on_hands(hands, frame):
    latest["hands"] = hands
    latest["frame"] = frame


def map_to_screen(nx, ny):
    sx = (nx - ROI_X) / (1 - 2 * ROI_X)
    sy = (ny - ROI_Y) / (1 - 2 * ROI_Y)
    return int(max(0.0, min(1.0, sx)) * SCREEN_W), int(max(0.0, min(1.0, sy)) * SCREEN_H)


def window_closed(title):
    try:
        return cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1
    except cv2.error:
        return True


def main():
    global SCREEN_W, SCREEN_H
    if pyautogui is None:
        print("缺少 pyautogui，先装依赖：\n    py -3.12 -m pip install pyautogui")
        return 1

    pyautogui.FAILSAFE = False      # 鼠标撞到屏幕角不抛异常，否则手一快就崩
    pyautogui.PAUSE = 0.0           # 每个动作后默认停 0.1s，这里必须关掉
    SCREEN_W, SCREEN_H = pyautogui.size()

    det = HandTracker(MODEL_PATH, on_hands, num_hands=1, cam_size=(960, 540),
                      mirror=True, draw=True, cam_fps=60)
    det.start()

    smooth_x, smooth_y = pyautogui.position()
    click = ClickDebounce(0.30)
    dragging = False
    prev_two_y = None
    title = "Gesture Mouse (ESC quit)"

    print("隔空鼠标：张开手掌移动 / 捏合点击 / 握拳拖拽 / 两指滚动；ESC 退出")

    while True:
        frame = latest["frame"]
        if frame is None:
            if det.error:
                print(det.error)
                break
            time.sleep(0.01)
            continue

        hands = latest["hands"] or []
        if hands:
            lm = hands[0]
            g = classify_gesture(lm, PINCH_THRESHOLD)
            ax, ay = anchor(lm)
            tx, ty = map_to_screen(ax, ay)

            if g == OPEN_PALM:
                smooth_x = ALPHA * tx + (1 - ALPHA) * smooth_x
                smooth_y = ALPHA * ty + (1 - ALPHA) * smooth_y
                pyautogui.moveTo(int(smooth_x), int(smooth_y))
                if dragging:
                    pyautogui.mouseUp()
                    dragging = False
                prev_two_y = None
            elif g == PINCH:
                if click.should_fire(True):
                    pyautogui.click()
                prev_two_y = None
            elif g == FIST:
                if not dragging:
                    pyautogui.mouseDown()
                    dragging = True
                smooth_x = ALPHA * tx + (1 - ALPHA) * smooth_x
                smooth_y = ALPHA * ty + (1 - ALPHA) * smooth_y
                pyautogui.moveTo(int(smooth_x), int(smooth_y))
                prev_two_y = None
            elif g == TWO_FINGER:
                if prev_two_y is None:
                    prev_two_y = ay
                else:
                    dy = (ay - prev_two_y) * 540
                    if abs(dy) > SCROLL_DEADZONE:
                        pyautogui.scroll(int(-dy / SCROLL_SENS))
                    prev_two_y = ay
                if dragging:
                    pyautogui.mouseUp()
                    dragging = False
            else:
                prev_two_y = None
                if dragging:
                    pyautogui.mouseUp()
                    dragging = False

            cv2.putText(frame, f"FPS {det.fps:4.1f}  {g}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        else:
            click.should_fire(False)
            if dragging:
                pyautogui.mouseUp()
                dragging = False
            prev_two_y = None
            cv2.putText(frame, "NO HAND", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        cv2.imshow(title, frame)
        if cv2.waitKey(1) & 0xFF == 27 or window_closed(title):
            break

    det.stop()
    det.join(2000)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    sys.exit(main())
