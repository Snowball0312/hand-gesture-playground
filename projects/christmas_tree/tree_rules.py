# -*- coding: utf-8 -*-
"""圣诞树的纯规则层：投影、指尖拾取、礼物状态机。

这里只有纯函数和纯状态机，不碰 OpenGL / Qt / 摄像头，
所以可以脱离图形环境做单元测试（tests/test_tree_rules.py）。

状态设计（与用户确认过的交互一致）：

    左手（画面左侧）
      · 拇食指捏合抓住并拖动 → 转着看树（由 main 按渲染帧积分速度）
      · 松开后用手掌开合度    → 张开拉近、握拳拉远

    右手（画面右侧）
      · 食指尖是屏幕上的圆环光标，压在哪个礼物上哪个高亮（selected）

    浏览态 BROWSE
      · 指尖指向某个礼物 → 该礼物高亮（selected）
      · 高亮时右手捏合   → 聚焦态 FOCUS
      · 没有选中时捏合    → 仍留在浏览态（不误触）

    聚焦态 FOCUS
      · 礼物已飞到屏幕中心、背景虚化
      · 右手张开         → 打开态 OPEN
      · 右手再捏合       → 退回浏览态

    打开态 OPEN
      · 礼物物件悬浮自转 + 粒子特效
      · 右手再捏合       → 退回浏览态
"""
import math
import time

BROWSE = "browse"
FOCUS = "focus"
OPEN = "open"

# 指尖距礼物屏幕位置小于该值（归一化坐标）才算"指向它"
SELECT_RADIUS = 0.16
# 指尖/礼物越界保护
_EPS = 1e-6
# 光标速度上限（归一化坐标/秒）：整屏宽约 1.0，人手快速划过 2.5 左右，
# 留到 3.5 足够跟手，同时挡掉抖动求导出来的尖峰
MAX_POINTER_SPEED = 3.0
# 上一次估出的速度在没有新目标点补充时按这个时间常数淡出
VEL_TAU = 0.10
# 预测位移上限（归一化坐标）：约 25px @1280，够抵消低通滞后，又不至于跑到手指前面
MAX_LEAD = 0.02


def project(point, cam_dist, aspect, fov_deg=45.0, cam_y=0.0, look_y=0.0):
    """世界坐标 → 归一化屏幕坐标 (x 向右, y 向下, 都在 0~1)。

    相机是绕原点抬高的一台机器：位置 (0, look_y + cam_y, cam_dist)，
    看向 (0, look_y, 0)。cam_y=0 就是平视，与旧行为完全一致。
    抬高相机（而不是把树翻过来）才能保证雪地永远水平、礼物永远压在地上。

    点在相机背后时返回 None。
    """
    x = float(point[0])
    y = float(point[1]) - (look_y + cam_y)
    z = float(point[2]) - cam_dist
    L = math.hypot(cam_y, cam_dist)
    if L < _EPS:
        return None
    # 视线方向 d=(0, -cam_y/L, -cam_dist/L)；相机基 s=(1,0,0)、u=(0, cos, -sin)
    depth = (-y * cam_y + (-z) * cam_dist) / L      # 到相机的正向距离
    if depth < 0.05:                               # 贴脸或身后
        return None
    y_c = (y * cam_dist - z * cam_y) / L
    f = 1.0 / math.tan(math.radians(fov_deg) * 0.5)
    ndc_x = (f / max(aspect, _EPS)) * x / depth
    ndc_y = f * y_c / depth
    return (ndc_x * 0.5 + 0.5, 0.5 - ndc_y * 0.5)


def pick(screen_positions, tip, radius=SELECT_RADIUS, current=-1,
         keep_radius=None, switch_margin=None):
    """返回离指尖最近、且在半径内的礼物下标；没有则 -1。

    current/keep_radius/switch_margin 构成回滞：已经选中的礼物在没有明显更近的
    候选时继续保留。没有回滞的话，指尖停在两个礼物中间，坐标抖一下就选 A、
    再抖一下选 B，高亮和光标尺寸跟着来回跳 —— 看起来就像卡了一下。
    但真有另一个礼物明显更近时还是要换过去，否则指着 B 却一直亮着 A。

    screen_positions: 每个礼物投影后的 (sx, sy)，不可见为 None
    tip: 食指尖归一化屏幕坐标
    """
    if keep_radius is None:
        keep_radius = radius * 1.25
    if switch_margin is None:
        switch_margin = radius * 0.18

    best, best_d = -1, radius
    for i, sp in enumerate(screen_positions):
        if sp is None:
            continue
        d = math.hypot(sp[0] - tip[0], sp[1] - tip[1])
        if d < best_d:
            best_d, best = d, i

    if 0 <= current < len(screen_positions) and current != best:
        sp = screen_positions[current]
        if sp is not None:
            d_cur = math.hypot(sp[0] - tip[0], sp[1] - tip[1])
            if d_cur < keep_radius and not (best >= 0
                                            and best_d < d_cur - switch_margin):
                return current
    return best


