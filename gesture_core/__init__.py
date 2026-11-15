# -*- coding: utf-8 -*-
"""gesture_core：与 UI 解耦的手势识别层。

只做三件事：
  1. 开摄像头、抓帧                    → tracker.HandTracker
  2. 用 MediaPipe 取 21 个手部关键点    → tracker.HandTracker
  3. 把关键点翻译成手势 / 几何量        → rules

不依赖 PyQt / OpenGL / pyautogui。前端订阅回调，自己决定手势对应什么动作。
"""
from .tracker import HandTracker, ensure_model, draw_skeleton, HAND_CONNECTIONS
from .rules import (
    OPEN_PALM, PINCH, FIST, TWO_FINGER, OTHER,
    fingers_up, count_up, is_open, pinch_ratio,
    palm_center, hand_center_x, anchor, openness, classify_gesture,
    EMA, ClickDebounce, ModeHold,
    STRAIGHT_RATIO, FINGER_PAIRS,
)

__all__ = [
    "HandTracker", "ensure_model", "draw_skeleton", "HAND_CONNECTIONS",
    "OPEN_PALM", "PINCH", "FIST", "TWO_FINGER", "OTHER",
    "fingers_up", "count_up", "is_open", "pinch_ratio",
    "palm_center", "hand_center_x", "anchor", "openness", "classify_gesture",
    "EMA", "ClickDebounce", "ModeHold",
    "STRAIGHT_RATIO", "FINGER_PAIRS",
]
