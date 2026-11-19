# -*- coding: utf-8 -*-
"""2D 中国地图的手势控制器（从 china_roam 合并进来，hand_3d 自包含）。

  屏幕右侧的手：食指移动 = 光标；悬停某省 + 捏合 0.5 秒 = 进入下一级
  屏幕左侧的手：捏合拖动 = 横移 + 上下缩放；先收再张开 0.6 秒 = 返回
"""
import time

from PyQt6.QtCore import QObject, QPointF, QTimer

from gesture_core import pinch_ratio, openness, hand_center_x

PINCH_THRESHOLD = 0.30
DRILL_HOLD = 0.50
BACK_HOLD = 0.60
DRAG_ZOOM = 0.0045
CURSOR_EMA = 0.5
HAND_LOST_GRACE = 0.45


class GestureController(QObject):
    """把 landmarks 翻译成地图动作；定时器负责推进“蓄力”进度。"""

    def __init__(self, view, tracker, parent=None):
        super().__init__(parent)
        self.view = view
        self.tracker = tracker
        self._hands = []
        self._has_right = False
        self._hand_mode = False
        self._last_seen = 0.0
        self._last_t = time.perf_counter()

        self.cright = None
        self.right_pinch = False
        self.drill_progress = 0.0
        self._lock_until_release = False

        self.left_pinch = False
        self.left_palm = False
        self.left_pos = None
        self._left_prev = None
        self.back_progress = 0.0
        self._back_armed = False
        self._closed_seen = False      # 见过“不捏合的收拢”，才允许武装返回
        self._left_open = 1.0
        self._left_lo_prev = 1.0

        self._note = ""
        self._note_until = 0.0

        # 嵌入 hand_3d 时由主窗口接管：active=False 不响应手势；
        # 在中国这一层再返回就触发 on_back_at_root（退回地球）。
        self.active = True
        self.on_back_at_root = None

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.tick)
        self._timer.start(16)

    def on_hands(self, hands):
        self._hands = hands or []
        if self._hands:
            self._last_seen = time.perf_counter()
            self._hand_mode = True

    def reset_for_entry(self):
        """进地图时把手势状态清零（进图靠“双手同时捏合”，不能让它延续成地图动作）。

        不带这一步的话，玩家进图后往往还捏着、隔一会儿才松手：
          · 左手一松 = “捏合 → 张开” = 返回手势 → 刚进图就被弹回地球；
          · 右手落点如果正好压在某个省上，0.5 秒后直接钻进那个省。
        所以进来时要求：右手必须先松开一次（`_lock_until_release`），
        左手必须先出现一次“不捏合的收拢”（`_closed_seen`）才允许武装返回。
        """
        self._hands = []
        self._has_right = False
        self.cright = None
        self.right_pinch = False
        self.drill_progress = 0.0
        self._lock_until_release = True

        self.left_pinch = False
        self.left_palm = False
        self.left_pos = None
        self._left_prev = None
        self.back_progress = 0.0
        self._back_armed = False
        self._closed_seen = False
        self._left_open = 1.0
        self._left_lo_prev = 1.0

    def tick(self):
        if not self.active:
            self._last_t = time.perf_counter()
            return
        now = time.perf_counter()
        dt = max(0.001, min(0.05, now - self._last_t))
        self._last_t = now

        self._read_hands(dt)
        self._advance(dt)
        self._push_view(now)

    def _read_hands(self, dt):
        right = left = None
        for lm in self._hands:
            if hand_center_x(lm) < 0.5:
                left = lm
            else:
                right = lm

        w, h = self.view.width(), self.view.height()

        if right is not None:
            px = right[8].x * w
            py = right[8].y * h
            if self.cright is None:
                self.cright = QPointF(px, py)
            else:
                a = CURSOR_EMA
                self.cright = QPointF(a * px + (1 - a) * self.cright.x(),
                                      a * py + (1 - a) * self.cright.y())
            self.right_pinch = pinch_ratio(right) < PINCH_THRESHOLD
            if self._lock_until_release and not self.right_pinch:
                self._lock_until_release = False
            self._has_right = True
        else:
            self._has_right = False
            self.right_pinch = False
            # 这里故意不清 _lock_until_release：手不在画面里不等于“松开过一次”，
            # 只有真看到一次非捏合，才允许重新蓄力。

        if left is not None:
            lo = openness(left)
            self._left_open = lo
            self.left_pinch = pinch_ratio(left) < PINCH_THRESHOLD
            self.left_palm = (not self.left_pinch) and lo > 0.82
            # 边沿触发：先收（<0.60）再张开，才武装“返回”，
            # 否则左手一直摊着，一进省就被弹回去。
            # 关键细节：捏合不算“收”。进地图靠的就是双手同时捏合，
            # 玩家进图后一松手就是“捏合 → 张开”，若把这步当成返回，
            # 刚进地图零点几秒就被弹回地球（见 reset_for_entry）。
            if self.left_pinch:
                # 捏合既不算“收”，也不留下“收过”的痕迹：把 prev 归到张开，
                # 松手那一下就不会被当成“收 → 张”。
                self._back_armed = False
                self._left_lo_prev = 1.0
            else:
                if lo < 0.60:
                    self._back_armed = False
                    self._closed_seen = True
                elif self.left_palm and self._closed_seen and self._left_lo_prev < 0.60:
                    self._back_armed = True
                self._left_lo_prev = lo
            tip = QPointF(left[8].x * w, left[8].y * h)
            self.left_pos = tip
            if self.left_pinch:
                if self._left_prev is not None:
                    dx = tip.x() - self._left_prev.x()
                    dy = tip.y() - self._left_prev.y()
                    if abs(dx) < 220 and abs(dy) < 220:
                        if abs(dx) > 0.5:
                            self.view.pan_pixels(dx, 0)
                        if abs(dy) > 1.5:
                            self.view.zoom_by(-dy * DRAG_ZOOM)
                self._left_prev = tip
            else:
                self._left_prev = None
        else:
            self.left_pinch = False
            self.left_palm = False
            self.left_pos = None
            self._left_prev = None

    def _advance(self, dt):
        if self._has_right and self.cright is not None:
            hovered = self.view.set_cursor(self.cright)
        else:
            hovered = None
            if self._hand_mode and time.perf_counter() - self._last_seen > HAND_LOST_GRACE:
                self.view.set_cursor(None)
                self.cright = None

        pinching = self.right_pinch and not self._lock_until_release
        can_drill = hovered is not None and hovered.level == 1
        if pinching and can_drill and self.cright is not None:
            self.drill_progress += dt / DRILL_HOLD
            if self.drill_progress >= 1.0:
                ok = self.view.drill(hovered)
                self._say(f"{hovered.name} 暂无下级边界" if not ok else "")
                self.drill_progress = 0.0
                self._lock_until_release = True
        else:
            self.drill_progress = 0.0

        if self.left_palm and self._back_armed:
            self.back_progress += dt / BACK_HOLD
            if self.back_progress >= 1.0:
                if self.view.back():
                    self._say("")
                elif self.on_back_at_root is not None:
                    self.on_back_at_root()
                else:
                    self._say("已经在最外层")
                self.back_progress = 0.0
                self._back_armed = False
        else:
            self.back_progress = 0.0

        self.view.set_status(fps=self.tracker.fps,
                             infer=self.tracker.last_infer_ms,
                             note=self._note if time.perf_counter() < self._note_until else "")
        if self.tracker.error:
            self.view.set_status(note=self.tracker.error)

    def _push_view(self, now):
        self.view.set_hold(self.drill_progress, self.cright if self._has_right else None)
        pos = self.left_pos if self.left_palm else None
        self.view.set_back_hold(self.back_progress, pos)

    def _say(self, text, secs=3.0):
        self._note = text
        self._note_until = time.perf_counter() + secs
