# -*- coding: utf-8 -*-
"""
双手 3D 地球交互
  屏幕左侧的手：拇食指捏合=按住，移动旋转地球（松手带惯性）
  屏幕右侧的手：张开程度控制镜头远近，越张开越靠近地球
  双手同时捏合 0.5 秒：进入 / 退出中国地图
    · 中国地图打开期间，一切手势都不再驱动地球（完全冻结），
      只有"双手同时捏合"可以退出
    · 地图淡出完毕后才重新接管手势，避免过渡期误操作
ESC 退出
"""
import math
import sys
import time
from pathlib import Path
import cv2
import numpy as np

from PyQt6.QtCore import Qt, QObject, pyqtSignal, QTimer
from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from OpenGL.GL import *
from OpenGL.GLU import *

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

import geo  # noqa: E402
from detector import Hand3dDetector  # noqa: E402
from rules import pinch_ratio, hand_center_x, openness  # noqa: E402
from gesture_core import ClickDebounce  # noqa: E402

MODEL_PATH = str(ROOT / "assets" / "hand_landmarker.task")
TEX_DIR = ROOT / "textures"

CAM_DIST_MIN = 1.18
CAM_DIST_MAX = 5.5
PINCH_THRESHOLD = 0.30
ZOOM_NEUTRAL = 0.52
ZOOM_BAND = 0.08
ZOOM_SPEED = 0.09
BASE_ROT_GAIN = 520.0
POLE_GUARD_DEG = 3.0        # 视角中心离北极小于该角度时，拒绝继续往上翻
MODE_SWITCH_COOLDOWN = 0.5  # 两次地图切换之间的最小间隔，防一次捏合连跳
MAP_FADE = 0.08             # 地图不透明度每帧逼近目标的比例
EARTH_READY_ALPHA = 0.04    # 地图残留低于此值，才把操作权交还地球

# 中国地图贴片：按经纬度贴在球面上（跟着地球转，转到背面就被地球挡住），
# 不是浮在屏幕前的平面。贴图由 tools_make_china.py 用等距圆柱投影生成，
# 正好覆盖下面这个经纬度范围，所以 1:1 贴上去就与球面上的中国重合。
CHINA_LON_MIN, CHINA_LON_MAX = 73.0, 135.0
CHINA_LAT_MIN, CHINA_LAT_MAX = 18.0, 53.5
# 以中国地理中心为原点等比放大。1.0 = 与疆域严丝合缝；1.15 就是整体放大 15%，
# 内容跟着放大（不是只把边框撑大），省界更清楚但会外溢到邻国一点。
MAP_SCALE = 1.15
CHINA_PATCH_R = 1.004       # 贴片半径，略高于球面 1.0，避免 z-fighting
CHINA_PATCH_NX = 96         # 经度方向网格数
CHINA_PATCH_NY = 64         # 纬度方向网格数

MODE_EARTH = "earth"
MODE_MAP = "map"

# 大头针：钉在北京，方向与朝外的旋转都由经纬度算出
PIN_DIR = geo.latlon_to_dir(geo.PIN_LAT, geo.PIN_LON)
PIN_ROT = geo.rotation_to_align(PIN_DIR)


def rotation(axis, deg):
    """绕世界坐标轴的 3x3 旋转矩阵。"""
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    if axis == "x":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=float)
    if axis == "y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=float)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=float)


def initial_rotation(lat=geo.CHINA_LAT, lon=geo.CHINA_LON):
    """构造“目标点正对镜头且北朝上”的初始姿态。

    球面坐标系里北极在 +Z，所以三根轴取：
      east  = 经度增加方向
      north = 纬度增加方向 = dir × east
      dir   = 目标点法线
    用这三根轴做**行**（不是列），矩阵就把
      东 → 屏幕右 +X、北 → 屏幕上 +Y、目标点 → 朝观众 +Z
    于是屏幕右是东、上是北，地图不再横躺着。

    旧版只用 rot_x/rot_y 两个角度，自由度不够控制“画面旋转”，
    这就是之前中国虽然是正面却像被转了 90° 的原因。
    """
    d = np.array(geo.latlon_to_dir(lat, lon), dtype=float)
    lam = math.radians(lon)
    east = np.array([math.cos(lam), math.sin(lam), 0.0])
    east /= np.linalg.norm(east)
    north = np.cross(d, east)
    north /= np.linalg.norm(north)
    return np.array([east, north, d])


