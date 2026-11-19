# -*- coding: utf-8 -*-
"""圣诞树的检测器：gesture_core.HandTracker 的薄封装。

双手模式：一只手做指向 / 捏合 / 张开，两只手做开合缩放。
镜像必须开，否则"手往右、画面往右"的直觉会反掉。
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gesture_core import HandTracker  # noqa: E402


class TreeDetector(HandTracker):
    def __init__(self, model_path, on_hands, num_hands=2,
                 cam_size=(480, 360), infer_interval=0.016):
        super().__init__(
            model_path,
            on_hands=on_hands,
            num_hands=num_hands,
            cam_size=cam_size,
            infer_interval=infer_interval,
            mirror=True,
            draw=False,
            cam_fps=60,
        )
