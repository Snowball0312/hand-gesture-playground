# -*- coding: utf-8 -*-
"""作画规则：食指画、捏合拖、张掌爆、其余悬停。

几何判定复用 gesture_core，这里只做“姿态 → 作画模式”的映射。
判定顺序有讲究：捏合优先，否则捏合时伸直的食指会被误判成画笔。
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gesture_core import anchor, fingers_up, pinch_ratio  # noqa: E402

# 模式
PAINT = "paint"      # 只伸食指：画笔
GRAB = "grab"        # 拇指+食指捏合：选中并拖动笔画
ERASE = "erase"      # 张开手掌：光标下笔画爆炸消散
HOVER = "hover"      # 其他（含握拳）：悬停

PINCH_THRESHOLD = 0.28


def classify(lm, pinch_threshold=PINCH_THRESHOLD):
    """返回 (模式, 锚点x, 锚点y)。锚点用食指尖。"""
    ax, ay = anchor(lm)
    if pinch_ratio(lm) < pinch_threshold:
        return GRAB, ax, ay
    fu = fingers_up(lm)
    if fu["index"] and not fu["middle"] and not fu["ring"] and not fu["pinky"]:
        return PAINT, ax, ay
    if all(fu.values()):
        return ERASE, ax, ay
    return HOVER, ax, ay
