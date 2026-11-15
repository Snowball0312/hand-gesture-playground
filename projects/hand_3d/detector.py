# -*- coding: utf-8 -*-
"""双手 3D 地球的检测器：gesture_core.HandTracker 的薄封装。

双手模式（num_hands=2），镜像必须开，否则左右手会搞反。
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gesture_core import HandTracker  # noqa: E402


class Hand3dDetector(HandTracker):
    def __init__(self, model_path, on_hands, num_hands=2,
                 cam_size=(480, 360), infer_interval=0.016):
        super().__init__(
            model_path,
            on_hands=(lambda hands, frame: on_hands(hands)) if on_hands else None,
            num_hands=num_hands,
            cam_size=cam_size,
            infer_interval=infer_interval,
            mirror=True,
            draw=False,
            cam_fps=60,
        )
