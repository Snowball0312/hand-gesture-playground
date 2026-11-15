# -*- coding: utf-8 -*-
"""回归比对：新代码的规则输出 vs 重构前基线。

用法：py -3.12 tests/compare_rules.py
任一项不一致都会列出来并以退出码 1 结束。
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE / "baseline_v1.json"


def run_snapshot():
    out = Path(tempfile.mkdtemp()) / "now.json"
    subprocess.run([sys.executable, str(HERE / "snapshot_rules.py"), str(out)],
                   check=True, cwd=str(HERE.parent),
                   stdout=subprocess.DEVNULL)
    return json.loads(out.read_text(encoding="utf-8"))


def main():
    base = json.loads(BASE.read_text(encoding="utf-8"))
    now = run_snapshot()

    diffs = []
    for case, old in base.items():
        new = now.get(case)
        if new is None:
            diffs.append(f"{case}: 新结果缺失")
            continue
        if old["flower"] != new["flower"]:
            diffs.append(f"{case}.flower: {old['flower']} -> {new['flower']}")
        if old["paint"] != new["paint"]:
            diffs.append(f"{case}.paint: {old['paint']} -> {new['paint']}")
        for key in ("pinch", "center_x", "openness"):
            if old["hand3d"][key] != new["hand3d"][key]:
                diffs.append(f"{case}.hand3d.{key}: {old['hand3d'][key]} -> {new['hand3d'][key]}")
        old_core = old["core"][0] if isinstance(old["core"], list) else old["core"]
        if old_core != new["core_gesture"]:
            diffs.append(f"{case}.core: {old_core} -> {new['core_gesture']}")

    total = len(base) * 4
    if diffs:
        print(f"FAIL  {len(diffs)} 处不一致 / 共 {total} 项")
        for d in diffs[:40]:
            print("  -", d)
        return 1
    print(f"OK    {len(base)} 组用例 × 4 类规则，全部与基线一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
