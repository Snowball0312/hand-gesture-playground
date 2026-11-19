# -*- coding: utf-8 -*-
"""接线自检：不需要摄像头，验证包装层参数与回调适配。

用法：py -3.12 tests/test_wiring.py
"""
import importlib
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(label, cond, detail=""):
    print(("  OK   " if cond else "  FAIL ") + label + (f"  [{detail}]" if detail else ""))
    return bool(cond)


def main():
    ok = True
    print("[1] 导入四个应用主模块")
    entries = [("flower_bloom", "flower_app.py"), ("hand_paint", "paint_app.py"),
               ("hand_3d", "main.py"), ("christmas_tree", "main.py")]
    for sub, fname in entries:
        src = ROOT / "projects" / sub / fname
        if not src.exists():
            print(f"  SKIP {sub}/{fname}（文件不存在）")
            continue
        # 两个项目里都有 detector.py / rules.py / particles.py，逐个导入前先清干净，
        # 否则后一个会拿到前一个的同名模块
        for k in ("detector", "rules", "particles", "scene", "renderer", "audio",
                  "map_data", "map_view", "roam", "tree_rules", "geo"):
            sys.modules.pop(k, None)
        sys.path.insert(0, str(ROOT / "projects" / sub))
        try:
            # 入口模块名唯一，避免两个 main.py 在 sys.modules 里互相顶掉
            spec = importlib.util.spec_from_file_location(f"entry_{sub}", src)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            ok &= check(f"{sub}/{fname}", True)
        except Exception as e:
            ok &= check(f"{sub}/{fname}", False, f"{type(e).__name__}: {e}")
        finally:
            sys.path.remove(str(ROOT / "projects" / sub))

    print("[2] 检测器参数与回调签名")
    got = {}

    from projects.flower_bloom.flower_detector import FlowerDetector
    fd = FlowerDetector(str(ROOT / "assets/hand_landmarker.task"),
                        on_hands=lambda hands: got.__setitem__("flower", hands))
    ok &= check("flower num_hands=1", fd.num_hands == 1, fd.num_hands)
    ok &= check("flower cam 480x360", (fd.cam_w, fd.cam_h) == (480, 360))
    ok &= check("flower 推理间隔 0.033", abs(fd.infer_interval - 0.033) < 1e-9)
    ok &= check("flower 不镜像", fd.mirror is False)
    fd.on_hands(["h"], "frame")
    ok &= check("flower 回调只收到 hands", got.get("flower") == ["h"])

    from projects.hand_paint.paint_detector import PaintDetector
    pd = PaintDetector(str(ROOT / "assets/hand_landmarker.task"),
                       on_hands=lambda hands, frame: got.__setitem__("paint", (hands, frame)))
    ok &= check("paint cam 640x480", (pd.cam_w, pd.cam_h) == (640, 480))
    ok &= check("paint 镜像", pd.mirror is True)
    ok &= check("paint 请求 60fps", pd.cam_fps == 60)
    pd.on_hands(["h"], "frame")
    ok &= check("paint 回调收到 (hands, frame)", got.get("paint") == (["h"], "frame"))

    from projects.hand_3d.detector import Hand3dDetector
    hd = Hand3dDetector(str(ROOT / "assets/hand_landmarker.task"),
                        on_hands=lambda hands: got.__setitem__("earth", hands))
    ok &= check("earth num_hands=2", hd.num_hands == 2, hd.num_hands)
    ok &= check("earth 镜像", hd.mirror is True)

    print("[3] ModeHold 与原内联防抖逻辑等价")
    for k in ["flower_detector", "flower_rules", "paint_detector", "paint_rules",
              "detector", "rules"]:
        sys.modules.pop(k, None)
    from gesture_core import ModeHold
    import random

    def old_logic(seq, hold=2, initial="hover"):
        committed = pending = initial
        count = 0
        out = []
        for raw in seq:
            if raw == committed:
                count = 0
            else:
                if raw == pending:
                    count += 1
                    if count >= hold:
                        committed = raw
                        count = 0
                else:
                    pending = raw
                    count = 1
            out.append(committed)
        return out

    rng = random.Random(20261113)
    alphabet = ["paint", "grab", "erase", "hover"]
    mismatch = 0
    for _ in range(300):
        seq = [rng.choice(alphabet) for _ in range(rng.randint(1, 40))]
        mh = ModeHold("hover", hold=2)
        new = [mh.update(r) for r in seq]
        if new != old_logic(seq):
            mismatch += 1
    ok &= check("300 条随机手势序列逐一相同", mismatch == 0, f"{mismatch} 条不同")

    print("\n" + ("全部通过" if ok else "存在失败项"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