def to_gl(mat33):
    """3x3 旋转矩阵 → OpenGL 需要的列主序 4x4。"""
    m = np.eye(4, dtype=np.float32)
    m[:3, :3] = mat33
    return m.T.flatten()


def rotation_about(axis, deg):
    """绕任意世界轴旋转的 3x3 矩阵（罗德里格斯公式）。"""
    ax = np.asarray(axis, dtype=float)
    n = np.linalg.norm(ax)
    if n < 1e-12:
        return np.eye(3)
    ax = ax / n
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    x, y, z = ax
    return np.array([
        [c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
        [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
        [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)],
    ])


def slerp_toward(cur, target, k):
    """把 cur 朝 target 转过去 k 比例（沿最短旋转弧），返回 (新矩阵, 是否到位)。"""
    d = target @ cur.T
    tr = float(np.clip((np.trace(d) - 1.0) * 0.5, -1.0, 1.0))
    ang = math.degrees(math.acos(tr))
    if ang < 0.15:
        return target.copy(), True
    axis = np.array([d[2, 1] - d[1, 2], d[0, 2] - d[2, 0], d[1, 0] - d[0, 1]])
    if np.linalg.norm(axis) < 1e-9:     # 180° 附近，轴退化
        return target.copy(), True
    return rotation_about(axis, ang * k) @ cur, False


def load_texture(path, alpha=False, boost=1.0):
    # cv2.imread 不支持中文路径，用 np.fromfile + imdecode 读
    data = np.fromfile(str(path), dtype=np.uint8)
    flag = cv2.IMREAD_UNCHANGED if alpha else cv2.IMREAD_COLOR
    img = cv2.imdecode(data, flag)
    if alpha:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
        fmt = GL_RGBA
    else:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        fmt = GL_RGB
    img = cv2.flip(img, 0)
    if boost != 1.0:
        img = np.clip(img.astype(np.float32) * boost, 0, 255).astype(np.uint8)
    h, w = img.shape[:2]
    tex = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, tex)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
    gluBuild2DMipmaps(GL_TEXTURE_2D, fmt, w, h, fmt, GL_UNSIGNED_BYTE, img.tobytes())
    return tex


class Bridge(QObject):
    signal = pyqtSignal(object)


