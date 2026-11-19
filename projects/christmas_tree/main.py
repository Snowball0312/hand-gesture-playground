# -*- coding: utf-8 -*-
"""立体圣诞树 · 手势交互

左右手分工（和摄像头小窗里看到的一致：画面左侧是你的左手）

  左手捏合抓住并拖动  → 转着看树（松手带惯性）
  左手握拳 / 张开手掌 → 拉远 / 拉近（连续量，手停在中位就不动）
  右手食指尖          → 屏幕上有个圆环光标，指着哪个礼物就高亮哪个
  右手捏合            → 聚焦：礼物飞到屏幕中心，其余画面虚化
  聚焦态右手张开      → 打开礼物：物件弹出 + 粒子特效
  聚焦 / 打开态再捏合 → 回到树

快捷键
  C        显示/隐藏镜头小窗
  F        全屏
  ESC      退出
  鼠标拖动  转视角（没摄像头时也能看）
  滚轮      缩放
  1-6 / 空格 / O  无摄像头时手动演示：选礼物 / 捏合 / 打开
"""
import math
import sys
import time
from pathlib import Path

import numpy as np
from PyQt6.QtCore import Qt, QObject, pyqtSignal, QTimer
from PyQt6.QtGui import QSurfaceFormat
from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from OpenGL.GL import *
from OpenGL.GLU import *

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

import tree_rules as R  # noqa: E402
from audio import GiftAudio  # noqa: E402
from detector import TreeDetector  # noqa: E402
from renderer import Renderer  # noqa: E402
from gesture_core import (  # noqa: E402
    pinch_ratio, is_open, openness, hand_center_x, ClickDebounce,
)
from gesture_core.rules import INDEX_TIP  # noqa: E402

MODEL_PATH = str(ROOT / "assets" / "hand_landmarker.task")

PINCH_THRESHOLD = 0.30
AUTO_SPIN = 8.0            # 没有人碰的时候自动旋转（度/秒）

# 左手抓取旋转：识别线程只更新"速度"，渲染帧里再积分成角度。
# 识别回调只有 30~50Hz 且间隔不均匀，直接把位移加到角度上会一顿一顿的。
GRAB_GAIN = 320.0          # 食指尖每秒横移 1.0（整屏宽）→ 320°/s
PITCH_GAIN = 0.55          # 上下方向压低一些，免得树一下子翻过头
INERTIA_TAU = 0.18         # 松手后速度的衰减时间常数（秒）
# 俯仰范围：pitch 是相机抬高，正数从上方看、负数从下往上看。
# 上限定得高一点才有一眼俯视的感觉；再高树就会被自身树冠挡住。
PITCH_MIN, PITCH_MAX = -10.0, 55.0

# 左手开合度 → 缩放：张开到 ZOOM_NEUTRAL 以上就推近，握拳就推远，中间留死区
ZOOM_NEAR, ZOOM_FAR = 3.5, 6.0
ZOOM_NEUTRAL = 0.52
ZOOM_BAND = 0.10
ZOOM_SPEED = 0.80          # 单位：相机距离/秒（按超出死区的量成比例）

# 右手光标：位置在渲染帧里按这个时间常数追识别给的目标点。
# 大 → 更稳但更拖；0.045 时滞后约 1~2 帧到 30Hz 识别的那一格之间。
POINTER_TAU = 0.038
# 右手丢失后光标再保留多久（秒）：识别偶尔漏帧，立刻清掉会让圆环闪一下
POINTER_KEEP = 0.25

# 只有 2 号礼物盒（大笑那个角色）带音效，别的盒子开出来是安静的
AUDIO_GIFT = 1
# laugh_open.wav 是把原始 laugh.wav 开头 1.675s 的纯静音切掉后的版本
# （tools_trim_audio.py 生成），听到笑声的时刻比原来提前约 1.6s。
AUDIO_FILE = "laugh_open.wav"
# 起播再往后推多少秒（按需求微调用）：0 = 盒子一开就响。
AUDIO_DELAY_S = 0.0


class Bridge(QObject):
    signal = pyqtSignal(object)


