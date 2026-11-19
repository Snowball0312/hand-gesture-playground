# -*- coding: utf-8 -*-
"""地图手势链路自检：用合成关键点驱动 GestureController，验证 进入 / 返回 / 缩放 / 进图交接。

不接摄像头、不弹窗，纯逻辑；跑法：
    py -3.12 projects/hand_3d/tools/test_gestures.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = Path(__file__).resolve().parent
PROJ = HERE.parent
ROOT = PROJ.parents[1]
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication  # noqa: E402

import map_data  # noqa: E402
from map_view import MapView  # noqa: E402
from roam import GestureController  # noqa: E402


class _NullTracker:
    """不占摄像头的 tracker 壳：HUD 只读这三个属性。"""

    fps = 0.0
    last_infer_ms = 0.0
    error = ""


class P:
    __slots__ = ("x", "y")

    def __init__(self, x, y):
        self.x, self.y = x, y


# 掌心为原点、手指朝上的模板（y 负方向是上）
TEMPLATE = {
    0: (0.0, 0.090),      # 腕
    1: (-0.050, 0.030), 2: (-0.080, -0.010), 3: (-0.090, -0.040), 4: (-0.080, -0.075),
    5: (-0.030, -0.010), 6: (-0.035, -0.060), 7: (-0.037, -0.090), 8: (-0.038, -0.120),
    9: (0.0, 0.0),      10: (0.0, -0.070), 11: (0.0, -0.100), 12: (0.0, -0.140),
    13: (0.030, 0.005), 14: (0.033, -0.060), 15: (0.034, -0.090), 16: (0.035, -0.130),
    17: (0.055, 0.020), 18: (0.058, -0.040), 19: (0.060, -0.070), 20: (0.060, -0.100),
}

FIST = {0: (0.0, 0.09), 4: (-0.06, -0.02), 8: (-0.01, -0.01), 12: (0.0, -0.015),
        16: (0.02, -0.02), 20: (0.04, -0.03), 6: (-0.035, -0.06), 10: (0.0, -0.07),
        14: (0.033, -0.06), 18: (0.058, -0.04), 5: (-0.03, -0.01), 9: (0, 0),
        13: (0.03, 0.005), 17: (0.055, 0.02)}


def make_hand(cx, cy, kind="open", pinch=False):
    pts = dict(TEMPLATE)
    if kind == "fist":
        pts.update(FIST)
    lm = [P(0, 0) for _ in range(21)]
    for i, (dx, dy) in pts.items():
        lm[i] = P(cx + dx, cy + dy)
    if pinch:
        # 拇指尖贴到食指尖
        lm[4] = P(lm[8].x + 0.004, lm[8].y + 0.002)
    return lm


def step(ctrl, hands, seconds, fps=60):
    for _ in range(int(seconds * fps) + 2):
        ctrl.on_hands(hands)
        ctrl._read_hands(1.0 / fps)
        ctrl._advance(1.0 / fps)


def fail(msg):
    print("FAIL", msg)
    return False


def main():
    app = QApplication(sys.argv[:1])
    root = map_data.load_root()
    view = MapView()
    view.resize(1280, 800)
    view.set_root(root)
    view.snap()

    ctrl = GestureController(view, _NullTracker())
    ok = True

    gd = [r for r in root.children if "广东" in r.name][0]
    px = view.world_to_screen(gd.label_pos.x(), gd.label_pos.y())
    # 光标取食指尖，所以掌心得往上、往右挪一点，让指尖落在标签上
    nx, ny = px.x() / view.width() + 0.038, px.y() / view.height() + 0.120
    hand = make_hand(nx, ny, "open", pinch=True)

    step(ctrl, [hand], 0.8)
    if view.current is not None and "广东" in view.current.name:
        print("PASS 进入下一级：", view.current.name, len(view.features), "个下级")
    else:
        ok = fail(f"捏合悬停没有进入，当前 = {view.current.name if view.current else None}")

    # 返回：先收左手，再张开保持 0.6 秒
    step(ctrl, [make_hand(0.25, 0.5, "fist")], 0.2)
    step(ctrl, [make_hand(0.25, 0.5, "open")], 0.9)
    if view.current is root:
        print("PASS 左手张开返回：", view.breadcrumb())
    else:
        ok = fail(f"返回失败，当前 = {view.current.name}")

    # 右手张开不应该再改变缩放（避免抬手就乱放大）
    before = view.tlog
    step(ctrl, [make_hand(nx, ny, "open", pinch=False)], 1.0)
    if abs(view.tlog - before) < 0.05:
        print(f"PASS 右手张开不误触缩放：tlog {before:.2f} → {view.tlog:.2f}")
    else:
        ok = fail(f"右手张开仍在缩放：tlog {before:.2f} → {view.tlog:.2f}")

    # 缩放：左手捏合向上拖动
    before = view.tlog
    step(ctrl, [make_hand(0.22, 0.55, "open", pinch=True)], 0.1)
    step(ctrl, [make_hand(0.22, 0.40, "open", pinch=True)], 0.2)
    if view.tlog > before + 0.2:
        print(f"PASS 左手捏合上拖放大：tlog {before:.2f} → {view.tlog:.2f}")
    else:
        ok = fail(f"拖动放大无效：tlog {before:.2f} → {view.tlog:.2f}")

    # 平移：左手捏合横向拖动
    tb = (view.tcx, view.tcy)
    step(ctrl, [make_hand(0.20, 0.50, "open", pinch=True)], 0.1)
    step(ctrl, [make_hand(0.30, 0.50, "open", pinch=True)], 0.2)
    moved = abs(view.tcx - tb[0]) + abs(view.tcy - tb[1])
    if moved > 1e-4:
        print(f"PASS 左手捏合平移：位移 {moved:.4f} 世界单位")
    else:
        ok = fail("平移无效")

    # ---------- 进图交接：双手捏合进图后还捏着，不能变成地图动作 ----------
    view.reset()
    ctrl.reset_for_entry()
    ctrl.active = True
    exited = []
    ctrl.on_back_at_root = lambda: exited.append(1)

    # 进图时双手都捏着，右手食指压在广东上
    both_pinch = [make_hand(0.25, 0.50, "open", pinch=True), hand]
    step(ctrl, both_pinch, 0.9)
    if view.current is root:
        print("PASS 进图后手还捏着：没有自己钻进省")
    else:
        ok = fail(f"进图后手还捏着却钻进了 {view.current.name}")

    # 接着松手（左手从捏合直接张开）——这不是“先收再张”，不该返回
    step(ctrl, [make_hand(0.25, 0.50, "open"), hand], 1.2)
    if not exited and view.current is root:
        print("PASS 进图后松手：没有被当成返回手势")
    else:
        ok = fail(f"进图后松手被当成返回（退出次数 {len(exited)}）")

    # 但正常的“收一下再张开”仍然要能返回，别把功能一起改坏
    step(ctrl, [make_hand(0.25, 0.50, "fist")], 0.3)
    step(ctrl, [make_hand(0.25, 0.50, "open")], 0.9)
    if exited:
        print("PASS 先收再张仍然能返回")
    else:
        ok = fail("修复后正常的返回手势失效了")

    # 右手松开一次之后，捏合悬停仍然要能进省
    view.reset()
    ctrl.reset_for_entry()
    ctrl.active = True
    step(ctrl, [make_hand(nx, ny, "open", pinch=False)], 0.1)   # 先松一次，解锁
    step(ctrl, [hand], 0.8)
    if view.current is not None and "广东" in view.current.name:
        print("PASS 松手解锁后，捏合悬停仍能进省")
    else:
        ok = fail(f"解锁后进不了省，当前 = {view.current.name if view.current else None}")

    print("全部通过" if ok else "有失败项")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
