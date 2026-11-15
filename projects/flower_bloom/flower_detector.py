# -*- coding: utf-8 -*-
"""花开项目的检测器：只是 gesture_core.HandTracker 的薄封装。

保留项目原有的构造参数与回调签名（只要 hands，不要预览帧），
所以 flower_app.py 一行都不用改。
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gesture_core import HandTracker  # noqa: E402


class FlowerDetector(HandTracker):
    def __init__(self, model_path, on_hands, num_hands=1,
                 cam_size=(480, 360), infer_interval=0.033):
        super().__init__(
            model_path,
            on_hands=(lambda hands, frame: on_hands(hands)) if on_hands else None,
            num_hands=num_hands,
            cam_size=cam_size,
            infer_interval=infer_interval,
            mirror=False,    # 花开只用姿态，位置不参与，不必镜像
            draw=False,      # 不显示摄像头画面，画骨架纯属浪费
        )