class GLWidget(QOpenGLWidget):
    def __init__(self):
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(960, 600)

        self.renderer = Renderer(HERE)
        self.fsm = R.GiftFSM()

        # 右手：光标 + 捏合 / 张开
        self._pointer = R.PointerSmooth(0.45, tau=POINTER_TAU)
        self._pinch = False
        self._open = False
        self._pointing = False
        self._right_lost = None      # 右手丢失的起始时刻（用于宽限）
        self._pending_frame = None

        # 左手：抓取旋转（速度积分）+ 开合度缩放
        self._grab_active = False
        self._grab_pos = None
        self._grab_t = 0.0
        self._grab_vx = 0.0
        self._grab_vy = 0.0
        self._zoom_open = None

        self._pinch_db = ClickDebounce(0.55)
        self._open_prev = False
        self.audio = GiftAudio(HERE / "assets" / AUDIO_FILE)
        self.audio.preload()          # 启动即解码完毕，开盒那一下不再等加载
        self._audio_on = False
        self._audio_timer = QTimer(self)
        self._audio_timer.setSingleShot(True)
        self._audio_timer.timeout.connect(self._start_audio)

        # 鼠标/键盘调试
        self._mouse_last = None

        self._last_t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(0)

    # ---------- GL ----------
    def initializeGL(self):
        glEnable(GL_MULTISAMPLE)
        self.renderer.build()

    def resizeGL(self, w, h):
        pass

    def paintGL(self):
        if not self.renderer.built:
            return
        dpr = self.devicePixelRatioF()
        w = int(self.width() * dpr)
        h = int(self.height() * dpr)
        frame = self._pending_frame
        self._pending_frame = None
        self.renderer.draw(w, h, frame)

    # ---------- 手势 ----------
    def apply_hands(self, data):
        hands, frame = data
        if frame is not None:
            self._pending_frame = frame

        # 左右按掌心横坐标分：镜像是开着的，所以画面左半 = 用户的左手。
        # 两只手各管一摊，互不抢手势，也不用再"猜"哪只是交互手。
        left = right = None
        for lm in hands or ():
            if hand_center_x(lm) < 0.5:
                left = lm
            else:
                right = lm
        self._update_left(left)
        self._update_right(right)

    def _update_left(self, lm):
        """左手：捏合 = 抓住树；松开 = 用开合度缩放。

        抓取时只算速度、不动角度，真正的角度积分放到渲染帧里做，
        这样即使识别只有 40Hz，画面也是每帧平滑推进。
        """
        if lm is None or self.fsm.is_busy():
            self._grab_active = False
            self._grab_pos = None
            self._zoom_open = None
            # 连速度一起清掉：不然从聚焦态回到树的那一瞬，左手若还捏着，
            # 会带着进场前的旧速度把树甩一下
            self._grab_vx = self._grab_vy = 0.0
            return

        if pinch_ratio(lm) < PINCH_THRESHOLD:
            px = float(lm[INDEX_TIP].x)
            py = float(lm[INDEX_TIP].y)
            now = time.perf_counter()
            if self._grab_pos is not None:
                dt = min(max(now - self._grab_t, 1e-3), 0.12)
                vx = (px - self._grab_pos[0]) / dt
                vy = (py - self._grab_pos[1]) / dt
                self._grab_vx = 0.55 * self._grab_vx + 0.45 * vx
                self._grab_vy = 0.55 * self._grab_vy + 0.45 * vy
            else:
                self._grab_vx = self._grab_vy = 0.0
            self._grab_pos = (px, py)
            self._grab_t = now
            self._grab_active = True
            self._zoom_open = None
            return

        # 没捏合 → 开合度参与缩放。捏合时不喂，免得捏合瞬间的收指被当成"握拳拉远"
        self._grab_active = False
        self._grab_pos = None
        o = openness(lm)
        self._zoom_open = (o if self._zoom_open is None
                           else 0.55 * self._zoom_open + 0.45 * o)

    def _update_right(self, lm):
        """右手：食指尖驱动光标与选中，捏合确认、张开打开。"""
        if lm is None:
            self._pinch = self._open = False
            # 识别偶尔会漏掉一帧。立刻清光标会让圆环闪一下再出现，
            # 所以给一个短暂的宽限：这期间保持原样，超过时间才收回（在 _tick 里）。
            if self._right_lost is None:
                self._right_lost = time.perf_counter()
            return
        self._right_lost = None

        pinched = pinch_ratio(lm) < PINCH_THRESHOLD
        # 捏合时食指在往回缩，喂进去光标会往掌心滑，所以冻住目标不动
        if not pinched:
            self._pointer.feed((float(lm[INDEX_TIP].x), float(lm[INDEX_TIP].y)))

        # 只要右手没在捏，指尖在哪就算指哪——以前要求"食指单独伸出"，
        # 自然伸手时中指常常也跟着伸一半，于是指着却选不中。
        self._pointing = not pinched
        self._pinch = pinched
        self._open = (not pinched) and is_open(lm, 4)

    def _start_audio(self):
        self.audio.play()
        self._audio_on = True

    def _play_gift_audio(self, idx):
        """只有"大笑"那盒有声音，而且只在真的打开时播（选中/聚焦都不响）。"""
        if idx != AUDIO_GIFT:
            return
        if AUDIO_DELAY_S > 0:
            # 想在开盒动画之后一点点再响，就用这个延迟（默认 0，立即响）
            self._audio_on = True
            self._audio_timer.start(int(AUDIO_DELAY_S * 1000))
        else:
            self._start_audio()

    # ---------- 每帧 ----------
    def _tick(self):
        now = time.perf_counter()
        dt = 0.016 if self._last_t == 0.0 else now - self._last_t
        self._last_t = now
        dt = max(0.001, min(0.05, dt))

        r = self.renderer
        f = self.fsm

        # ---- 右手光标：按渲染帧推进，识别帧率再低也不会一顿一顿 ----
        self._pointer.step(dt)
        if (self._right_lost is not None
                and now - self._right_lost > POINTER_KEEP):
            # 宽限期过了才真的收走光标，中途重新识别到就不闪
            self._pointer.reset()
            self._pointing = False
            self._right_lost = None

        # ---- 左手抓取：按渲染帧积分速度，不跟识别帧率绑在一起 ----
        if self._grab_active and not f.is_busy():
            r.yaw += self._grab_vx * dt * GRAB_GAIN
            r.pitch = max(PITCH_MIN, min(PITCH_MAX,
                                         r.pitch + self._grab_vy * dt * GRAB_GAIN * PITCH_GAIN))
        else:
            # 松手后速度按时间常数衰减，树顺着手势滑一小段再停。
            # 必须用 dt 而不是每帧乘一个固定系数：这台机器 158fps，
            # 固定系数会让惯性几乎瞬间消失，换台机器手感又完全不同。
            decay = math.exp(-dt / INERTIA_TAU)
            self._grab_vx *= decay
            self._grab_vy *= decay

        if not f.is_busy() and not self._grab_active:
            r.yaw += AUTO_SPIN * dt

        # ---- 左手开合度 → 缩放：张开推近、握拳推远，中间保持不动 ----
        if self._zoom_open is not None and not f.is_busy():
            d = self._zoom_open - ZOOM_NEUTRAL
            if abs(d) > ZOOM_BAND:
                step = (abs(d) - ZOOM_BAND) * ZOOM_SPEED * dt
                r.target_dist = max(ZOOM_NEAR, min(ZOOM_FAR,
                                                   r.target_dist - math.copysign(step, d)))

        # 选中高亮：用平滑后的光标位置判断，指尖微抖不会让高亮来回跳
        if f.state == R.BROWSE:
            if self._pinch:
                # 捏合的瞬间食指会收回、不再是"指向"姿态，
                # 这里必须保持已选中项，否则捏合会被当成"没选中"而进不了聚焦。
                pass
            elif self._pointing and self._pointer.pos is not None:
                sp = r.gift_screen_positions(self.width(), self.height())
                # 带上当前选中项：靠回滞避免在两个礼物中间来回跳
                f.highlight(R.pick(sp, self._pointer.pos, current=f.selected))
            else:
                f.highlight(-1)

        # 捏合边沿
        if self._pinch_db.should_fire(self._pinch):
            st, changed = f.pinch()
            if changed and st == R.FOCUS:
                r.focus_idx = f.selected
                for b in r.bursts:
                    b.active = False

        # 张开边沿 → 打开礼物
        if not self._open_prev and self._open and f.state == R.FOCUS:
            _, changed = f.open_gift()
            if changed and r.focus_idx >= 0:
                r.bursts[r.focus_idx].emit(r.focus_center(2.0))
                self._play_gift_audio(r.focus_idx)
        self._open_prev = self._open

        # 盒子合上（再捏合退回）就掐掉音效，不用等它自己放完
        if self._audio_on and f.state != R.OPEN:
            self._audio_timer.stop()
            self.audio.stop()
            self._audio_on = False

        # 退场动画结束后清掉聚焦索引
        if f.state == R.BROWSE and r.focus_t < 0.03:
            r.focus_idx = -1

        r.state = f.state
        r.selected = f.selected
        r.pointer = self._pointer.pos
        r.pointer_hit = (f.state == R.BROWSE and f.selected >= 0)
        r.update(dt)
        self.update()

    # ---------- 输入 ----------
    def mousePressEvent(self, e):
        self._mouse_last = e.position()

    def mouseReleaseEvent(self, e):
        self._mouse_last = None

    def mouseMoveEvent(self, e):
        if self._mouse_last is None:
            return
        p = e.position()
        dx = p.x() - self._mouse_last.x()
        dy = p.y() - self._mouse_last.y()
        self._mouse_last = p
        if not self.fsm.is_busy():
            self.renderer.yaw += dx * 0.35
        self.renderer.pitch = max(PITCH_MIN, min(PITCH_MAX, self.renderer.pitch + dy * 0.30))

    def wheelEvent(self, e):
        step = e.angleDelta().y() / 120.0
        self.renderer.target_dist = max(
            ZOOM_NEAR, min(ZOOM_FAR, self.renderer.target_dist - step * 0.35))

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_C:
            self.renderer.show_camera = not self.renderer.show_camera
        elif k == Qt.Key.Key_F:
            win = self.window()
            if win.isFullScreen():
                win.showNormal()
            else:
                win.showFullScreen()
        elif k == Qt.Key.Key_Escape:
            self.window().close()
        elif k == Qt.Key.Key_Space:
            _, changed = self.fsm.pinch()
            if changed and self.fsm.state == R.FOCUS:
                self.renderer.focus_idx = self.fsm.selected
        elif k == Qt.Key.Key_O:
            if self.fsm.state == R.FOCUS and self.renderer.focus_idx >= 0:
                self.fsm.open_gift()
                self.renderer.bursts[self.renderer.focus_idx].emit(
                    self.renderer.focus_center(2.0))
                self._play_gift_audio(self.renderer.focus_idx)
        elif Qt.Key.Key_1 <= k <= Qt.Key.Key_6:
            idx = k - Qt.Key.Key_1
            if self.fsm.state == R.BROWSE:
                self.fsm.highlight(idx)
                self.fsm.pinch()
                self.renderer.focus_idx = idx
        else:
            super().keyPressEvent(e)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("立体圣诞树 · 手势交互")
        self.resize(1280, 800)
        self.gl = GLWidget()
        self.setCentralWidget(self.gl)

        self.bridge = Bridge()
        self.bridge.signal.connect(self.gl.apply_hands)
        self.det = TreeDetector(MODEL_PATH, on_hands=self._emit)
        self.det.start()

    def _emit(self, hands, frame):
        self.bridge.signal.emit((hands, frame))

    def closeEvent(self, e):
        self.det.stop()
        self.det.join(2000)
        super().closeEvent(e)


def main():
    fmt = QSurfaceFormat()
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    fmt.setSamples(4)
    fmt.setVersion(2, 1)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.NoProfile)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
