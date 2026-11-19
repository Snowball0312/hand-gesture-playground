# -*- coding: utf-8 -*-
"""下载并整理中国地图边界数据（国 → 省 → 市）。

数据源：阿里 DataV 边界库
    https://geo.datav.aliyun.com/areas_v3/bound/{adcode}_full.json
100000 是中国，其 features 是 34 个省级；
每个省的文件 features 是该省的地级市（直辖市为市辖区）。

用法（项目根目录）：
    py -3.12 projects/hand_3d/tools/build_geo.py
"""
import json
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets" / "geo"
URL = "https://geo.datav.aliyun.com/areas_v3/bound/{code}_full.json"


def fetch(code):
    dest = ASSETS / f"{code}_full.json"
    if dest.exists() and dest.stat().st_size > 1024:
        return dest
    last = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(URL.format(code=code), timeout=25) as r:
                data = r.read()
            if len(data) < 1024:
                raise ValueError("返回内容过小")
            dest.write_bytes(data)
            return dest
        except Exception as e:
            last = e
            time.sleep(0.8)
    print(f"  [失败] {code}: {last}")
    return None


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)

    root = fetch("100000")
    if root is None:
        raise SystemExit("中国边界下载失败，检查网络后重试")
    data = json.loads(root.read_text(encoding="utf-8"))
    provinces = []
    for f in data["features"]:
        p = f.get("properties") or {}
        name, code = p.get("name"), p.get("adcode")
        if not name or not code:
            continue
        provinces.append((str(code), name))

    print(f"省级 {len(provinces)} 个")

    manifest = []
    total_children = 0
    for code, name in provinces:
        dest = fetch(code)
        if dest is None:
            manifest.append({"adcode": code, "name": name, "children": 0, "ok": False})
            continue
        d = json.loads(dest.read_text(encoding="utf-8"))
        n = len(d.get("features") or [])
        total_children += n
        manifest.append({"adcode": code, "name": name, "children": n, "ok": True})
        print(f"  {name}({code}) → {n} 个下级")

    (ASSETS / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    bad = [m for m in manifest if not m["ok"]]
    print(f"合计下级 {total_children} 个；缺失 {len(bad)} 个")
    if bad:
        print("缺失：" + "、".join(m["name"] for m in bad))
    print(f"数据目录：{ASSETS}")


if __name__ == "__main__":
    main()
