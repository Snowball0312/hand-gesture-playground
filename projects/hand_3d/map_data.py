# -*- coding: utf-8 -*-
"""地图数据层：读 GeoJSON → 墨卡托投影 → QPainterPath。

所有层级共用同一套世界坐标（墨卡托），这样相机可以跨层级连续推拉，
切换层级时画面不会跳。
"""
import json
import math
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QPainterPath, QPolygonF

HERE = Path(__file__).resolve().parent
GEO_DIR = HERE / "assets" / "geo"


def project(lon, lat):
    """经纬度 → 墨卡托平面坐标（弧度制 x，保证赤道处等比例）。"""
    lat = max(-85.0, min(85.0, lat))
    x = math.radians(lon)
    y = math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0))
    return x, y


def _rings_of(geometry):
    """Polygon / MultiPolygon → 环列表。"""
    if not geometry:
        return []
    t = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if t == "Polygon":
        return coords                       # [外环, 内环...]
    if t == "MultiPolygon":
        return [ring for poly in coords for ring in poly]
    return []


def _build_path(rings):
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.OddEvenFill)
    for ring in rings:
        if len(ring) < 3:
            continue
        pts = [QPointF(*project(p[0], p[1])) for p in ring]
        path.moveTo(pts[0])
        for p in pts[1:]:
            path.lineTo(p)
        path.closeSubpath()
    return path


def _ring_centroid(pts):
    """多边形重心；退化时用顶点平均。"""
    a = cx = cy = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(a) < 1e-9:
        return sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n
    return cx / (3.0 * a), cy / (3.0 * a)


def _label_pos(rings):
    """面积最大的外环的重心，作为注记落点。"""
    best, best_area = None, 0.0
    for ring in rings:
        if len(ring) < 3:
            continue
        pts = [project(p[0], p[1]) for p in ring]
        area = abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
                       - pts[(i + 1) % len(pts)][0] * pts[i][1]
                       for i in range(len(pts))) * 0.5)
        if area > best_area:
            best, best_area = pts, area
    if not best:
        return QPointF(0, 0)
    c = _ring_centroid(best)
    return QPointF(c[0], c[1])


class Region:
    """一个行政区：省或市。children 懒加载。"""

    __slots__ = ("name", "adcode", "level", "path", "bbox", "core_bbox", "full_bbox",
                 "label_pos", "parent", "children", "_loaded")

    def __init__(self, name, adcode, level, path, label_pos, parent=None, core_bbox=None):
        self.name = name
        self.adcode = str(adcode)
        self.level = level            # 0=中国 1=省 2=市
        self.path = path
        self.bbox = path.boundingRect() if path is not None else QRectF()
        self.core_bbox = core_bbox if core_bbox is not None else self.bbox
        self.full_bbox = None
        self.label_pos = label_pos
        self.parent = parent
        self.children = None          # None = 还没加载；[] = 确实没有下级
        self._loaded = False

    def ensure_children(self):
        """按需读取本级下级边界，第一次进入该级时加载。"""
        if self._loaded:
            return self.children or []
        self._loaded = True
        f = GEO_DIR / f"{self.adcode}_full.json"
        if not f.exists():
            self.children = []
            return self.children
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            self.children = []
            return self.children
        kids = []
        for feat in data.get("features") or []:
            kids.append(_region_from_feature(feat, self.level + 1, self))
        kids = [k for k in kids if k is not None]
        self.children = kids
        return kids

    def short_name(self):
        """地图上用的简称：去掉“省 / 市 / 自治区 / 特别行政区”等尾巴。"""
        n = self.name
        for suf in ("维吾尔自治区", "壮族自治区", "回族自治区", "特别行政区",
                    "自治区", "自治州", "地区", "省", "市", "盟"):
            if n.endswith(suf) and len(n) > len(suf):
                return n[:-len(suf)]
        return n

    def __repr__(self):
        return f"<Region {self.name} L{self.level}>"


def _main_ring_bbox(rings):
    """面积最大那圈（主体陆地）的包围盒，用于取景，忽略零星小岛。"""
    best_pts, best_area = None, 0.0
    for ring in rings:
        if len(ring) < 3:
            continue
        pts = [project(p[0], p[1]) for p in ring]
        area = abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
                       - pts[(i + 1) % len(pts)][0] * pts[i][1]
                       for i in range(len(pts))) * 0.5)
        if area > best_area:
            best_pts, best_area = pts, area
    if not best_pts:
        return QRectF()
    xs = [p[0] for p in best_pts]
    ys = [p[1] for p in best_pts]
    return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def _region_from_feature(feat, level, parent):
    props = feat.get("properties") or {}
    name = props.get("name")
    code = props.get("adcode")
    if not name or not code:
        return None
    rings = _rings_of(feat.get("geometry"))
    if not rings:
        return None
    path = _build_path(rings)
    if path.isEmpty():
        return None
    return Region(name, code, level, path, _label_pos(rings), parent,
                  core_bbox=_main_ring_bbox(rings))


def load_root():
    """读中国边界，构建 34 个省级 Region（省市数据保持懒加载）。"""
    f = GEO_DIR / "100000_full.json"
    if not f.exists():
        raise SystemExit(f"缺少边界数据：{f}\n先运行 py -3.12 projects/hand_3d/tools/build_geo.py")
    data = json.loads(f.read_text(encoding="utf-8"))

    root = Region("中国", 100000, 0, None, QPointF(0, 0), None)
    root._loaded = True
    root.full_bbox = QRectF()
    kids = []
    for feat in data.get("features") or []:
        r = _region_from_feature(feat, 1, root)
        if r is not None:
            kids.append(r)
    root.children = kids

    # 全国取景框：各省主体（最大一圈）的并集，避免南海零星岛把画面拉扁
    box = QRectF()
    full = QRectF()
    for r in kids:
        box = box.united(r.core_bbox)
        full = full.united(r.bbox)
    root.bbox = box
    root.core_bbox = box
    root.full_bbox = full
    root.label_pos = QPointF(box.center())
    return root
