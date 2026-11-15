# -*- coding: utf-8 -*-
"""作画项目的检测器：gesture_core.HandTracker 的薄封装。

回调保持 (hands, frame) 双参数，paint_app.py 无需改动。
镜像必须开：不做镜像的话“手往右、画笔往左”。
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gesture_core import HandTracker  # noqa: E402


class PaintDetector(HandTracker):
    def __init__(self, model_path, on_hands, num_hands=1,
                 cam_size=(640, 480), infer_interval=0.016):
        super().__init__(
            model_path,
            on_hands=(lambda hands, frame: on_hands(hands, frame)) if on_hands else None,
            num_hands=num_hands,
            cam_size=cam_size,
            infer_interval=infer_interval,
            mirror=True,
            draw=False,
            cam_fps=60,
        )
