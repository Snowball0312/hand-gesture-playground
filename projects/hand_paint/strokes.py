# -*- coding: utf-8 -*-
"""矢量笔画管理：每一笔是点序列，支持命中、拖动、删除、渲染。"""
import math
import numpy as np
import cv2


class Stroke:
    __slots__ = ("points", "width")

    def __init__(self, width=2):
        self.points = []
        self.width = width


class StrokeManager:
    def __init__(self):
        self.strokes = []
        self.current = None

    def begin(self):
        s = Stroke()
        self.strokes.append(s)
        self.current = s
        return s

    def extend(self, x, y):
        if self.current is None:
            self.begin()
        self.current.points.append((float(x), float(y)))

    def end(self):
        self.current = None

    @staticmethod
    def _seg_dist(px, py, ax, ay, bx, by):
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        qx, qy = ax + t * dx, ay + t * dy
        return math.hypot(px - qx, py - qy)

    def hit(self, x, y, radius):
        """返回距离 (x,y) 最近且在 radius 内的笔画，找不到返回 None。"""
        best, best_d = None, radius
        for s in self.strokes:
            p = s.points
            for i in range(1, len(p)):
                d = self._seg_dist(x, y, *p[i - 1], *p[i])
                if d < best_d:
                    best_d, best = d, s
        return best

    def move(self, stroke, dx, dy):
        stroke.points = [(px + dx, py + dy) for px, py in stroke.points]

    def delete_near(self, x, y, radius):
        s = self.hit(x, y, radius)
        if s:
            self.strokes.remove(s)
            if self.current is s:
                self.current = None
        return s

    def render(self, canvas):
        # 黑色投影保证在摄像头画面上可读，再叠淡青辉光和青白色笔芯
        shadow = (25, 25, 25)
        glow = (180, 140, 40)    # BGR
        core = (255, 245, 220)   # BGR
        for s in self.strokes:
            p = s.points
            if len(p) == 1:
                cv2.circle(canvas, (int(p[0][0]), int(p[0][1])), 2, core, -1, cv2.LINE_AA)
                continue
            if len(p) < 2:
                continue
            arr = np.array([(int(x), int(y)) for x, y in p],
                           dtype=np.int32).reshape(-1, 1, 2)
            cv2.polylines(canvas, [arr], False, shadow, 10, cv2.LINE_AA)
            cv2.polylines(canvas, [arr], False, glow, 6, cv2.LINE_AA)
            cv2.polylines(canvas, [arr], False, core, 2, cv2.LINE_AA)
