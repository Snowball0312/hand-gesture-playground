# -*- coding: utf-8 -*-
"""双手地球：初始姿态与模式隔离的行为测试（不需要摄像头，也不需要显示窗口）。

    py -3.12 tests/test_globe_modes.py
"""
import math
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "projects" / "hand_3d"))
sys.path.insert(0, str(ROOT / "tests"))

import numpy as np  # noqa: E402
from synth_hands import make_hand, transform  # noqa: E402

ok_all = True


def check(label, cond, detail=""):
    global ok_all
    ok_all = ok_all and bool(cond)
    print(("  OK   " if cond else "  FAIL ") + label + (f"  [{detail}]" if detail else ""))
    return bool(cond)


def hand(side, pinch=False, open_hand=False):
    """造一只位于画面左/右侧的手。"""
    pts = make_hand(True, True, True, True) if open_hand else make_hand(
        pinched_index := True, False, False, False, pinch=pinch)
    dx = -0.22 if side == "left" else 0.22
    return transform(pts, dx=dx)


def main():
    print("[1] 初始姿态：中国正对镜头且北朝上")
    import main as app_mod
    from PyQt6.QtWidgets import QApplication
    qapp = QApplication.instance() or QApplication(sys.argv)
    glw = app_mod.GLWidget()

    rot = glw.rot
    d = np.array(app_mod.geo.latlon_to_dir(app_mod.geo.CHINA_LAT, app_mod.geo.CHINA_LON))
    facing = rot @ d
    check("中国方向被转到 +Z（正对镜头）", np.allclose(facing, [0, 0, 1], atol=1e-9),
          f"{facing.round(3)}")

    lam = math.radians(app_mod.geo.CHINA_LON)
    east = np.array([math.cos(lam), math.sin(lam), 0.0])
    north = np.cross(d, east)
    north /= np.linalg.norm(north)
    check("东方向映射到屏幕右 +X", np.allclose(rot @ east, [1, 0, 0], atol=1e-9))
    check("北方向映射到屏幕上 +Y", np.allclose(rot @ north, [0, 1, 0], atol=1e-9))
    check("旋转矩阵行列式为 +1（无镜像）", abs(np.linalg.det(rot) - 1.0) < 1e-9)

    print("[2] 大头针：立于法线方向")
    pin_dir = np.array(app_mod.PIN_DIR)
    ang, ax, ay, az = app_mod.PIN_ROT
    axis = np.array([ax, ay, az])
    # 把 +Z 绕该轴转 ang 度，应等于针的方向
    c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    v = np.array([0.0, 0.0, 1.0])
    rotated = v * c + np.cross(axis, v) * s + axis * axis.dot(v) * (1 - c)
    check("针轴与球面法线同向（不再扎进地里）", np.allclose(rotated, pin_dir, atol=1e-6),
          f"{rotated.round(3)} vs {pin_dir.round(3)}")
    check("针坐标落在单位球面上", abs(np.linalg.norm(pin_dir) - 1.0) < 1e-9)

    print("[3] 模式隔离：地图打开期间地球完全冻结")
    left_open, right_open = hand("left", open_hand=True), hand("right", open_hand=True)
    left_pinch, right_pinch = hand("left", pinch=True), hand("right", pinch=True)

    check("初始为地球模式", glw.mode == app_mod.MODE_EARTH)

    glw.apply_hands([left_pinch, right_pinch])
    check("双手同时捏合 → 进入地图模式", glw.mode == app_mod.MODE_MAP)

    before = glw.rot.copy()
    dist_before = glw.target_dist
    glw.apply_hands([left_pinch, left_open])          # 单捏合 + 张手，模拟乱动
    for _ in range(60):
        glw._tick()
    check("地图模式下旋转矩阵完全不动", np.array_equal(before, glw.rot))
    check("地图模式下镜头距离不动", abs(glw.target_dist - dist_before) < 1e-12)
    check("地图不透明度已升到 1 附近", glw.china_alpha > 0.9, f"{glw.china_alpha:.3f}")

    print("[4] 退出地图：先松开再捏合，且要等地图像素退干净")
    glw.apply_hands([left_open, right_open])          # 松开，重置边沿检测
    time.sleep(app_mod.MODE_SWITCH_COOLDOWN + 0.05)   # 冷却按真实时间计算
    glw.apply_hands([left_pinch, right_pinch])
    check("再次双手捏合 → 回到地球模式", glw.mode == app_mod.MODE_EARTH)
    check("此时地图仍可见，手势暂不生效", not glw.earth_ready(),
          f"alpha={glw.china_alpha:.3f}")

    before = glw.rot.copy()
    glw.apply_hands([left_pinch, right_open])         # 立刻试图旋转
    for _ in range(3):
        glw._tick()
    check("淡出期间旋转被忽略", np.array_equal(before, glw.rot))

    for _ in range(120):                              # 让 alpha 衰减到位
        glw._tick()
    check("淡出完成后恢复就绪", glw.earth_ready(), f"alpha={glw.china_alpha:.3f}")

    # 速度需要两帧位置差才算得出来，所以先建立基准再移动一点
    glw.apply_hands([left_pinch, right_open])
    glw.apply_hands([transform(left_pinch, dx=0.001), right_open])
    for _ in range(3):
        glw._tick()
    moved = not np.array_equal(before, glw.rot)
    check("此时捏合拖动确实能转动地球", moved)

    print("[5] 切换手势不会误触：单手连续夹放不切模式")
    glw2_mode_before = glw.mode
    for _ in range(30):
        glw.apply_hands([right_pinch, right_open])
        glw.apply_hands([right_open, right_pinch])
    check("单手反复捏合不改变模式", glw.mode == glw2_mode_before)

    print("[6] 进地图时自动转回中国（贴片贴在球面，中国转到背面就看不见了）")
    glw3 = app_mod.GLWidget()
    glw3.rot = app_mod.rotation("y", 140) @ app_mod.initial_rotation()   # 中国转到侧后方
    glw3.set_mode(app_mod.MODE_MAP)
    facing0 = glw3.rot @ d
    check("刚进地图时还没对上（这不是缺陷，只是记录起点）", facing0[2] < 0.9,
          f"朝屏幕分量={facing0[2]:.3f}")
    for _ in range(200):
        glw3._tick()
    facing1 = glw3.rot @ d
    check("几十帧后自动转回中国正对镜头", np.allclose(facing1, [0, 0, 1], atol=0.02),
          f"{facing1.round(3)}")
    check("对焦完成后不再继续转", np.allclose(glw3.rot @ d, facing1, atol=1e-9))

    print("\n" + ("全部通过" if ok_all else "存在失败项"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
