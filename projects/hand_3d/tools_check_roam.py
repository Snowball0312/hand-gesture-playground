# -*- coding: utf-8 -*-
"""合并链路自检（不需要摄像头）。

把 Hand3dDetector 换成空壳，直接驱动主窗口的模式机：
  地球 → 中国平面 → 广东省 → 中国 → 地球
并验证：地图可见性、淡入淡出后地球是否暂停、返回根节点是否触发退回地球。

运行：py -3.12 projects/hand_3d/tools_check_roam.py
输出：projects/hand_3d/roam_country.png / roam_province.png
"""
import sys
import time
from pathlib import Path

from PyQt6.QtWidgets import QApplication

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

import main as earth  # noqa: E402


class _NullDet:
    fps = 60.0
    last_infer_ms = 0.0
    error = ""

    def __init__(self, *a, **k):
        pass

    def start(self):
        pass

    def stop(self):
        pass

    def join(self, timeout=None):
        pass


def pump(app, seconds):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.01)


def check(label, cond):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        raise SystemExit(1)


def main():
    earth.Hand3dDetector = _NullDet          # 自检不占摄像头
    app = QApplication(sys.argv)
    win = earth.MainWindow()
    win.show()
    pump(app, 0.5)

    check("初始为地球模式", win.mode == earth.MODE_EARTH)
    check("地图数据已并入 hand_3d",
          str(earth.map_data.GEO_DIR).startswith(str(HERE)))
    check("地图初始隐藏", not win.map_view.isVisible())
    check("地球初始在渲染", win.gl._active)

    # 双手捏合走的正是这个回调
    win.gl.on_double_pinch()
    # 这一条要在放帧之前查：一旦有帧进来，“没手 = 已经松开”会把锁清掉
    check("进图清掉了旧手势状态", win.roam._lock_until_release and not win.roam._back_armed)
    pump(app, 0.7)
    check("双手捏合回调 → 中国地图", win.mode == earth.MODE_MAP)
    check("地图已显示", win.map_view.isVisible())
    check("淡入完成", win._opacity.opacity() > 0.99)
    check("地球已暂停渲染", not win.gl._active)
    check("当前层级是中国", win.map_view.current is win.map_view.root)
    win.grab().save(str(HERE / "roam_country.png"))

    gd = next(f for f in win.map_view.root.children if f.name == "广东省")
    check("进入广东省", win.map_view.drill(gd))
    pump(app, 0.8)
    check("当前层级是广东省", win.map_view.current.name == "广东省")
    check("广东有市级要素", len(win.map_view.current.children or []) > 0)
    win.grab().save(str(HERE / "roam_province.png"))

    check("返回中国", win.map_view.back())
    pump(app, 0.5)
    check("回到中国层级", win.map_view.current is win.map_view.root)

    # 在中国这一层再做一次“返回”，应当退回地球而不是提示最外层
    win.roam.on_back_at_root()
    pump(app, 0.7)
    check("根节点返回 → 地球模式", win.mode == earth.MODE_EARTH)
    check("地图已隐藏", not win.map_view.isVisible())
    check("地球恢复渲染", win.gl._active)

    win.enter_map()
    pump(app, 0.5)
    check("可以再次进入地图", win.mode == earth.MODE_MAP and win.map_view.isVisible())
    win.exit_map()
    pump(app, 0.5)
    check("可以再次退出", win.mode == earth.MODE_EARTH and not win.map_view.isVisible())

    win.close()
    pump(app, 0.2)
    print("全部通过")


if __name__ == "__main__":
    main()