class GLWidget(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rot = initial_rotation()      # 3x3：物体坐标 → 世界坐标
        self.cam_dist = 3.2
        self.target_dist = 3.2
        self.cloud_rot = 0.0
        self._quad = None
        self._tex_day = self._tex_clouds = self._tex_lights = self._tex_china = 0
        self._stars = None

        # 模式机：只有 EARTH 模式才允许手势驱动地球
        self.mode = MODE_EARTH
        self.china_alpha = 0.0             # 地图不透明度，纯视觉，不参与判定
        self._mode_switch = ClickDebounce(MODE_SWITCH_COOLDOWN)
        self._focus_target = None           # 进地图时地球自动转回中国的目标姿态
        self._china_list = 0                # 球面贴片显示列表（initializeGL 里编译）

        self._zoom_smooth = 0.5
        self._pinch_active = False
        self._last_pinch_pos = None
        self._last_pinch_t = 0.0
        self._vel_x = 0.0
        self._vel_y = 0.0
        self._last_tick = 0.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(0)

    def set_mode(self, mode):
        """切换模式。进入地图时清掉全部运动状态，退出后地球不会突然甩一下。"""
        if mode == self.mode:
            return
        self.mode = mode
        self._vel_x = self._vel_y = 0.0
        self._pinch_active = False
        self._last_pinch_pos = None
        self._last_pinch_t = 0.0
        # 地图贴在球面中国上，如果此刻中国在背面就看不见了，所以进地图时自动转回去
        self._focus_target = initial_rotation() if mode == MODE_MAP else None
        title = ("双手 3D 地球 · 中国地图（双手同时捏合返回）"
                 if mode == MODE_MAP else "双手 3D 地球")
        try:
            self.window().setWindowTitle(title)
        except Exception:
            pass

    def earth_ready(self):
        """地图淡出到几乎看不见，才把手势交还地球。"""
        return self.mode == MODE_EARTH and self.china_alpha < EARTH_READY_ALPHA

    def apply_spin(self, dx_deg, dy_deg):
        """按屏幕方向增量旋转；北极顶到画面中心时拒绝继续往上翻。"""
        step = rotation("y", dx_deg) @ rotation("x", dy_deg) @ self.rot
        pole_z = float((step @ np.array([0.0, 0.0, 1.0]))[2])
        if math.degrees(math.acos(max(-1.0, min(1.0, pole_z)))) < POLE_GUARD_DEG:
            return
        self.rot = step

    def apply_hands(self, hands):
        rot_hand = None
        zoom_hand = None
        for lm in hands or []:
            if hand_center_x(lm) < 0.5:
                rot_hand = lm
            else:
                zoom_hand = lm

        # 双手同时捏合 = 进入 / 退出中国地图（带冷却，避免一次捏合连跳两次）
        both_pinch = (rot_hand is not None and zoom_hand is not None
                      and pinch_ratio(rot_hand) < PINCH_THRESHOLD
                      and pinch_ratio(zoom_hand) < PINCH_THRESHOLD)
        if self._mode_switch.should_fire(both_pinch):
            self.set_mode(MODE_MAP if self.mode == MODE_EARTH else MODE_EARTH)
            return

        # 地图打开中、或地图还没淡出干净：手势一律不作用于地球
        if not self.earth_ready():
            self._pinch_active = False
            self._last_pinch_pos = None
            return

        # 地球模式
        if zoom_hand is not None:
            o = openness(zoom_hand)
            self._zoom_smooth = 0.6 * self._zoom_smooth + 0.4 * o
            if self._zoom_smooth > ZOOM_NEUTRAL + ZOOM_BAND:
                self.target_dist -= (self._zoom_smooth - ZOOM_NEUTRAL - ZOOM_BAND) * ZOOM_SPEED
            elif self._zoom_smooth < ZOOM_NEUTRAL - ZOOM_BAND:
                self.target_dist += (ZOOM_NEUTRAL - ZOOM_BAND - self._zoom_smooth) * ZOOM_SPEED
            self.target_dist = max(CAM_DIST_MIN, min(CAM_DIST_MAX, self.target_dist))

        if rot_hand is not None and pinch_ratio(rot_hand) < PINCH_THRESHOLD:
            px, py = rot_hand[8].x, rot_hand[8].y
            now = time.perf_counter()
            if self._last_pinch_pos is not None:
                dt = max(1e-3, now - self._last_pinch_t)
                vx = (px - self._last_pinch_pos[0]) / dt
                vy = (py - self._last_pinch_pos[1]) / dt
                self._vel_x = 0.6 * self._vel_x + 0.4 * vx
                self._vel_y = 0.6 * self._vel_y + 0.4 * vy
            else:
                self._vel_x = self._vel_y = 0.0
            self._last_pinch_pos = (px, py)
            self._last_pinch_t = now
            self._pinch_active = True
        else:
            self._pinch_active = False
            self._last_pinch_pos = None

    def _tick(self):
        now = time.perf_counter()
        dt = 0.016 if self._last_tick == 0.0 else now - self._last_tick
        self._last_tick = now
        dt = max(0.001, min(0.05, dt))

        # 识别线程只更新速度；旋转按渲染帧率积分，丝滑不卡
        # 越靠近地球，旋转灵敏度越低，避免贴脸时一划就飞
        rot_gain = BASE_ROT_GAIN * (self.cam_dist / 3.2)
        if self._pinch_active and self.mode == MODE_EARTH:
            self.apply_spin(self._vel_x * dt * rot_gain,
                            self._vel_y * dt * rot_gain)
        else:
            self._vel_x *= 0.92
            self._vel_y *= 0.92

        # 进地图时把地球平滑转回中国（否则贴片可能正好在背面，看不见）
        if self._focus_target is not None and self.mode == MODE_MAP:
            self.rot, done = slerp_toward(self.rot, self._focus_target, 0.16)
            if done:
                self._focus_target = None

        target_alpha = 1.0 if self.mode == MODE_MAP else 0.0
        self.china_alpha += (target_alpha - self.china_alpha) * MAP_FADE
        self.cam_dist += (self.target_dist - self.cam_dist) * 0.12
        self.cloud_rot += 0.02
        self.update()

    def initializeGL(self):
        glClearColor(0.008, 0.010, 0.025, 1.0)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_CULL_FACE)
        glCullFace(GL_BACK)
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glLightfv(GL_LIGHT0, GL_POSITION, [5.0, 2.0, 3.0, 1.0])
        glLightfv(GL_LIGHT0, GL_DIFFUSE, [1.05, 1.00, 0.92, 1.0])
        glLightfv(GL_LIGHT0, GL_SPECULAR, [0.35, 0.35, 0.35, 1.0])
        glLightModelfv(GL_LIGHT_MODEL_AMBIENT, [0.28, 0.28, 0.32, 1.0])

        self._quad = gluNewQuadric()
        gluQuadricNormals(self._quad, GLU_SMOOTH)
        self._tex_day = load_texture(TEX_DIR / "day4k.jpg", boost=1.12)
        self._tex_clouds = load_texture(TEX_DIR / "clouds.png", alpha=True)
        self._tex_lights = load_texture(TEX_DIR / "lights.png")
        self._tex_china = load_texture(HERE / "textures" / "china_map.png", alpha=True)

        rng = np.random.default_rng(7)
        v = rng.normal(size=(800, 3))
        v /= np.linalg.norm(v, axis=1, keepdims=True)
        self._stars = v * 30.0

        self._build_china_patch()

    def _build_china_patch(self):
        """把“贴在球面上的中国地图”编译成显示列表。

        贴片是物体坐标系里的球面网格，所以会跟着 self.rot 一起转，
        转到地球背面时被球体本身挡住——这就是“粘在中国上”而不是浮在屏幕前。
        纹理坐标按贴图覆盖的经纬度线性映射：1:1 时与球面中国重合，
        MAP_SCALE 放大时图片内容等比放大铺满更大的经纬度范围（而不是只撑边框）。

        用显示列表而不是 client array：这台机器上 glVertexPointer + numpy
        画出来是乱的（整屏被三角形盖住），编译进列表最稳。
        """
        lon_c = 0.5 * (CHINA_LON_MIN + CHINA_LON_MAX)
        lat_c = 0.5 * (CHINA_LAT_MIN + CHINA_LAT_MAX)
        half_lon = 0.5 * (CHINA_LON_MAX - CHINA_LON_MIN) * MAP_SCALE
        half_lat = 0.5 * (CHINA_LAT_MAX - CHINA_LAT_MIN) * MAP_SCALE
        lon0, lon1 = lon_c - half_lon, lon_c + half_lon
        lat0, lat1 = lat_c - half_lat, lat_c + half_lat

        nx, ny = CHINA_PATCH_NX, CHINA_PATCH_NY
        lats = np.linspace(lat0, lat1, ny + 1)
        lons = np.linspace(lon0, lon1, nx + 1)
        dirs = geo.latlon_to_dir_grid(lats, lons) * CHINA_PATCH_R

        # 贴图经 load_texture 的 cv2.flip(img, 0) 翻转后，t=0 对应原图底边（南），
        # 所以 v 由南向北 0→1，与纬度方向一致。
        u = (lons - lon0) / (lon1 - lon0)
        v = (lats - lat0) / (lat1 - lat0)

        if self._china_list:
            glDeleteLists(self._china_list, 1)
        self._china_list = glGenLists(1)
        glNewList(self._china_list, GL_COMPILE)
        glBegin(GL_QUADS)
        for i in range(ny):
            for j in range(nx):
                # A(南西) → B(南东) → C(北东) → D(北西)，从球外看逆时针
                for (ii, jj) in ((i, j), (i, j + 1), (i + 1, j + 1), (i + 1, j)):
                    d = dirs[ii, jj]
                    glTexCoord2f(float(u[jj]), float(v[ii]))
                    glVertex3f(float(d[0]), float(d[1]), float(d[2]))
        glEnd()
        glEndList()

    def resizeGL(self, w, h):
        glViewport(0, 0, w, h)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(45, w / max(1, h), 0.1, 100.0)
        glMatrixMode(GL_MODELVIEW)

    def _draw_stars(self):
        glDisable(GL_LIGHTING)
        glDisable(GL_TEXTURE_2D)
        glDepthMask(GL_FALSE)
        glPointSize(1.3)
        glBegin(GL_POINTS)
        for x, y, z in self._stars:
            glColor3f(0.85, 0.88, 1.0)
            glVertex3f(x, y, z)
        glEnd()
        glDepthMask(GL_TRUE)

    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()
        gluLookAt(0, 0, self.cam_dist, 0, 0, 0, 0, 1, 0)
        self._draw_stars()

        glPushMatrix()
        glMultMatrixf(to_gl(self.rot))

        # 大气辉光
        glDisable(GL_LIGHTING)
        glDisable(GL_TEXTURE_2D)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE)
        glDepthMask(GL_FALSE)
        glCullFace(GL_FRONT)
        glColor4f(0.25, 0.50, 1.00, 0.10)
        gluSphere(self._quad, 1.12, 48, 48)
        glColor4f(0.12, 0.30, 0.90, 0.04)
        gluSphere(self._quad, 1.25, 48, 48)
        glCullFace(GL_BACK)
        glDepthMask(GL_TRUE)

        # 地球本体
        glEnable(GL_TEXTURE_2D)
        glEnable(GL_LIGHTING)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glBindTexture(GL_TEXTURE_2D, self._tex_day)
        gluQuadricTexture(self._quad, GL_TRUE)
        gluSphere(self._quad, 1.0, 64, 64)

        # 夜灯
        glDisable(GL_LIGHTING)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE)
        glDepthMask(GL_FALSE)
        glBindTexture(GL_TEXTURE_2D, self._tex_lights)
        glColor4f(1.0, 0.85, 0.55, 0.65)
        gluSphere(self._quad, 1.003, 48, 48)
        glDepthMask(GL_TRUE)

        # 中国地图贴片：贴在球面上，跟着地球一起转；转到背面会被球体挡住。
        # 半径 1.004 比球面略高，避免与地表 z-fighting。
        if self.china_alpha > 0.01 and self._china_list:
            glDisable(GL_LIGHTING)
            glEnable(GL_TEXTURE_2D)
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glDepthMask(GL_FALSE)
            glBindTexture(GL_TEXTURE_2D, self._tex_china)
            glColor4f(1, 1, 1, self.china_alpha)
            glCallList(self._china_list)
            glDepthMask(GL_TRUE)
            glDisable(GL_BLEND)
            # 注意：这里不能 glEnable(GL_LIGHTING)。后面紧跟着的云层和针都是在
            # 无光照状态下画的，一旦开回光照，glColor4f 的 alpha 会被材质 alpha
            # 顶掉，云层就以不透明白色铺满整个球。

        # 云层：看地图时调淡，不然云会把省界糊住
        # 这里必须自己开混合：上面贴片块会关掉 GL_BLEND，原代码是依赖大气那步
        # 一直开着混合的，关掉后云层会以不透明白色铺满整个球。
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glPushMatrix()
        glRotatef(self.cloud_rot, 0, 1, 0)
        glBindTexture(GL_TEXTURE_2D, self._tex_clouds)
        glColor4f(1, 1, 1, 0.55 * (1.0 - 0.85 * self.china_alpha))
        gluSphere(self._quad, 1.018, 48, 48)
        glPopMatrix()

        # 中国立体大头针：位置和朝向都由经纬度算出，钉在北京并沿法线朝外。
        # 旧版把旋转轴写成了 z×d 的相反数，针杆其实是扎进地球里的。
        glDisable(GL_LIGHTING)
        glDisable(GL_TEXTURE_2D)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE)
        glDepthMask(GL_FALSE)
        glPushMatrix()
        glTranslatef(PIN_DIR[0], PIN_DIR[1], PIN_DIR[2])
        glRotatef(PIN_ROT[0], PIN_ROT[1], PIN_ROT[2], PIN_ROT[3])
        glColor4f(1.0, 0.2, 0.2, 1.0)
        gluSphere(self._quad, 0.03, 20, 20)
        glTranslatef(0.0, 0.0, 0.02)
        glColor4f(1.0, 0.35, 0.35, 1.0)
        gluCylinder(self._quad, 0.012, 0.004, 0.16, 12, 12)
        glPopMatrix()
        glDepthMask(GL_TRUE)

        glColor4f(1, 1, 1, 1)
        glDisable(GL_BLEND)
        glPopMatrix()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("双手 3D 地球")
        self.resize(1280, 800)
        self.gl = GLWidget()
        self.setCentralWidget(self.gl)

        self.bridge = Bridge()
        self.bridge.signal.connect(self.gl.apply_hands)
        self.det = Hand3dDetector(MODEL_PATH, on_hands=self._emit)
        self.det.start()

    def _emit(self, hands):
        self.bridge.signal.emit(hands)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()

    def closeEvent(self, e):
        self.det.stop()
        self.det.join(2000)
        super().closeEvent(e)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
