# -*- coding: utf-8 -*-
"""双手交互规则：屏幕左侧=右手(旋转)，右侧=左手(缩放)。

几何量全部来自 gesture_core，这里只是转手方便 main.py 引用。
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gesture_core import hand_center_x, openness, pinch_ratio  # noqa: E402,F401

__all__ = ["pinch_ratio", "hand_center_x", "openness"]
