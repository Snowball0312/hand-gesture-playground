# -*- coding: utf-8 -*-
"""纯规则层：只吃 mediapipe 的 21 个关键点，返回手势与几何量。

这里不含任何摄像头、线程、UI 代码，函数都是纯函数，方便单元测试
（tests/synth_hands.py 用合成关键点验证过全部分支）。
"""
import math
import time

# ---- 关键点索引（MediaPipe Hands 标准布局）----
WRIST = 0
THUMB_TIP = 4
INDEX_TIP = 8
MIDDLE_MCP = 9

# (指尖, PIP 关节)
FINGER_PAIRS = (
    ("index", (8, 6)),
    ("middle", (12, 10)),
    ("ring", (16, 14)),
    ("pinky", (20, 18)),
)
PALM_IDS = (0, 5, 9, 13, 17)

# 指尖到腕的距离超过 PIP 到腕距离的这个倍数，才算“伸直”。
# 实测伸直约 1.43，蜷曲约 0.69，1.15 落在中间。
STRAIGHT_RATIO = 1.15

# 通用手势名（粗粒度姿态；各前端再翻译成自己的动作）
OPEN_PALM = "OPEN_PALM"
PINCH = "PINCH"
FIST = "FIST"
TWO_FINGER = "TWO_FINGER"
OTHER = "OTHER"


def _dist(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def fingers_up(lm):
    """四根手指是否伸直，返回 {"index": bool, "middle": ..., ...}。"""
    wrist = lm[WRIST]
    return {
        name: _dist(lm[tip], wrist) > _dist(lm[pip], wrist) * STRAIGHT_RATIO
        for name, (tip, pip) in FINGER_PAIRS
    }


def count_up(lm):
    """伸直的手指数量 0~4。"""
    return sum(fingers_up(lm).values())


def pinch_ratio(lm):
    """捏合程度 = 拇指尖到食指尖距离 / 手掌长度，越小越接近捏合。

    除以手掌长度是为了抵消手离摄像头远近带来的尺度变化。
    """
    return _dist(lm[THUMB_TIP], lm[INDEX_TIP]) / (_dist(lm[WRIST], lm[MIDDLE_MCP]) + 1e-6)


def palm_center(lm):
    """掌心 = 腕 + 四个掌根点的平均，归一化坐标。"""
    n = len(PALM_IDS)
    return (sum(lm[i].x for i in PALM_IDS) / n,
            sum(lm[i].y for i in PALM_IDS) / n)


def hand_center_x(lm):
    """掌心横坐标，用于判断左右手（<0.5 为画面左侧）。"""
    return sum(lm[i].x for i in PALM_IDS) / len(PALM_IDS)


def anchor(lm):
    """操作锚点：食指尖。画笔、光标、拖拽都用它。"""
    return lm[INDEX_TIP].x, lm[INDEX_TIP].y


def openness(lm):
    """张开程度 0=握拳，1=完全张开，用于连续量控制（如镜头远近）。"""
    wrist = lm[WRIST]
    vals = []
    for _, (tip, pip) in FINGER_PAIRS:
        ratio = _dist(lm[tip], wrist) / (_dist(lm[pip], wrist) + 1e-6)
        # 伸直约 1.35、握拳约 0.9，线性归一到 0~1
        vals.append(max(0.0, min(1.0, (ratio - 0.95) / 0.4)))
    return sum(vals) / 4.0


def is_open(lm, min_up=3):
    """粗判断手掌张开：至少 min_up 根手指伸直。"""
    return count_up(lm) >= min_up


def classify_gesture(lm, pinch_threshold=0.28):
    """粗粒度手势分类，判定顺序有讲究：

    捏合优先——捏合时食指通常是伸直的，若不先判就会被误认成两指/张掌。
    """
    if pinch_ratio(lm) < pinch_threshold:
        return PINCH
    fu = fingers_up(lm)
    up = sum(fu.values())
    if fu["index"] and fu["middle"] and up == 2:
        return TWO_FINGER
    if up == 4:
        return OPEN_PALM
    if up == 0:
        return FIST
    return OTHER


class EMA:
    """指数滑动平均，抑制坐标抖动。alpha 越大越跟手、越小越平滑。"""

    def __init__(self, alpha=0.55, init=None):
        self.alpha = alpha
        self.value = init

    def update(self, x):
        if self.value is None:
            self.value = x
        else:
            self.value = self.alpha * x + (1 - self.alpha) * self.value
        return self.value

    def reset(self):
        self.value = None


class ClickDebounce:
    """边沿触发 + 冷却：只在“从未捏合变为捏合”的瞬间触发一次。

    没有它，捏住不动的每一帧都会触发点击。
    """

    def __init__(self, cooldown=0.30):
        self.cooldown = cooldown
        self._active = False
        self._last = 0.0

    def should_fire(self, active, now=None):
        now = now if now is not None else time.time()
        fire = False
        if active and not self._active and (now - self._last) > self.cooldown:
            fire = True
            self._last = now
        self._active = active
        return fire


class ModeHold:
    """手势防抖：候选姿态要连续保持 hold 帧才真正切换。

    识别结果逐帧抖动时，直接切换会让画笔/拖动模式疯狂闪跳。
    """

    def __init__(self, initial, hold=2):
        self.committed = initial
        self.pending = initial
        self.hold = max(1, int(hold))
        self._count = 0

    def update(self, raw):
        if raw == self.committed:
            self._count = 0
        elif raw == self.pending:
            self._count += 1
            if self._count >= self.hold:
                self.committed = raw
                self._count = 0
        else:
            self.pending = raw
            self._count = 1
        return self.committed

    def reset(self, value=None):
        if value is not None:
            self.committed = self.pending = value
        self._count = 0
