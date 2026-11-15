# -*- coding: utf-8 -*-
"""合成手部关键点：不接摄像头也能验证手势规则。

坐标按 MediaPipe 21 点布局构造，归一化 0~1，原点左上。
  0 腕  1-4 拇指  5-8 食指  9-12 中指  13-16 无名指  17-20 小指
每根手指的 MCP/PIP/DIP/TIP 沿 -y 方向排列，指根 x 分散。
伸直时 指尖到腕距离 / PIP到腕距离 ≈ 1.43；蜷曲时 ≈ 0.69，
刚好跨过规则里 1.15 的判定线。
"""

WRIST = (0.50, 0.78)
FINGER_X = {"index": 0.47, "middle": 0.50, "ring": 0.53, "pinky": 0.56}
MCP_Y = 0.62
UP = (0.53, 0.47, 0.42)     # PIP, DIP, TIP 伸直
CURL = (0.56, 0.60, 0.63)   # PIP, DIP, TIP 蜷曲
THUMB_OPEN = [(0.44, 0.72), (0.41, 0.66), (0.39, 0.61), (0.37, 0.57)]
THUMB_PINCH = [(0.46, 0.72), (0.46, 0.64), (0.465, 0.55), (0.465, 0.425)]


class P:
    """最小关键点对象，只保留 mediapipe 里被规则用到的字段。"""

    __slots__ = ("x", "y", "z")

    def __init__(self, x, y, z=0.0):
        self.x, self.y, self.z = x, y, z

    def __repr__(self):
        return f"P({self.x:.4f},{self.y:.4f})"


def make_hand(index=False, middle=False, ring=False, pinky=False, pinch=False):
    """按哪几根手指伸直生成 21 点。pinch=True 时拇指尖贴到食指尖。"""
    up = [index, middle, ring, pinky]
    pts = [P(*WRIST)]
    thumb = THUMB_PINCH if pinch else THUMB_OPEN
    pts += [P(x, y) for x, y in thumb]
    for name, flag in zip(["index", "middle", "ring", "pinky"], up):
        x = FINGER_X[name]
        pip_y, dip_y, tip_y = UP if flag else CURL
        pts += [P(x, MCP_Y), P(x, pip_y), P(x, dip_y), P(x, tip_y)]
    assert len(pts) == 21
    return pts


def transform(pts, scale=1.0, dx=0.0, dy=0.0):
    """整体缩放/平移（以腕为原点），用于验证规则对距离和位置不敏感。"""
    wx, wy = pts[0].x, pts[0].y
    return [P(wx + (p.x - wx) * scale + dx, wy + (p.y - wy) * scale + dy, p.z)
            for p in pts]


# 覆盖所有分支的基础手型
CASES = {
    "open":       make_hand(True, True, True, True),
    "fist":       make_hand(),
    "pinch":      make_hand(True, False, False, False, pinch=True),
    "index_only": make_hand(True),
    "two_finger": make_hand(True, True),
    "three":      make_hand(True, True, True),
    "pinky_only": make_hand(pinky=True),
}


def all_variants():
    """每只手型再派生缩放 / 平移 / 镜像变体，共 7 × 4 = 28 组。"""
    out = {}
    for name, pts in CASES.items():
        out[name] = pts
        out[name + "@big"] = transform(pts, scale=1.35)
        out[name + "@small"] = transform(pts, scale=0.75)
        out[name + "@left"] = transform(pts, dx=-0.22)
        out[name + "@right"] = transform(pts, dx=0.18)
    return out


if __name__ == "__main__":
    for k, v in all_variants().items():
        print(k, v[0], v[8])
