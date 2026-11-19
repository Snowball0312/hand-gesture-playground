# -*- coding: utf-8 -*-
"""地图视图：相机推拉、边界渲染、悬停命中、手势进度反馈。

所有层级共用同一套世界坐标，切换层级时相机不动，
所以“进入下一级 / 返回上一级”都是连续的推拉，不会硬切。
"""
import math
import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import (QColor, QFont, QFontDatabase, QLinearGradient, QPainter,
                         QPen, QPixmap, QRadialGradient, QTransform)
from PyQt6.QtWidgets import QWidget

BG_TOP = QColor(11, 21, 38)
BG_BOTTOM = QColor(4, 7, 12)
LAND_FILL = QColor(24, 46, 76, 165)
BORDER = QColor(96, 156, 214, 210)
HOVER_FILL = QColor(70, 170, 255, 90)
HOVER_BORDER = QColor(176, 232, 255, 255)
GLOW = QColor(80, 170, 255, 110)
PARENT_LINE = QColor(110, 170, 240, 70)
LABEL_COLOR = QColor(206, 228, 255, 225)
ACCENT = QColor(120, 210, 255)

ZOOM_MIN_OFFSET = -0.25      # 相对“全国刚好铺满”的对数缩放下限
ZOOM_MAX_OFFSET = 5.0
CAM_EASE = 7.0

_FONT_FAMILY = None


