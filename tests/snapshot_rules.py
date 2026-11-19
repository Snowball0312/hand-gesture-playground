# -*- coding: utf-8 -*-
"""跑一遍所有手势规则，把结果写成 JSON。

重构前跑一次作为 baseline_v1.json，重构后再跑一次逐值比对，
确保“抽公共层”没有改变任何一条判定结果。

用法：
    py -3.12 tests/snapshot_rules.py            # 打印到 stdout
    py -3.12 tests/snapshot_rules.py out.json   # 写入文件
"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from synth_hands import all_variants  # noqa: E402


def load(name, path):
    """按文件路径加载模块，绕开三个项目里同名的 rules.py。"""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def r(v, n=10):
    return None if v is None else round(float(v), n)


def main():
    flower = load("p_flower_rules", ROOT / "projects/flower_bloom/flower_rules.py")
    paint = load("p_paint_rules", ROOT / "projects/hand_paint/paint_rules.py")
    hand3d = load("p_hand3d_rules", ROOT / "projects/hand_3d/rules.py")

    out = {}
    for name, lm in all_variants().items():
        rec = {}

        g = flower.classify(lm)
        rec["flower"] = g

        mode, ax, ay = paint.classify(lm)
        rec["paint"] = [mode, r(ax), r(ay)]

        rec["hand3d"] = {
            "pinch": r(hand3d.pinch_ratio(lm)),
            "center_x": r(hand3d.hand_center_x(lm)),
            "openness": r(hand3d.openness(lm)),
        }

        # 通用分类器；新旧 core 的入口名不同，两种都兼容
        try:
            import gesture_core as core
            if hasattr(core, "classify_gesture"):
                rec["core_gesture"] = core.classify_gesture(lm, 0.28)
            else:
                cg, _open, _cx, _cy = core.classify(lm, 0.28)
                rec["core_gesture"] = cg
        except Exception as e:  # 某一项失败不影响其它项
            rec["core_gesture"] = f"<{type(e).__name__}: {e}>"

        out[name] = rec

    text = json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text, encoding="utf-8")
        print(f"wrote {len(out)} cases -> {sys.argv[1]}")
    else:
        print(text)


if __name__ == "__main__":
    main()
