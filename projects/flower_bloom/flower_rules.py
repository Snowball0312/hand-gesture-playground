# -*- coding: utf-8 -*-
"""花开规则：张开手掌=开花，握拳=合花。

判定逻辑来自 gesture_core.rules，这里只做“姿态 → 花开动作”的语义映射。
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gesture_core import fingers_up  # noqa: E402

OPEN = "open"    # 五指张开
FIST = "fist"    # 握拳
OTHER = "other"


def classify(lm):
    fu = fingers_up(lm)
    if all(fu.values()):
        return OPEN
    if not any(fu.values()):
        return FIST
    return OTHER
