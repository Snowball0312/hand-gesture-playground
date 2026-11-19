# -*- coding: utf-8 -*-
"""tree_rules 的纯逻辑单测：投影、拾取、礼物状态机。

不依赖 OpenGL / 摄像头，直接跑：
    py -3.12 tests/test_tree_rules.py
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "projects" / "christmas_tree"))

import tree_rules as R  # noqa: E402

passed = 0


def ok(cond, msg):
    global passed
    assert cond, msg
    passed += 1


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def test_project():
    # 正前方原点 → 屏幕中心
    sp = R.project((0, 0, 0), 5.0, 16 / 9)
    ok(approx(sp[0], 0.5) and approx(sp[1], 0.5), "原点应投影到屏幕中心")

    # 上方的点 → 屏幕 y 更小（屏幕坐标向下为正）
    up = R.project((0, 1, 0), 5.0, 16 / 9)
    ok(up[1] < 0.5, "上方的点应出现在中心上方")

    # 右边的点 → 屏幕 x 更大
    right = R.project((1, 0, 0), 5.0, 16 / 9)
    ok(right[0] > 0.5, "右边的点应出现在中心右侧")

    # 相机背后 → None
    ok(R.project((0, 0, 10), 5.0, 16 / 9) is None, "相机背后的点应返回 None")


def test_pick():
    pts = [(0.2, 0.8), (0.5, 0.5), None, (0.9, 0.1)]
    ok(R.pick(pts, (0.51, 0.49)) == 1, "应选中最近的礼物 1")
    ok(R.pick(pts, (0.21, 0.79)) == 0, "应选中礼物 0")
    ok(R.pick(pts, (0.05, 0.05)) == -1, "太远应返回 -1")
    ok(R.pick([None, None], (0.5, 0.5)) == -1, "全不可见应返回 -1")


def test_fsm():
    f = R.GiftFSM()
    ok(f.state == R.BROWSE and f.selected == -1, "初始应为浏览态且无选中")

    # 浏览态没选中时捏合：不应误触
    st, changed = f.pinch()
    ok(st == R.BROWSE and not changed, "无选中时捏合不应切换")

    # 选中后捏合 → 聚焦
    f.highlight(3)
    ok(f.selected == 3, "浏览态应能高亮")
    ok(not f.open_gift()[1], "浏览态的张开不应生效")
    st, changed = f.pinch()
    ok(st == R.FOCUS and changed, "选中后捏合应进入聚焦态")

    # 聚焦态不允许改选中
    f.highlight(1)
    ok(f.selected == 3, "聚焦态不应改变选中")

    # 聚焦态张开 → 打开
    st, changed = f.open_gift()
    ok(st == R.OPEN and changed, "聚焦态张开应进入打开态")

    # 打开态再捏合 → 回到浏览
    st, changed = f.pinch()
    ok(st == R.BROWSE and changed and f.selected == -1,
       "打开态再捏合应回到浏览并清空选中")

    # 聚焦态直接再捏合 → 回到浏览
    f.highlight(2)
    f.pinch()
    st, changed = f.pinch()
    ok(st == R.BROWSE and changed, "聚焦态再捏合应直接回到浏览")

    # 重置
    f.reset()
    ok(f.state == R.BROWSE and f.selected == -1, "reset 应回到初始")


def test_ease():
    ok(approx(R.ease_out_cubic(0.0), 0.0), "ease(0)=0")
    ok(approx(R.ease_out_cubic(1.0), 1.0), "ease(1)=1")
    ok(0.0 < R.ease_out_cubic(0.5) < 1.0, "ease 中间值应在 0~1")


def test_pointer_smooth():
    s = R.PointerSmooth(0.5)
    ok(s.pos is None, "未喂点时光标不存在")
    ok(s.update((0.2, 0.8)) == (0.2, 0.8), "第一个点应直接落位，不从屏幕角落飞过来")

    s.update((0.6, 0.4))
    ok(approx(s.pos[0], 0.4) and approx(s.pos[1], 0.6), "后续点按 alpha 混合")

    # 反复喂同一个点应收敛过去，而不是永远停在半路
    for _ in range(12):
        s.update((0.6, 0.4))
    ok(approx(s.pos[0], 0.6, 1e-3) and approx(s.pos[1], 0.4, 1e-3), "持续同一点应收敛")

    # 两个方向的抖动应被压掉一半以上
    s2 = R.PointerSmooth(0.5)
    s2.update((0.5, 0.5))
    s2.update((0.54, 0.5))
    ok(abs(s2.pos[0] - 0.52) < 1e-9, "抖动幅度应被 alpha 衰减")

    s2.update(None)
    ok(s2.pos is not None, "喂 None 应冻结光标而不是清空")
    s2.reset()
    ok(s2.pos is None, "reset 后光标消失")


def test_pick_hysteresis():
    """已经选中的礼物在没明显更近的候选时保留，指尖抖动不会让高亮来回跳。"""
    pts = [(0.4, 0.5), (0.5, 0.5)]
    # 恰好卡在两个礼物中间：B 略近，但不明显
    tip = (0.455, 0.5)
    ok(R.pick(pts, tip) == 1, "无回滞时应选略近的 B")
    ok(R.pick(pts, tip, current=0) == 0, "已选中 A 且优势不明显时应保留 A")
    # 但明显指向另一个时要换过去
    ok(R.pick(pts, (0.55, 0.5), current=0) == 1, "明显更近时应换成 B")
    # 走远到回滞半径外也应放弃
    ok(R.pick(pts, (0.62, 0.5), current=0) == 1, "超出回滞半径应换人")
    # current 越界或不可见时不应崩
    ok(R.pick(pts, (0.41, 0.5), current=9) == 0, "current 越界应退化成普通拾取")
    ok(R.pick([None, (0.5, 0.5)], (0.42, 0.5), current=0) == 1,
       "当前选中项不可见时应正常选下一个")


def test_pointer_step():
    """光标位移必须在渲染帧里推进，而不是只在识别回调时跳一格。"""
    s = R.PointerSmooth(0.45, tau=0.040)
    s.feed((0.20, 0.50), now=0.000)
    ok(s.pos == (0.20, 0.50), "第一个点应直接落位")

    # 识别在 t=0.033 给到新目标，随后 150fps 连跑 5 帧
    s.feed((0.40, 0.50), now=0.033)
    xs = []
    for k in range(1, 6):
        s.step(1.0 / 150.0)
        xs.append(s.pos[0])
    ok(all(x > 0.20 for x in xs), "第一帧就应该开始移动，而不是等下一次识别")
    ok(all(xs[i] < xs[i + 1] for i in range(len(xs) - 1)),
       "连续帧位移应单调推进，不能停住再跳")
    ok(xs[0] < 0.40, "不应一步跳到目标（那就是没有平滑）")

    # 手停住后必须收敛到目标，且不能冲过头
    for _ in range(120):
        s.step(1.0 / 150.0)
    ok(approx(s.pos[0], 0.40, 2e-3), "静止后应收敛到目标点，不能超调或停在半路")

    # 时间步长变化时行为一致：走 0.3 秒，无论分多少帧，结果接近
    a = R.PointerSmooth(0.45, tau=0.040)
    a.feed((0.2, 0.5), now=0.0)
    a.feed((0.8, 0.5), now=0.001)
    for _ in range(45):
        a.step(0.3 / 45)
    b = R.PointerSmooth(0.45, tau=0.040)
    b.feed((0.2, 0.5), now=0.0)
    b.feed((0.8, 0.5), now=0.001)
    for _ in range(450):
        b.step(0.3 / 450)
    ok(abs(a.pos[0] - b.pos[0]) < 0.02,
       f"帧率不同不应改变手感（{a.pos[0]:.3f} vs {b.pos[0]:.3f}）")


def main():
    test_project()
    test_pick()
    test_pick_hysteresis()
    test_fsm()
    test_ease()
    test_pointer_smooth()
    test_pointer_step()
    print(f"tree_rules 自检通过：{passed} 项断言")


if __name__ == "__main__":
    main()