def ui_font(px):
    """按可用字体挑一个中文无衬线，离屏渲染时也能正常出字。"""
    global _FONT_FAMILY
    if _FONT_FAMILY is None:
        fams = set(QFontDatabase.families())
        for cand in ("Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "SimSun"):
            if cand in fams:
                _FONT_FAMILY = cand
                break
        else:
            _FONT_FAMILY = ""
    f = QFont(_FONT_FAMILY)
    f.setPixelSize(px)
    return f


class MapView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(720, 540)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        self.root = None
        self.current = None           # 当前“展开的是谁的下级”
        self.features = []            # 当前层级要画的行政区

        self.cx = self.cy = 0.0
        self.log_scale = 0.0
        self.tcx = self.tcy = 0.0
        self.tlog = 0.0

        self.cursor = None            # 屏幕坐标 QPointF
        self.hovered = None
        self.hover_alpha = 0.0

        self.hold_progress = 0.0      # 进入下一级的蓄力环
        self.hold_pos = None
        self.back_progress = 0.0
        self.back_pos = None

        self.status_fps = 0.0
        self.status_infer = 0.0
        self.status_note = ""
        self._paint_ms = 0.0
        self._bg = None               # 背景渐变缓存，别每帧算径向渐变
        self._moving = False

        self.banner_text = ""
        self.banner_t0 = 0.0

        self._last_tick = 0.0
        self._frame_fps = 0.0

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)          # 锁 60FPS，别让重绘空转烧 CPU

    # ---------- 数据 ----------
    def set_root(self, root):
        self.root = root
        self.reset()

    def _set_features(self, features):
        self.features = features

    def reset(self):
        self.current = self.root
        self._set_features(self.root.children or [])
        self.hovered = None
        self.cx, self.cy = self.root.bbox.center().x(), self.root.bbox.center().y()
        self.log_scale = self._fit_log(self.root.bbox)
        self.tcx, self.tcy, self.tlog = self.cx, self.cy, self.log_scale

    def _fit_log(self, bbox):
        w = max(1.0, float(self.width()))
        h = max(1.0, float(self.height()))
        bw = max(1e-5, bbox.width())
        bh = max(1e-5, bbox.height())
        return math.log(min(w / bw, h / bh) * 0.92)

    def _clamp_scale(self, log_scale):
        if self.root is None:
            return log_scale
        base = self._fit_log(self.root.bbox)
        return max(base + ZOOM_MIN_OFFSET, min(base + ZOOM_MAX_OFFSET, log_scale))

    def _clamp_center(self, cx, cy):
        box = self.root.full_bbox or self.root.bbox
        m = max(box.width(), box.height()) * 0.25
        return (max(box.left() - m, min(box.right() + m, cx)),
                max(box.top() - m, min(box.bottom() + m, cy)))

    def _banner(self, text):
        self.banner_text = text or ""
        self.banner_t0 = time.perf_counter()

    def drill(self, region):
        """进入某个省，显示它的地级市。没有下级就返回 False。"""
        if region is None or self.current is None:
            return False
        kids = region.ensure_children()
        if not kids:
            return False
        self.current = region
        self._set_features(kids)
        self.hovered = None
        self.hover_alpha = 0.0
        self.tcx, self.tcy = region.core_bbox.center().x(), region.core_bbox.center().y()
        self.tlog = self._clamp_scale(self._fit_log(region.core_bbox))
        self._banner(region.name)
        return True

    def back(self):
        if self.current is None or self.current.parent is None:
            return False
        target = self.current.parent
        self.current = target
        self._set_features(target.children or [])
        self.hovered = None
        self.hover_alpha = 0.0
        self.tcx, self.tcy = target.bbox.center().x(), target.bbox.center().y()
        self.tlog = self._clamp_scale(self._fit_log(target.bbox))
        self._banner(target.name)
        return True

    def breadcrumb(self):
        parts = []
        r = self.current
        while r is not None:
            parts.append(r.name)
            r = r.parent
        return " / ".join(reversed(parts))

    def level_hint(self):
        if self.current is None:
            return ""
        n = len(self.features)
        if self.current.level == 0:
            return f"{n} 个省级行政区"
        return f"{n} 个市级行政区"

    # ---------- 手势 / 鼠标输入 ----------
    def zoom_by(self, delta_log, anchor=None):
        """按对数缩放；anchor 给屏幕点时，尽量让该点下的地图不动。"""
        self.tlog = self._clamp_scale(self.tlog + delta_log)
        if anchor is not None:
            wx, wy = self.screen_to_world(anchor)
            scale = math.exp(self.tlog)
            self.tcx = wx - (anchor.x() - self.width() / 2.0) / scale
            self.tcy = wy + (anchor.y() - self.height() / 2.0) / scale
            self.tcx, self.tcy = self._clamp_center(self.tcx, self.tcy)

    def pan_pixels(self, dx, dy):
        scale = math.exp(self.tlog)
        self.tcx -= dx / scale
        self.tcy += dy / scale
        self.tcx, self.tcy = self._clamp_center(self.tcx, self.tcy)

    def set_cursor(self, pt):
        self.cursor = pt
        if pt is None:
            self.hovered = None
            return None
        wx, wy = self.screen_to_world(pt)
        hit = None
        for f in self.features:
            if f.path is not None and f.path.contains(QPointF(wx, wy)):
                hit = f
                break
        self.hovered = hit
        return hit

    def set_hold(self, progress, pos=None):
        self.hold_progress = max(0.0, min(1.0, progress))
        self.hold_pos = pos

    def set_back_hold(self, progress, pos=None):
        self.back_progress = max(0.0, min(1.0, progress))
        self.back_pos = pos

    def set_status(self, fps=None, infer=None, note=None):
        if fps is not None:
            self.status_fps = fps
        if infer is not None:
            self.status_infer = infer
        if note is not None:
            self.status_note = note

    def snap(self):
        """跳过缓动，直接把相机贴到目标位置（离屏预览 / 自检用）。"""
        self.cx, self.cy = self.tcx, self.tcy
        self.log_scale = self.tlog
        self.hover_alpha = 1.0 if self.hovered is not None else 0.0

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._bg = None
        if self.root is not None and self.current is self.root:
            self.tlog = self._clamp_scale(self._fit_log(self.root.bbox))

    def _make_bg(self):
        dpr = self.devicePixelRatioF() or 1.0
        w, h = self.width(), self.height()
        pm = QPixmap(int(max(1, w * dpr)), int(max(1, h * dpr)))
        pm.setDevicePixelRatio(dpr)
        p = QPainter(pm)
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, BG_TOP)
        g.setColorAt(1, BG_BOTTOM)
        p.fillRect(QRectF(0, 0, w, h), g)
        rg = QRadialGradient(w * 0.5, h * 0.46, max(w, h) * 0.72)
        rg.setColorAt(0.0, QColor(30, 70, 120, 26))
        rg.setColorAt(1.0, QColor(0, 0, 0, 90))
        p.fillRect(QRectF(0, 0, w, h), rg)
        p.end()
        self._bg = pm

    # ---------- 坐标 ----------
    def world_to_screen(self, wx, wy):
        s = math.exp(self.log_scale)
        return QPointF(self.width() / 2.0 + (wx - self.cx) * s,
                       self.height() / 2.0 - (wy - self.cy) * s)

    def screen_to_world(self, pt):
        s = math.exp(self.log_scale)
        return (self.cx + (pt.x() - self.width() / 2.0) / s,
                self.cy - (pt.y() - self.height() / 2.0) / s)

    def _transform(self):
        s = math.exp(self.log_scale)
        return QTransform().translate(self.width() / 2.0, self.height() / 2.0) \
                           .scale(s, -s).translate(-self.cx, -self.cy)

    # ---------- 动画 ----------
    def _tick(self):
        now = time.perf_counter()
        if self._last_tick and now - self._last_tick < 0.0150:
            return                      # 定时器偶尔提前，硬性锁住 60FPS 上限
        dt = 0.016 if self._last_tick == 0.0 else now - self._last_tick
        self._last_tick = now
        dt = max(0.001, min(0.05, dt))
        if dt > 0:
            self._frame_fps = 0.9 * self._frame_fps + 0.1 * (1.0 / dt) if self._frame_fps else 1.0 / dt

        k = 1.0 - math.exp(-dt * CAM_EASE)
        self.cx += (self.tcx - self.cx) * k
        self.cy += (self.tcy - self.cy) * k
        self.log_scale += (self.tlog - self.log_scale) * k
        s = math.exp(self.log_scale)
        self._moving = (abs(self.tlog - self.log_scale) > 0.0015
                        or abs(self.tcx - self.cx) * s > 0.6
                        or abs(self.tcy - self.cy) * s > 0.6)

        target = 1.0 if self.hovered is not None else 0.0
        self.hover_alpha += (target - self.hover_alpha) * min(1.0, dt * 12.0)
        self.update()

    # ---------- 绘制 ----------
    def paintEvent(self, ev):
        t0 = time.perf_counter()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        w, h = self.width(), self.height()

        # 背景
        if self._bg is None:
            self._make_bg()
        p.drawPixmap(0, 0, self._bg)

        if self.root is None:
            p.end()
            return

        p.setTransform(self._transform())

        # 父级轮廓：当前展开区域的外框，给一点上下文
        if self.current is not None and self.current.path is not None:
            pen = QPen(PARENT_LINE, 1.0)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(self.current.path)

        # 行政区：先铺底色（关抗锯齿，边由后面的描边盖住，省一半开销）
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(LAND_FILL)
        for f in self.features:
            if f.path is not None:
                p.drawPath(f.path)

        # 再描边（静止时开抗锯齿保证细腻，镜头运动时关掉换帧率）
        p.setRenderHint(QPainter.RenderHint.Antialiasing, not self._moving)
        pen = QPen(BORDER, 1.0)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for f in self.features:
            if f.path is not None:
                p.drawPath(f.path)

        # 悬停高亮：单独补一层填充 + 亮边 + 外发光
        if self.hovered is not None and self.hover_alpha > 0.05:
            a = int(70 + 70 * self.hover_alpha)
            p.setBrush(QColor(70, 170, 255, a))
            pen = QPen(QColor(176, 232, 255, int(220 * self.hover_alpha)), 2.0)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.drawPath(self.hovered.path)
            glow = QPen(QColor(85, 175, 255, int(70 * self.hover_alpha)), 6.0)
            glow.setCosmetic(True)
            p.setPen(glow)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(self.hovered.path)

        p.setTransform(QTransform())
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._draw_labels(p)
        self._draw_hud(p, w, h)
        self._draw_rings(p)
        p.end()
        self._paint_ms = 0.85 * self._paint_ms + 0.15 * (time.perf_counter() - t0) * 1000.0

    def _draw_labels(self, p):
        font = ui_font(12)
        p.setFont(font)
        fm = p.fontMetrics()
        occupied = []          # 已占用的文字矩形，做简单避让

        def free(rect):
            for o in occupied:
                if o.intersects(rect):
                    return False
            return True

        pts = [(f, self.world_to_screen(f.label_pos.x(), f.label_pos.y())) for f in self.features
               if f.path is not None]
        # 面积大的先放，避免小地名抢位
        pts.sort(key=lambda t: t[0].bbox.width() * t[0].bbox.height(), reverse=True)

        for f, pos in pts:
            if not (-80 <= pos.x() <= self.width() + 80 and -40 <= pos.y() <= self.height() + 40):
                continue
            tl = self.world_to_screen(f.bbox.left(), f.bbox.top())
            br = self.world_to_screen(f.bbox.right(), f.bbox.bottom())
            bw, bh = abs(br.x() - tl.x()), abs(br.y() - tl.y())
            name = f.short_name()
            tw = fm.horizontalAdvance(name)
            th = fm.height()
            small = bw < 46 or bh < 30

            if small:
                # 小区域：画一个小点，名字向四周找空位挂出
                cands = [
                    QRectF(pos.x() + 9, pos.y() - th / 2 - 1, tw + 4, th + 2),
                    QRectF(pos.x() - tw - 13, pos.y() - th / 2 - 1, tw + 4, th + 2),
                    QRectF(pos.x() - tw / 2, pos.y() + 7, tw + 4, th + 2),
                    QRectF(pos.x() - tw / 2, pos.y() - th - 8, tw + 4, th + 2),
                ]
                rect = next((c for c in cands if free(c)), None)
                if rect is None:
                    continue
                occupied.append(rect)
                p.setBrush(QColor(120, 190, 240, 220))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(pos, 2.0, 2.0)
                p.setPen(QColor(0, 0, 0, 190))
                p.drawText(QPointF(rect.left() + 1, rect.top() + fm.ascent() + 1), name)
                p.setPen(QColor(200, 228, 255, 235))
                p.drawText(QPointF(rect.left(), rect.top() + fm.ascent()), name)
                continue

            placed = None
            for dy in (0, -16, 16, -32, 32):
                rect = QRectF(pos.x() - tw / 2 - 3, pos.y() + dy - th / 2, tw + 6, th + 2)
                if free(rect):
                    placed = (rect, dy)
                    break
            if placed is None:
                continue
            rect, dy = placed
            occupied.append(rect)
            at = QPointF(pos.x() - tw / 2, pos.y() + dy + fm.ascent() - th / 2)
            p.setPen(QColor(0, 0, 0, 190))
            p.drawText(at + QPointF(1, 1), name)
            p.setPen(QColor(200, 228, 255, 235))
            p.drawText(at, name)

            if f is self.hovered and self.hover_alpha > 0.4 and self.current.level == 0:
                p.setPen(ACCENT)
                p.drawText(QPointF(at.x(), at.y() + 15), "捏合 0.5 秒进入")
    def _draw_hud(self, p, w, h):
        font = ui_font(13)
        p.setFont(font)

        # 面包屑
        p.setPen(QColor(150, 200, 245, 230))
        p.drawText(24, 36, self.breadcrumb())
        p.setFont(ui_font(11))
        p.setPen(QColor(120, 160, 200, 190))
        p.drawText(24, 56, self.level_hint())
        # 说明
        p.setPen(QColor(110, 145, 180, 170))
        p.drawText(24, h - 22,
                   "右手悬停 + 捏合 0.5 秒进入 / 左手收一下再张开、保持 0.6 秒返回 / "
                   "左手捏合拖动：横移、上下缩放 / 鼠标也可操作")

        # 状态
        p.setPen(QColor(120, 160, 200, 190))
        txt = f"FPS {self._frame_fps:.0f}   推理 {self.status_infer:.0f}ms   绘制 {self._paint_ms:.0f}ms"
        p.drawText(w - 24 - p.fontMetrics().horizontalAdvance(txt), 36, txt)
        if self.status_note:
            p.setPen(QColor(255, 170, 120, 220))
            p.drawText(24, h - 44, self.status_note)

        # 悬停目标胶囊：光标旁边直接报名字
        if self.hovered is not None and self.cursor is not None and self.hover_alpha > 0.25:
            label = self.hovered.name
            if self.current.level == 0:
                label += "   ·   捏合进入"
            f2 = ui_font(12)
            p.setFont(f2)
            tw2 = p.fontMetrics().horizontalAdvance(label)
            box = QRectF(self.cursor.x() + 16, self.cursor.y() - 62, tw2 + 20, 26)
            if box.right() > w - 12:
                box.moveLeft(self.cursor.x() - box.width() - 16)
            if box.top() < 12:
                box.moveTop(self.cursor.y() + 22)
            p.setPen(QPen(QColor(120, 205, 255, 160), 1.0))
            p.setBrush(QColor(8, 18, 32, 235))
            p.drawRoundedRect(box, 5, 5)
            p.setPen(QColor(200, 235, 255, 240))
            p.drawText(QPointF(box.left() + 10, box.top() + 18), label)
            p.setFont(ui_font(13))

        # 层级切换横幅：淡出
        if self.banner_text:
            t = time.perf_counter() - self.banner_t0
            if t < 1.5:
                a = int(210 * (1.0 - t / 1.5) ** 2)
                p.setFont(ui_font(34))
                p.setPen(QColor(190, 226, 255, a))
                tw = p.fontMetrics().horizontalAdvance(self.banner_text)
                p.drawText(QPointF((w - tw) / 2.0, h - 64.0), self.banner_text)

    def _draw_rings(self, p):
        # 光标：一个小准星，让人知道指尖现在指哪
        if self.cursor is not None:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(120, 215, 255, 55), 7.0))
            p.drawEllipse(self.cursor, 7.0, 7.0)
            p.setPen(QPen(QColor(170, 235, 255, 210), 1.6))
            p.drawEllipse(self.cursor, 5.0, 5.0)
            p.setBrush(QColor(210, 245, 255, 235))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(self.cursor, 1.8, 1.8)
        self._ring(p, self.hold_pos, self.hold_progress, QColor(120, 215, 255, 235), "进入")
        self._ring(p, self.back_pos, self.back_progress, QColor(255, 175, 120, 235), "返回")

    def _ring(self, p, pos, progress, color, label):
        if pos is None or progress <= 0.01:
            return
        r = 22
        p.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(QColor(color.red(), color.green(), color.blue(), 70), 2.0)
        p.setPen(pen)
        p.drawEllipse(pos, r, r)
        pen = QPen(color, 3.0)
        p.setPen(pen)
        span = int(360 * min(1.0, progress))
        p.drawArc(QRectF(pos.x() - r, pos.y() - r, 2 * r, 2 * r), 90 * 16, -span * 16)
        p.setFont(ui_font(10))
        p.setPen(color)
        p.drawText(QPointF(pos.x() + r + 6, pos.y() + 4), label)

    # ---------- 鼠标兜底（没有摄像头也能看效果）----------
    def mouseMoveEvent(self, e):
        self.set_cursor(QPointF(e.position()))

    def leaveEvent(self, e):
        self.set_cursor(None)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if self.hovered is not None:
                self.drill(self.hovered)
        elif e.button() == Qt.MouseButton.RightButton:
            self.back()

    def wheelEvent(self, e):
        self.zoom_by(e.angleDelta().y() / 1200.0, QPointF(e.position()))