class GiftFSM:
    """礼物交互状态机。只处理状态与选中，不处理动画。"""

    def __init__(self):
        self.state = BROWSE
        self.selected = -1

    def reset(self):
        self.state = BROWSE
        self.selected = -1

    def highlight(self, idx):
        """浏览态下更新高亮；非浏览态不允许改选中。"""
        if self.state == BROWSE:
            self.selected = idx if idx >= 0 else -1
        return self.selected

    def pinch(self):
        """捏合上升沿。返回 (新状态, 是否发生了切换)。"""
        if self.state == BROWSE:
            if self.selected >= 0:
                self.state = FOCUS
                return self.state, True
            return self.state, False
        # FOCUS / OPEN 下再捏合 → 退回
        self.state = BROWSE
        self.selected = -1
        return self.state, True

    def open_gift(self):
        """张开上升沿。只在聚焦态生效。"""
        if self.state == FOCUS:
            self.state = OPEN
            return self.state, True
        return self.state, False

    def is_busy(self):
        """是否处于聚焦/打开（此时应冻结树的自动旋转与手势转动）。"""
        return self.state != BROWSE


class PointerSmooth:
    """食指光标：回调只喂目标点，位移在渲染帧里推进。

    识别只有 30~50Hz，画面却跑 150fps。旧做法在识别回调里按固定 alpha 混合，
    于是光标每 20~30ms 跳一格、中间四五个渲染帧完全静止 —— 看着就是一顿一顿。
    现在和左手抓取旋转同一套思路：feed() 只记目标（顺带估目标速度），
    step() 在每帧按 exp(-dt/tau) 追过去，识别再慢，画面也是每帧都在动。

    光标的两个要求互相打架：要稳（压掉指尖抖动），又要跟手（不能拖半拍）。
    单级低通只能二选一，所以加一步"按估计速度把目标往前推半个 tau"，
    把滞后抵掉一半，而抖动仍然只被衰减、不会被放大。

    捏合时食指会往回缩，调用方应停止 feed、让光标停在原地，
    否则光标会跟着收起的食指向掌心滑。
    """

    def __init__(self, alpha=0.45, tau=0.038, lead=1.0):
        self.alpha = alpha      # update() 的固定混合系数（保留：单帧/测试用）
        self.tau = tau          # feed() + step() 的时间常数（秒）
        self.lead = lead        # 按速度外推的比例（乘 tau），用来抵消低通滞后
        self.pos = None         # 画出来的位置
        self.target = None      # 最近一次识别到的原始点
        self.vel = (0.0, 0.0)   # 目标点的平滑速度（归一化坐标/秒）
        self._t = 0.0

    def feed(self, point, now=None):
        """识别回调里喂原始点。None 表示这一帧没有指尖，冻结目标。"""
        if point is None:
            return self.pos
        x, y = float(point[0]), float(point[1])
        t = time.perf_counter() if now is None else now
        if self.pos is None:
            # 第一个点直接落位：不要从屏幕中心飞过去
            self.pos = (x, y)
            self.target = (x, y)
            self.vel = (0.0, 0.0)
            self._t = t
            return self.pos
        if self.target is not None and self._t:
            # 间隔下限 12ms：识别结果偶尔会挤在一起送达（队列里排了两个），
            # 用真实间隔去求导会把速度算成十几倍，光标被"预测"甩到前面去
            dt = min(max(t - self._t, 0.012), 0.12)
            vx = 0.6 * self.vel[0] + 0.4 * (x - self.target[0]) / dt
            vy = 0.6 * self.vel[1] + 0.4 * (y - self.target[1]) / dt
            # 指尖的抖动在求导后会被放大，必须夹住上限，
            # 否则一次抖动会把光标提前甩出去（看着像"抽一下"）
            sp = math.hypot(vx, vy)
            if sp > MAX_POINTER_SPEED:
                vx, vy = vx * MAX_POINTER_SPEED / sp, vy * MAX_POINTER_SPEED / sp
            self.vel = (vx, vy)
        self._t = t
        self.target = (x, y)
        return self.pos

    def step(self, dt):
        """渲染帧里推进一次。返回当前（平滑后的）光标位置。"""
        if self.pos is None or self.target is None:
            return self.pos
        # 速度也要跟着衰减：手停住时不会再有新目标点进来，
        # 若一直拿旧速度外推，光标会先冲出去一点点再弹回来（停手时"抽一下"）
        dv = math.exp(-max(dt, 0.0) / VEL_TAU)
        self.vel = (self.vel[0] * dv, self.vel[1] * dv)
        lead = self.lead * self.tau
        ox, oy = self.vel[0] * lead, self.vel[1] * lead
        # 预测位移封顶：速度估得再大，光标最多领先目标这么远（约 25px @1280）。
        # 不封顶的话快速划过时光环会跑到手指前面一截，停手时再退回来。
        off = math.hypot(ox, oy)
        if off > MAX_LEAD:
            ox, oy = ox * MAX_LEAD / off, oy * MAX_LEAD / off
        tx = self.target[0] + ox
        ty = self.target[1] + oy
        k = 1.0 - math.exp(-max(dt, 0.0) / max(self.tau, 1e-4))
        self.pos = (self.pos[0] + (tx - self.pos[0]) * k,
                    self.pos[1] + (ty - self.pos[1]) * k)
        return self.pos

    def update(self, point):
        """固定 alpha 混合（旧的单帧接口，保留兼容）。"""
        if point is None:
            return self.pos
        x, y = float(point[0]), float(point[1])
        if self.pos is None:
            self.pos = (x, y)
        else:
            a = self.alpha
            self.pos = (a * x + (1.0 - a) * self.pos[0],
                        a * y + (1.0 - a) * self.pos[1])
        self.target = (x, y)
        return self.pos

    def reset(self):
        self.pos = None
        self.target = None
        self.vel = (0.0, 0.0)
        self._t = 0.0


def lerp(a, b, t):
    return a + (b - a) * t


def smoothstep(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def ease_out_cubic(t):
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3
