# -*- coding: utf-8 -*-
"""圣诞树的 3D 几何：松树、彩球挂饰、螺旋灯带、顶星、地面、
6 个礼物盒、6 张礼物人物卡（打开后缓慢自转的 2D 贴图）。

静态几何编译进显示列表，保证每帧只是几百次 glCallList，跑满 60fps 不费劲。
"""
import math
from pathlib import Path

import cv2
import numpy as np
from OpenGL.GL import *
from OpenGL.GLU import *

# ---------- 调色 ----------
GREEN_BASE = (0.062, 0.200, 0.083)
GREEN_MID = (0.112, 0.340, 0.124)
GREEN_TOP = (0.178, 0.452, 0.172)
TRUNK_COL = (0.28, 0.155, 0.075)
GOLD = (1.00, 0.76, 0.28)
SNOW_COL = (0.90, 0.94, 1.00)

ORNAMENT_COLS = [
    (0.90, 0.13, 0.16), (1.00, 0.74, 0.18), (0.16, 0.45, 0.90),
    (0.92, 0.92, 0.95), (0.62, 0.28, 0.85), (0.10, 0.72, 0.58),
]

# 礼物盒颜色（6 个）
BOX_COLS = [
    (0.78, 0.10, 0.13), (0.12, 0.34, 0.72), (0.10, 0.55, 0.32),
    (0.52, 0.20, 0.70), (0.85, 0.42, 0.08), (0.10, 0.55, 0.62),
]

# 礼物盒在树脚围成一圈的半径与角度
GIFT_RADIUS = 1.06
GIFT_ANGLES = [18, 72, 132, 196, 252, 314]
BOX_SIZE = 0.32

# 树干：底部一直到 1.02 都不长枝，礼物就摆在裸露的树干周围
TRUNK_BOTTOM_R = 0.190
TRUNK_TOP_R = 0.105
TRUNK_TOP = 1.06

# 各层松枝 (y0, height, radius, shade)
# 每层的枝条从 y0+h（靠主干、靠上）向外下方伸到 y0（枝尖、靠下），
# 所以整层是斜向下的裙摆，上下层交叠出锥形轮廓。
LAYERS = [
    (0.96, 0.64, 1.10, GREEN_BASE),
    (1.34, 0.60, 0.94, GREEN_BASE),
    (1.68, 0.56, 0.78, GREEN_MID),
    (1.99, 0.50, 0.63, GREEN_MID),
    (2.26, 0.44, 0.48, GREEN_TOP),
    (2.50, 0.38, 0.33, GREEN_TOP),
]
TREE_TOP = 2.90
# 顶星单独抬高：以前和树尖同高，星的下半截被树尖的针叶吞掉，
# 看着像陷进树里。抬到树尖之上，星才立在树顶上。
STAR_Y = 3.06

# 针叶尺寸
NEEDLE_HALF_W = 0.0076

# 树干的环状剖面高度：根部密、往上疏，根部不规则外扩才有"扎进土里"的重量感
TRUNK_RINGS = [-0.16, -0.12, -0.08, -0.05, -0.02, 0.0, 0.03, 0.06, 0.10, 0.14,
               0.19, 0.25, 0.32, 0.40, 0.49, 0.58, 0.68, 0.78, 0.88, 0.97, 1.06]


LIGHT_BOTTOM = TRUNK_TOP - 0.06


def foliage_radius(y):
    """树冠外轮廓在高度 y 处的半径。

    一条平滑的锥形包络：彩灯贴着它螺旋上升，彩球也挂在它附近。
    以前彩球按"层内百分比"摆，越往里越深，树一密就整个埋进针叶里看不见了。
    """
    t = (TREE_TOP - y) / (TREE_TOP - LIGHT_BOTTOM)
    return max(0.03, LAYERS[0][2] * max(0.0, t) ** 0.96)


def gift_positions():
    """6 个礼物盒的世界坐标（放在树脚）。"""
    out = []
    for a in GIFT_ANGLES:
        r = math.radians(a)
        out.append((math.cos(r) * GIFT_RADIUS, 0.0, math.sin(r) * GIFT_RADIUS))
    return out


def _set_mat(diffuse, specular=(0.25, 0.25, 0.25), shininess=40.0,
             emission=(0.0, 0.0, 0.0)):
    glMaterialfv(GL_FRONT_AND_BACK, GL_DIFFUSE, (*diffuse, 1.0))
    glMaterialfv(GL_FRONT_AND_BACK, GL_AMBIENT, (*[c * 0.50 for c in diffuse], 1.0))
    glMaterialfv(GL_FRONT_AND_BACK, GL_SPECULAR, (*specular, 1.0))
    glMaterialfv(GL_FRONT_AND_BACK, GL_EMISSION, (*emission, 1.0))
    glMaterialf(GL_FRONT_AND_BACK, GL_SHININESS, shininess)


def load_texture(path, alpha=False):
    data = np.fromfile(str(path), dtype=np.uint8)
    flag = cv2.IMREAD_UNCHANGED if alpha else cv2.IMREAD_COLOR
    img = cv2.imdecode(data, flag)
    if img is None:
        return 0
    if alpha:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
        fmt = GL_RGBA
    else:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        fmt = GL_RGB
    img = cv2.flip(img, 0)
    h, w = img.shape[:2]
    tex = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, tex)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
    gluBuild2DMipmaps(GL_TEXTURE_2D, fmt, w, h, fmt, GL_UNSIGNED_BYTE, img.tobytes())
    return tex


def make_glow_texture(size=64):
    """程序化生成的径向光晕贴图（中心白、边缘透明）。"""
    y, x = np.mgrid[-1:1:complex(size), -1:1:complex(size)]
    r2 = x * x + y * y
    a = np.clip(np.exp(-r2 * 3.2) - 0.02, 0.0, 1.0)
    rgba = np.zeros((size, size, 4), np.uint8)
    rgba[:, :, 0] = 255
    rgba[:, :, 1] = 255
    rgba[:, :, 2] = 255
    rgba[:, :, 3] = (a * 255).astype(np.uint8)
    tex = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, tex)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, size, size, 0,
                 GL_RGBA, GL_UNSIGNED_BYTE, rgba.tobytes())
    return tex


# ---------- 基础几何 ----------
def emit_cube(sx, sy, sz):
    """以原点为中心的长方体。"""
    x, y, z = sx * 0.5, sy * 0.5, sz * 0.5
    faces = [
        ((0, 0, 1), [(-x, -y, z), (x, -y, z), (x, y, z), (-x, y, z)]),
        ((0, 0, -1), [(-x, -y, -z), (-x, y, -z), (x, y, -z), (x, -y, -z)]),
        ((1, 0, 0), [(x, -y, -z), (x, y, -z), (x, y, z), (x, -y, z)]),
        ((-1, 0, 0), [(-x, -y, z), (-x, y, z), (-x, y, -z), (-x, -y, -z)]),
        ((0, 1, 0), [(-x, y, z), (x, y, z), (x, y, -z), (-x, y, -z)]),
        ((0, -1, 0), [(-x, -y, -z), (x, -y, -z), (x, -y, z), (-x, -y, z)]),
    ]
    glBegin(GL_QUADS)
    for n, vs in faces:
        glNormal3f(*n)
        for v in vs:
            glVertex3f(*v)
    glEnd()


def emit_branch(p0, p1, r0, r1, slices=7):
    """一根枝条：从 p0 到 p1 的细圆台。"""
    d = np.asarray(p1, dtype=np.float64) - np.asarray(p0, dtype=np.float64)
    L = float(np.linalg.norm(d))
    if L < 1e-6:
        return
    d = d / L
    up = np.array([0.0, 1.0, 0.0])
    if abs(d[1]) > 0.9999:
        axis = np.array([1.0, 0.0, 0.0])
        ang = 0.0 if d[1] > 0 else 180.0
    else:
        axis = np.cross(up, d)
        axis = axis / np.linalg.norm(axis)
        ang = math.degrees(math.acos(max(-1.0, min(1.0, float(d[1])))))
    glPushMatrix()
    glTranslatef(float(p0[0]), float(p0[1]), float(p0[2]))
    glRotatef(ang, float(axis[0]), float(axis[1]), float(axis[2]))
    emit_cylinder(r0, r1, L, slices, caps=False)
    glPopMatrix()


def layer_branches(rng, y0, h, r, shade, layer_i):
    """一层松枝的枝条列表 [(起点, 枝尖, 颜色), ...]。

    起点贴近主干且偏上，枝尖向外且偏下 —— 整层因此是一片斜向下的裙摆，
    上下层交叠出锥形轮廓。枝条和长在它上面的松针共用这份列表，
    两者才不会错位。

    每根主枝还会从中间分出两根侧枝，方向随机偏开。只有长射线的话，
    整棵树会像梳过的扫把，侧枝让轮廓碎起来、树冠才有厚度。
    """
    nb = max(20, int(round(r * 34)))
    out = []
    phase = layer_i * 0.83
    for i in range(nb):
        a = 2 * math.pi * i / nb + phase + rng.uniform(-0.07, 0.07)
        rr = r * rng.uniform(0.78, 1.06)
        ys = y0 + h * rng.uniform(0.84, 0.97)
        ye = y0 + h * rng.uniform(-0.04, 0.10) - rng.uniform(0.0, 0.03)
        ca, sa = math.cos(a), math.sin(a)
        p0 = np.array([ca * 0.085, ys, sa * 0.085], dtype=np.float64)
        p1 = np.array([ca * rr, ye, sa * rr], dtype=np.float64)
        out.append((p0, p1, shade))

        # 侧枝：从主枝中段分叉，向外侧再张开一点，长度随机
        n_twig = 3 if r > 0.85 else 2
        for k in range(n_twig):
            t = rng.uniform(0.30, 0.78)
            base = p0 + (p1 - p0) * t
            side = 0.34 if k % 2 else -0.34
            a2 = a + side + rng.uniform(-0.20, 0.20)
            ext = rr * rng.uniform(0.28, 0.50)
            tip = base + np.array([math.cos(a2) * ext,
                                   -rng.uniform(0.03, 0.13),
                                   math.sin(a2) * ext])
            out.append((base, tip, shade))
    return out


def _needle_patch(rng, p0, p1, shade):
    """一根枝条上的松针，返回 (N, 3, 9) 的「颜色+法线+顶点」三角片。

    每根针叶是一个细长三角，正反两份都生成，所以任何角度都看得到、
    也都有正确的受光；叶长和叶色都带随机扰动，避免整齐得像刷子。
    """
    d = p1 - p0
    L = float(np.linalg.norm(d))
    if L < 1e-6:
        return None
    d = d / L
    side0 = np.cross(d, np.array([0.0, 1.0, 0.0]))
    n0 = float(np.linalg.norm(side0))
    if n0 < 1e-6:
        side0 = np.array([1.0, 0.0, 0.0])
    else:
        side0 = side0 / n0
    upv = np.cross(side0, d)
    if upv[1] < 0:
        upv = -upv

    ns = max(12, int(L * 34))
    per = 9
    ts = np.linspace(0.03, 1.0, ns)
    base = p0[None, :] + ts[:, None] * (d * L)[None, :]        # (ns,3)

    phi = np.linspace(0.18, 2 * np.pi - 0.18, per) + rng.uniform(-0.22, 0.22, per)
    dirs = (np.cos(phi)[None, :, None] * side0[None, None, :]
            + np.sin(phi)[None, :, None] * upv[None, None, :]) * 0.95
    dirs = dirs + d[None, None, :] * 0.78
    dirs[:, :, 1] -= 0.21                                       # 松针下垂
    # 每根针再随机歪一点，否则一束针叶会像排好队的梳齿
    dirs += rng.normal(0.0, 0.07, dirs.shape)
    dirs /= np.linalg.norm(dirs, axis=2, keepdims=True) + 1e-9

    grow = 0.62 + 0.92 * ts                                     # 枝尖针叶更长
    ln = (0.082 * grow[:, None] * rng.uniform(0.76, 1.26, (ns, per)))[..., None]
    tips = base[:, None, :] + dirs * ln

    lat = np.cross(dirs, upv[None, None, :])
    lat /= np.linalg.norm(lat, axis=2, keepdims=True) + 1e-9
    hw = NEEDLE_HALF_W * rng.uniform(0.8, 1.25, (ns, per))[..., None]

    v0 = np.broadcast_to(base[:, None, :], tips.shape)
    v1 = tips + lat * hw
    v2 = tips - lat * hw
    tris = np.stack([v0, v1, v2], axis=2)                       # (ns,per,3,3)

    nf = np.cross(tris[:, :, 1] - tris[:, :, 0], tris[:, :, 2] - tris[:, :, 0])
    nf /= np.linalg.norm(nf, axis=2, keepdims=True) + 1e-9
    # 和「朝上」混一点，针叶整体受光更像一团有体积的松针
    nf = nf * 0.78 + np.array([0.0, 1.0, 0.0])[None, None, :] * 0.22
    nf /= np.linalg.norm(nf, axis=2, keepdims=True) + 1e-9

    # 假 AO：靠主干内侧压暗、树冠下方压暗，整棵树才有体积而不是一片平绿
    rr = np.hypot(base[:, 0], base[:, 2])
    # 用 0.7 次幂：靠主干处不至于一下子黑掉，树尖才不会糊成一团
    radial = np.clip(0.50 + 0.58 * np.power(np.clip(rr / 1.30, 0.0, 1.0), 0.7), 0.46, 1.12)
    hgt = 0.72 + 0.40 * np.clip(base[:, 1] / TREE_TOP, 0.0, 1.0)
    bright = ((0.66 + 0.46 * ts)[:, None] * rng.uniform(0.88, 1.12, (ns, per))
              * radial[:, None] * hgt[:, None])
    col = np.clip(np.asarray(shade, dtype=np.float64)[None, None, :] * bright[..., None],
                  0.0, 1.0)

    flat_v = tris.reshape(-1, 3)
    flat_n = np.repeat(nf.reshape(-1, 1, 3), 3, axis=1).reshape(-1, 3)
    flat_c = np.repeat(col.reshape(-1, 1, 3), 3, axis=1).reshape(-1, 3)
    front = np.concatenate([flat_c, flat_n, flat_v], axis=1)
    back = np.concatenate([flat_c, -flat_n,
                           tris.reshape(-1, 3, 3)[:, ::-1, :].reshape(-1, 3)], axis=1)
    return np.concatenate([front, back], axis=0)


def build_needles(branches, seed=11):
    """把全部枝条上的松针拼成一个交错的顶点数组（每顶点 颜色3+法线3+坐标3）。

    用顶点数组一次 glDrawArrays 画完一万多根针叶，比逐根 glBegin 快得多，
    也不会让显示列表编译卡住启动。
    """
    rng = np.random.default_rng(seed)
    chunks = []
    for (p0, p1, shade) in branches:
        patch = _needle_patch(rng, p0, p1, shade)
        if patch is not None:
            chunks.append(patch)
    # 树尖：沿轴线向上收拢的一小簇，让顶端收成一个尖，不盖住顶上那颗星
    for _ in range(64):
        a = rng.uniform(0.0, 2 * math.pi)
        r0 = rng.uniform(0.01, 0.055)
        r1 = rng.uniform(0.035, 0.10)
        y0 = rng.uniform(2.48, 2.68)
        p0 = np.array([math.cos(a) * r0, y0, math.sin(a) * r0])
        p1 = np.array([math.cos(a) * r1, y0 + rng.uniform(0.02, 0.045),
                       math.sin(a) * r1])
        patch = _needle_patch(rng, p0, p1, (0.240, 0.560, 0.220))
        if patch is not None:
            chunks.append(patch)
    # 树尖主梢：一小段细梢顶着星星，星就不会悬空
    for i in range(9):
        a = 2 * math.pi * i / 9 + 0.4
        r1 = 0.022
        p0 = np.array([math.cos(a) * 0.006, 2.62, math.sin(a) * 0.006])
        p1 = np.array([math.cos(a) * r1, 2.80 + 0.02 * (i % 3),
                       math.sin(a) * r1])
        patch = _needle_patch(rng, p0, p1, (0.250, 0.585, 0.230))
        if patch is not None:
            chunks.append(patch)
    if not chunks:
        return np.zeros((0, 9), dtype=np.float32)
    return np.ascontiguousarray(np.concatenate(chunks, axis=0), dtype=np.float32)


# ---------- 树干：不规则的树皮、根盘、断枝 ----------
def _trunk_center(y):
    """树干轴线微微弯曲，不是一根笔直的棒。"""
    return (0.024 * math.sin(y * 2.0 + 0.6),
            0.018 * math.sin(y * 1.35 + 2.2))


def _trunk_radius(y, a):
    """某高度、某角度上的树干半径。

    三层扰动叠起来：整体锥度（上细下粗）、角度上几个低频正弦（截面不是正圆）、
    以及只在根部很低范围生效的三道不对称根盘（buttress）。这样从上到下都是
    "这一侧胖一点、那一侧瘦一点"，不会出现一排整齐的圆箍。
    """
    if y < 0.0:
        # 地平面以下迅速收成一个尖。雪面是半透明的，树干若还保持原粗细，
        # 会透过雪面露出一截"插进地里的木桩"；收尖之后就只剩一点暗影。
        return _trunk_radius(0.0, a) * max(0.03, 1.0 + 3.2 * y)
    t = min(max(y / TRUNK_TOP, 0.0), 1.0)
    r = TRUNK_BOTTOM_R * (1.0 - t) + TRUNK_TOP_R * t
    r *= 1.0 + 0.070 * math.sin(t * 3.4 + 0.4)                  # 中段略鼓
    r *= 1.0 + (0.048 * math.sin(2 * a + 0.8)
                + 0.034 * math.sin(3 * a - 1.7)
                + 0.022 * math.sin(5 * a + 2.3)
                + 0.012 * math.sin(7 * a + 0.4))
    if y < 0.34:
        f = math.exp(-max(0.0, y) / 0.105)
        # 三道大小不一的根盘，各自往地面斜撑出去；cos^3 让它们收得很急，
        # 不会绕成一圈对称的裙边
        lobe = (0.62 * max(0.0, math.cos(a - 0.55)) ** 3
                + 0.45 * max(0.0, math.cos(a - 2.85)) ** 3
                + 0.34 * max(0.0, math.cos(a - 4.75)) ** 3)
        r += f * 0.200 * (lobe - 0.06)
    return r


def emit_trunk_mesh(rng, seg=64):
    """不规则树皮圆柱：逐环逐角算半径，逐面着色。

    面法线 + 逐面颜色斑驳，光打上去是一块一块的树皮，而不是一根打过蜡的圆筒。
    """
    ang = np.linspace(0.0, 2 * math.pi, seg, endpoint=False)
    band = 1.0 + rng.uniform(-0.006, 0.007, len(TRUNK_RINGS))
    verts = []
    for k, y in enumerate(TRUNK_RINGS):
        cx, cz = _trunk_center(y)
        ring = []
        for j in range(seg):
            a = ang[j]
            r = _trunk_radius(y, a) * band[k]
            ring.append((cx + math.cos(a) * r, y, cz + math.sin(a) * r))
        verts.append(ring)

    glBegin(GL_QUADS)
    for k in range(len(TRUNK_RINGS) - 1):
        yk = TRUNK_RINGS[k]
        # 越靠下的树皮越暗，像被阴影和积雪压住
        depth = 0.86 + 0.14 * min(1.0, max(0.0, yk) / 0.55)
        for j in range(seg):
            j2 = (j + 1) % seg
            a0 = ang[j]
            a1 = ang[j2] if j2 else 2 * math.pi
            am = (a0 + a1) * 0.5
            m = rng.uniform(0.86, 1.08) * depth
            glColor3f(0.215 * m, 0.124 * m, 0.068 * m)
            glNormal3f(math.cos(am), 0.16, math.sin(am))
            glVertex3f(*verts[k][j])
            glVertex3f(*verts[k][j2])
            glVertex3f(*verts[k + 1][j2])
            glVertex3f(*verts[k + 1][j])
    glEnd()


def emit_bark_ridges(rng, count=44):
    """纵向树皮沟与凸棱：宽窄、长短、弯曲方向全随机，绝不等距排一圈。

    细而浅，只是在树皮上划出深浅不一的竖纹；太粗会像贴上去的木条。
    """
    for i in range(count):
        a = rng.uniform(0.0, 2 * math.pi)
        y0 = rng.uniform(-0.03, 0.66)
        y1 = min(TRUNK_TOP * 0.99, y0 + rng.uniform(0.10, 0.50))
        drift = rng.uniform(-0.14, 0.14)
        pts = []
        for k in range(4):
            t = k / 3.0
            y = y0 + (y1 - y0) * t
            aa = a + drift * t * t
            cx, cz = _trunk_center(y)
            rad = _trunk_radius(y, aa) * 1.002
            pts.append(np.array([cx + math.cos(aa) * rad, y,
                                 cz + math.sin(aa) * rad]))
        w0 = rng.uniform(0.0035, 0.0085)
        if i % 3 == 0:
            glColor3f(0.235, 0.148, 0.082)          # 受光的凸棱
        else:
            glColor3f(0.098, 0.052, 0.026)          # 深沟
        for k in range(3):
            emit_branch(pts[k], pts[k + 1], w0 * (1.0 - 0.14 * k),
                        w0 * (1.0 - 0.14 * (k + 1)), 6)


def emit_trunk_stubs(rng):
    """断掉的老枝：短、细、朝下斜，断面是一块平疤。"""
    quad = gluNewQuadric()
    gluQuadricNormals(quad, GLU_SMOOTH)
    specs = [(1.18, 0.58, 0.135, 0.034), (3.55, 0.38, 0.105, 0.028),
             (5.02, 0.78, 0.150, 0.031)]
    for a0, y, L, rr in specs:
        a = a0 + rng.uniform(-0.12, 0.12)
        cx, cz = _trunk_center(y)
        r0 = _trunk_radius(y, a) * 0.92
        p0 = np.array([cx + math.cos(a) * r0, y, cz + math.sin(a) * r0])
        d = np.array([math.cos(a) * 0.82, rng.uniform(-0.52, -0.28),
                      math.sin(a) * 0.82])
        d /= np.linalg.norm(d)
        p1 = p0 + d * L
        m = rng.uniform(0.85, 1.05)
        glColor3f(0.218 * m, 0.126 * m, 0.062 * m)
        emit_branch(p0, p1, rr, rr * 0.92, 10)
        # 断面：深色平疤，用圆盘而不是球，才不会像一颗长在枝头的珠子
        glColor3f(0.132, 0.092, 0.050)
        up = np.array([0.0, 1.0, 0.0])
        axis = np.cross(up, d)
        nl = float(np.linalg.norm(axis))
        ang = 0.0
        if nl > 1e-6:
            axis = axis / nl
            ang = math.degrees(math.acos(max(-1.0, min(1.0, float(d[1])))))
        else:
            axis = np.array([1.0, 0.0, 0.0])
            ang = 0.0 if d[1] > 0 else 180.0
        glPushMatrix()
        glTranslatef(float(p1[0]), float(p1[1]), float(p1[2]))
        glRotatef(ang, float(axis[0]), float(axis[1]), float(axis[2]))
        glRotatef(-90, 1, 0, 0)
        gluDisk(quad, 0.0, rr * 0.88, 12, 1)
        glPopMatrix()

def emit_root_ridges(rng):
    """根部几条不对称的根脊，贴着雪面斜伸出去再没入雪里。

    截面是个三角形（脊背 + 两侧斜面），而不是圆管：圆管会像一条条触手，
    根脊才像树根从根盘上延伸出去。长度、方向、弯曲都不一样，转一圈看都不是环形。
    """
    specs = [(0.50, 0.48, 0.26), (2.55, 0.29, -0.20), (4.40, 0.40, 0.30)]
    for base_a, L, curve in specs:
        seg = 9
        top, left, right = [], [], []
        for k in range(seg + 1):
            t = k / seg
            a = base_a + curve * t
            r = 0.10 + (L - 0.10) * t
            cx, cz = math.cos(a) * r, math.sin(a) * r
            sh = 1.0 - t
            w = 0.090 * sh ** 0.72 + 0.006
            h = 0.068 * sh ** 0.95
            px, pz = -math.sin(a), math.cos(a)
            top.append(np.array([cx, h - 0.004, cz]))
            left.append(np.array([cx + px * w, -0.008, cz + pz * w]))
            right.append(np.array([cx - px * w, -0.008, cz - pz * w]))

        glBegin(GL_QUADS)
        for k in range(seg):
            m = rng.uniform(0.86, 1.07)
            for (lo, hi, dark) in ((left, top, 1.0), (top, right, 0.88)):
                v00, v01 = lo[k], lo[k + 1]
                v11, v10 = hi[k + 1], hi[k]
                n = np.cross(v01 - v00, v10 - v00)
                nl = float(np.linalg.norm(n))
                if nl > 1e-9:
                    n = n / nl
                if n[1] < 0:
                    n = -n
                glColor3f(0.205 * m * dark, 0.118 * m * dark, 0.062 * m * dark)
                glNormal3f(float(n[0]), float(n[1]), float(n[2]))
                glVertex3f(*v00)
                glVertex3f(*v01)
                glVertex3f(*v11)
                glVertex3f(*v10)
        glEnd()


def emit_snow_mound(seg=72, seed=41):
    """树脚一圈不规则的积雪，把树干和雪面的接缝埋掉。

    真实雪地里树根总是被雪堆住的，树干是"从雪里长出来"的；雪面直接切在
    树干上，会像一根木棍插进地板。内圈比树干细（藏在树干轮廓里面），
    外圈平摊到雪面，脊线高低不齐，才是一堆雪而不是一个甜甜圈。

    没有光照参与，明暗靠颜色按光照方向模拟：右前侧亮、左后侧暗。
    """
    rng = np.random.default_rng(seed)
    ph = rng.uniform(0.0, 2 * math.pi, 6)
    # 内圈必须略小于树干根部半径（0.29 左右），雪坡才能紧贴树根向外摊开；
    # 内圈太小的话整圈雪都埋在树干里面，外面只看得到一条窄边。
    rings = []
    # 第一圈必须比树根细（根盘最粗处 0.31 左右），否则雪坡和树干之间会裂开
    # 一道缝——树干是不规则的，固定半径的圆盘没法跟它贴合。
    for k, (rr, yy, amp) in enumerate(((0.180, 0.105, 0.012),
                                       (0.360, 0.080, 0.011),
                                       (0.440, 0.050, 0.009),
                                       (0.520, 0.022, 0.006),
                                       # 最外圈沉到雪面以下：地面写了深度，
                                       # 会把它裁掉，雪堆边缘就自然融进雪地
                                       (0.610, -0.016, 0.003))):
        ring = []
        for j in range(seg):
            a = 2 * math.pi * j / seg
            # 相位在各圈之间必须一致：否则上下两圈的起伏错开，
            # 坡面会被拧出一道道棱，像一块皱掉的布
            w = (1.0 + 0.115 * math.sin(a * 3.0 + ph[0])
                 + 0.060 * math.sin(a * 5.0 + ph[1] * 1.7)
                 + 0.032 * math.sin(a * 8.0 + ph[2] * 2.3))
            y = yy + amp * math.sin(a * 4.0 + ph[3])
            ring.append((math.cos(a) * rr * w, y, math.sin(a) * rr * w))
        rings.append(ring)

    glBegin(GL_QUADS)
    for k in range(len(rings) - 1):
        # 靠树干的一圈最高最亮，越往外的雪面越沉
        band = (1.00, 0.96, 0.93, 0.89, 0.83)[k]
        for j in range(seg):
            j2 = (j + 1) % seg
            a = 2 * math.pi * (j + 0.5) / seg
            dot = max(0.0, math.cos(a) * 0.60 + math.sin(a) * 0.80)
            shade = (0.46 + 0.28 * dot) * band
            glColor4f(SNOW_COL[0] * shade, SNOW_COL[1] * shade,
                      SNOW_COL[2] * shade, 1.0)
            glVertex3f(*rings[k][j])
            glVertex3f(*rings[k][j2])
            glVertex3f(*rings[k + 1][j2])
            glVertex3f(*rings[k + 1][j])
    glEnd()


def emit_foliage_shell(rng, y0, h, r, seg=54, rings=9):
    """每层松枝内部一圈暗绿的"内胆"。

    松针之间总有缝，缝后面如果是夜空，整棵树就显得稀、透、秃。这层暗色锥面
    把缝堵成深绿，树冠远看就是一团厚实的叶团，近看仍是根根分明的针叶。
    """
    ang = np.linspace(0.0, 2 * math.pi, seg, endpoint=False)
    jit = (1.0 + 0.09 * np.sin(ang * 3.0 + rng.uniform(0.0, 6.28))
           + 0.055 * np.sin(ang * 5.0 + rng.uniform(0.0, 6.28)))
    verts = []
    for k in range(rings + 1):
        t = k / rings
        y = y0 + h * (0.02 + 0.90 * t)
        rad = r * 0.66 * (1.0 - 0.52 * t)
        ring = []
        for j in range(seg):
            a = ang[j]
            rr = rad * jit[j] * (1.0 + 0.05 * math.sin(t * 5.0 + a * 2.0))
            ring.append((math.cos(a) * rr, y, math.sin(a) * rr))
        verts.append(ring)
    glBegin(GL_QUADS)
    for k in range(rings):
        for j in range(seg):
            j2 = (j + 1) % seg
            am = ang[j] + math.pi / seg
            m = rng.uniform(0.70, 1.16)
            glColor3f(0.028 * m, 0.088 * m, 0.043 * m)
            glNormal3f(math.cos(am), 0.22, math.sin(am))
            glVertex3f(*verts[k][j])
            glVertex3f(*verts[k][j2])
            glVertex3f(*verts[k + 1][j2])
            glVertex3f(*verts[k + 1][j])
    glEnd()


def emit_cylinder(r1, r2, h, slices=32, caps=True):
    """沿 +Y 的圆柱/圆台。"""
    glPushMatrix()
    glRotatef(-90, 1, 0, 0)          # GLU 圆柱沿 +Z，转成 +Y
    q = gluNewQuadric()
    if caps:
        gluQuadricNormals(q, GLU_SMOOTH)
    gluCylinder(q, r1, r2, h, slices, slices)
    glPopMatrix()


def emit_torus(R, r, seg=32, sides=12):
    glBegin(GL_QUAD_STRIP)
    for i in range(seg + 1):
        a = 2 * math.pi * i / seg
        ca, sa = math.cos(a), math.sin(a)
        for j in range(sides + 1):
            b = 2 * math.pi * j / sides
            cb, sb = math.cos(b), math.sin(b)
            x = (R + r * cb) * ca
            y = (R + r * cb) * sa
            z = r * sb
            nx, ny, nz = cb * ca, cb * sa, sb
            glNormal3f(nx, ny, nz)
            glVertex3f(x, y, z)
    glEnd()


def emit_torus_arc(R, r, a0, a1, seg=24, sides=10):
    glBegin(GL_QUAD_STRIP)
    for i in range(seg + 1):
        a = a0 + (a1 - a0) * i / seg
        ca, sa = math.cos(a), math.sin(a)
        for j in range(sides + 1):
            b = 2 * math.pi * j / sides
            cb, sb = math.cos(b), math.sin(b)
            glNormal3f(cb * ca, cb * sa, sb)
            glVertex3f((R + r * cb) * ca, (R + r * cb) * sa, r * sb)
    glEnd()


def emit_star_prism(r_out, r_in, thick, points=5):
    """五角星棱柱，立在 XY 平面、沿 Z 加厚。"""
    pts = []
    for i in range(points * 2):
        a = math.pi / 2 + i * math.pi / points
        rad = r_out if i % 2 == 0 else r_in
        pts.append((math.cos(a) * rad, math.sin(a) * rad))
    zf, zb = thick * 0.5, -thick * 0.5
    n = len(pts)
    for z, nz in ((zf, 1.0), (zb, -1.0)):
        glBegin(GL_TRIANGLE_FAN)
        glNormal3f(0, 0, nz)
        glVertex3f(0, 0, z)
        for (x, y) in pts:
            glVertex3f(x, y, z)
        glVertex3f(pts[0][0], pts[0][1], z)
        glEnd()
    glBegin(GL_QUADS)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        nx, ny = (y0 + y1), -(x0 + x1)
        nl = math.hypot(nx, ny) + 1e-9
        glNormal3f(nx / nl, ny / nl, 0)
        glVertex3f(x0, y0, zb)
        glVertex3f(x1, y1, zb)
        glVertex3f(x1, y1, zf)
        glVertex3f(x0, y0, zf)
    glEnd()


def emit_star_solid(r_out, r_in, depth, points=5, wave=0.04):
    """树顶星：带厚度的实体五角星（前后各一道尖脊）。

    为什么不做成原来那种薄棱柱：这颗星是插在树干尖上的，转树时会跟着转。
    薄片一转就侧对镜头，只剩一条竖线，看着像掉了一半；做成前后都有尖脊的
    实体，正面是五道高光棱的立体金星，转到侧面看到的是它本身的厚度——
    一颗有棱面的金饰，而不是一张纸。

    面法线逐面平直（flat shading）：转动时高光一个面一个面地跳过去，
    这比任何额外交互提示都更能让人看出"星是长在树上、跟着一起转的"。
    凹角在前后方向留一点点起伏，免得正反面太平、像塑料片。
    """
    n = points * 2
    pts = []
    for i in range(n):
        a = math.pi / 2 + i * math.pi / points
        rad = r_out if i % 2 == 0 else r_in
        sign = 1.0 if (i // 2) % 2 == 0 else -1.0
        z = 0.0 if i % 2 == 0 else wave * sign
        pts.append((math.cos(a) * rad, math.sin(a) * rad, z))

    glBegin(GL_TRIANGLES)
    for sign in (1.0, -1.0):
        apex = (0.0, 0.0, depth * sign)
        for i in range(n):
            p0 = pts[i]
            p1 = pts[(i + 1) % n]
            tri = (apex, p0, p1) if sign > 0 else (apex, p1, p0)
            e1 = tuple(tri[1][k] - tri[0][k] for k in range(3))
            e2 = tuple(tri[2][k] - tri[0][k] for k in range(3))
            nx = e1[1] * e2[2] - e1[2] * e2[1]
            ny = e1[2] * e2[0] - e1[0] * e2[2]
            nz = e1[0] * e2[1] - e1[1] * e2[0]
            nl = math.sqrt(nx * nx + ny * ny + nz * nz) + 1e-9
            glNormal3f(nx / nl, ny / nl, nz / nl)
            for v in tri:
                glVertex3f(*v)
    glEnd()


# ---------- 场景资源 ----------
class SceneAssets:
    def __init__(self, here=None):
        self.here = Path(here) if here else Path(__file__).resolve().parent
        self.tree_list = 0
        self.ornament_list = 0
        self.star_list = 0
        self.ground_list = 0
        self.box_body = 0
        self.box_ribbon = 0
        self.item_lists = []
        self.glow_tex = 0
        # 六个礼物盒里都是 2D 人物卡片：[(贴图, 宽高比, 画出来的高, 画出来的宽), ...]
        # 第 5 个（下标 4）沿用最早那张捧心人物，其余五个用用户新给的抠图角色
        self.characters = []
        self.char_aspect = 0.714
        self.light_pos = None
        self.gifts = gift_positions()
        self.branches = []
        self.needles = np.zeros((0, 9), dtype=np.float32)

    # ---- 构建 ----
    def build(self):
        self.branches = self._make_branches()
        self.needles = build_needles(self.branches)
        self._build_tree()
        self._build_ornaments()
        self._build_star()
        self._build_ground()
        self._build_snow_mound()
        self._build_box()
        self._build_items()
        self.glow_tex = make_glow_texture()
        self._load_characters()
        self._build_lights()

    # 礼物盒下标 → 人物素材。5 号盒（下标 4）还是原来那张捧心图，
    # 其余五张按用户给的 1~5 顺序填进 1/2/3/4/6 号盒。
    CHAR_FILES = {
        0: "gift_char_1.png",     # 手势
        1: "gift_char_2.png",     # 大笑（开盒时播 laugh_open.wav）
        2: "gift_char_3.png",     # 天使
        3: "gift_char_4.png",     # 跳跃
        4: "gift5_character.png",  # 捧心黄人（原有）
        5: "gift_char_5.png",     # 功夫
    }
    CHAR_H = 0.92        # 人物可见高度（世界单位），六个盒统一
    CHAR_MAX_W = 1.12    # 太宽的角色（天使张开翅膀）按宽度收一点，别顶出画面

    def _load_characters(self):
        """把六张人物卡读成贴图，并按"可见高度一致"算好各自的绘制尺寸。

        素材已经由 tools_import_chars.py 裁掉了透明边，所以这儿的 aspect
        就是人物本身的比例，直接用，不用再给每个人单独调尺寸。
        """
        self.characters = []
        for i in range(6):
            name = self.CHAR_FILES[i]
            p = self.here / "assets" / name
            tex = 0
            aspect = self.char_aspect
            if p.exists():
                data = np.fromfile(str(p), dtype=np.uint8)
                im = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
                if im is not None and im.shape[0] > 0:
                    aspect = im.shape[1] / im.shape[0]
                tex = load_texture(p, alpha=True)
            h = self.CHAR_H
            w = h * aspect
            if w > self.CHAR_MAX_W:
                w = self.CHAR_MAX_W
                h = w / aspect
            if i == 4:
                self.char_aspect = aspect
            self.characters.append({"tex": tex, "aspect": aspect, "w": w, "h": h})

    def _make_branches(self):
        """六层枝条，一次性算好，骨架和松针共用同一份。"""
        rng = np.random.default_rng(7)
        out = []
        for li, (y0, h, r, shade) in enumerate(LAYERS):
            out.extend(layer_branches(rng, y0, h, r, shade, li))
        return out

    def _build_tree(self):
        self.tree_list = glGenLists(1)
        glNewList(self.tree_list, GL_COMPILE)
        rng = np.random.default_rng(23)
        # 裸露的树干：礼物就围在它周围，所以这一段必须经得起近看。
        # 逐面用 glColor 着色（COLOR_MATERIAL），树皮才有斑驳的块面感。
        # 树皮完全无高光：有一点反光就会像打了蜡的塑料
        _set_mat(TRUNK_COL, specular=(0.0, 0.0, 0.0), shininess=2)
        glEnable(GL_COLOR_MATERIAL)
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)
        emit_trunk_mesh(rng)
        emit_root_ridges(rng)
        emit_bark_ridges(rng)
        emit_trunk_stubs(rng)
        # 每层松枝内部的暗绿内胆，堵住针叶之间的缝
        for (y0, h, r, _shade) in LAYERS:
            emit_foliage_shell(rng, y0, h, r)
        glDisable(GL_COLOR_MATERIAL)
        # 枝干骨架（针叶由顶层用顶点数组一次性画）
        for (p0, p1, shade) in self.branches:
            _set_mat([c * 0.52 for c in shade], specular=(0.04, 0.06, 0.04),
                     shininess=10)
            emit_branch(p0, p1, 0.011, 0.004, 6)
        glEndList()

    def _build_ornaments(self):
        self.ornament_list = glGenLists(1)
        glNewList(self.ornament_list, GL_COMPILE)
        quad = gluNewQuadric()
        gluQuadricNormals(quad, GLU_SMOOTH)
        rng = np.random.default_rng(5)
        ci = 0
        for (y0, h, r, _) in LAYERS:
            n = 0 if r < 0.45 else max(3, int(round(r * 6.5)))   # 树尖不挂球，免得挤成一堆
            for _ in range(n):
                # 挂在每层下摆的外沿：贴着树冠轮廓，才不会被新长的针叶埋掉
                y = y0 + h * rng.uniform(-0.04, 0.18)
                a = rng.uniform(0, 2 * np.pi)
                rad = foliage_radius(y) * rng.uniform(0.95, 1.06)
                x = math.cos(a) * rad
                z = math.sin(a) * rad
                col = ORNAMENT_COLS[ci % len(ORNAMENT_COLS)]
                ci += 1
                sz = rng.uniform(0.040, 0.064)
                _set_mat(col, specular=(0.9, 0.9, 0.9), shininess=80)
                glPushMatrix()
                glTranslatef(x, y, z)
                gluSphere(quad, sz, 16, 16)
                glPopMatrix()
        glEndList()

    def _build_star(self):
        self.star_list = glGenLists(1)
        glNewList(self.star_list, GL_COMPILE)
        _set_mat(GOLD, specular=(0.92, 0.86, 0.70), shininess=86,
                 emission=(0.34, 0.24, 0.05))
        # 三片星按 60° 交错：转到任何角度，总有一片差镜头不到 30°，
        # 侧影永远不会塌成一条竖线；三片对称摆，中间角度也是对称的
        emit_star_solid(0.30, 0.118, 0.165, 5, wave=0.040)
        glEndList()

    def _build_ground(self):
        # 只放几何与颜色，混合/光照状态由渲染器在绘制前后设置，
        # 避免显示列表把不该改的 GL 状态带到后续绘制。
        #
        # 中心几乎不透明、向外渐隐：以前中心只有 0.42，树干伸到雪面以下的
        # 那一截会透过雪面显出来，看着像树插在半透明的玻璃板上。
        self.ground_list = glGenLists(1)
        glNewList(self.ground_list, GL_COMPILE)
        seg = 72
        bands = [(0.00, 0.92, 1.00), (0.78, 0.90, 1.00), (1.35, 0.56, 0.96),
                 (2.15, 0.26, 0.92), (3.30, 0.00, 0.86)]
        base = (0.40, 0.44, 0.53)
        for k in range(len(bands) - 1):
            r0, a0, s0 = bands[k]
            r1, a1, s1 = bands[k + 1]
            glBegin(GL_QUAD_STRIP)
            for i in range(seg + 1):
                a = 2 * math.pi * i / seg
                ca, sa = math.cos(a), math.sin(a)
                glColor4f(base[0] * s0, base[1] * s0, base[2] * s0, a0)
                glVertex3f(ca * r0, -0.006, sa * r0)
                glColor4f(base[0] * s1, base[1] * s1, base[2] * s1, a1)
                glVertex3f(ca * r1, -0.006, sa * r1)
            glEnd()
        # 树脚的一团接触阴影：树才像"压在雪上"，而不是立在旁边
        glBegin(GL_TRIANGLE_FAN)
        glColor4f(0.0, 0.0, 0.01, 0.55)
        glVertex3f(0, -0.0055, 0)
        for i in range(seg + 1):
            a = 2 * math.pi * i / seg
            glColor4f(0.0, 0.0, 0.0, 0.0)
            glVertex3f(math.cos(a) * 0.62, -0.0055, math.sin(a) * 0.62)
        glEnd()
        glEndList()

    def _build_snow_mound(self):
        # 单独一个列表：它必须画在树干之后，才能把树根埋住
        self.snow_mound_list = glGenLists(1)
        glNewList(self.snow_mound_list, GL_COMPILE)
        emit_snow_mound()
        glEndList()

    def _build_box(self):
        """礼盒：盒身 + 外挑一圈的盖子 + 贴面缎带 + 立体蝴蝶结。

        以前是"一个立方体 + 两块穿透的十字扁块"，所以看着像木箱：没有盖子、
        没有厚度差，缎带还从盒子里穿出来。现在盒身略窄、盖子比盒身宽一圈
        且有明确厚度，缎带贴着每个面缠在外侧（外凸一个带子的厚度）。
        """
        bw = BOX_SIZE
        body_w = 0.955 * bw
        body_h = 0.760 * bw
        lid_w = 1.045 * bw
        lid_h = 0.235 * bw
        y_bot = -0.5 * bw
        y_body_top = y_bot + body_h
        y_lid = y_body_top - 0.004          # 盖沿略压下去一点，接口不留缝
        y_lid_top = y_lid + lid_h

        self.box_body = glGenLists(1)
        glNewList(self.box_body, GL_COMPILE)
        glPushMatrix()
        glTranslatef(0, y_bot + body_h * 0.5, 0)
        emit_cube(body_w, body_h, body_w)
        glPopMatrix()
        glEndList()

        self.box_lid = glGenLists(1)
        glNewList(self.box_lid, GL_COMPILE)
        glPushMatrix()
        glTranslatef(0, y_lid + lid_h * 0.5, 0)
        emit_cube(lid_w, lid_h, lid_w)
        glPopMatrix()
        glEndList()

        self.box_ribbon = glGenLists(1)
        glNewList(self.box_ribbon, GL_COMPILE)
        _set_mat(GOLD, specular=(1, 1, 1), shininess=70,
                 emission=(0.22, 0.15, 0.03))
        t = 0.165 * bw                      # 带子宽度
        e = 0.0075 * bw                     # 外凸厚度
        body_y = y_bot + body_h * 0.5
        for s in (-1.0, 1.0):
            # 盒身四侧的竖带：贴在面外侧，不从盒子里穿过去
            glPushMatrix()
            glTranslatef(s * (body_w * 0.5 + e * 0.5), body_y, 0)
            emit_cube(e, body_h, t)
            glPopMatrix()
            glPushMatrix()
            glTranslatef(0, body_y, s * (body_w * 0.5 + e * 0.5))
            emit_cube(t, body_h, e)
            glPopMatrix()
            # 盖子四侧的竖带（比盒身的宽，因为盖子本身外挑）
            glPushMatrix()
            glTranslatef(s * (lid_w * 0.5 + e * 0.5), y_lid + lid_h * 0.5, 0)
            emit_cube(e, lid_h, t)
            glPopMatrix()
            glPushMatrix()
            glTranslatef(0, y_lid + lid_h * 0.5, s * (lid_w * 0.5 + e * 0.5))
            emit_cube(t, lid_h, e)
            glPopMatrix()
        # 盖顶的十字
        glPushMatrix()
        glTranslatef(0, y_lid_top + e * 0.5, 0)
        emit_cube(lid_w * 1.004, e, t)
        emit_cube(t, e, lid_w * 1.004)
        glPopMatrix()

        self._emit_bow(bw, y_lid_top)
        glEndList()

    @staticmethod
    def _emit_bow(bw, y_base):
        """蝴蝶结：两片压扁的椭球当耳朵 + 中心结 + 两条飘带。

        不能用细圆环当耳朵——管径再粗，正面看也是两个"铁丝圈"；而且环的
        下半圈会埋进盖子，只剩两个拱门。椭球压扁后边缘圆润、受光鼓起的两片，
        才是蝴蝶结该有的样子；耳的底刚好落在盖顶上，不穿模。
        """
        quad = gluNewQuadric()
        gluQuadricNormals(quad, GLU_SMOOTH)
        for side in (-1.0, 1.0):
            glPushMatrix()
            glTranslatef(side * 0.158 * bw, y_base + 0.145 * bw, 0.0)
            glRotatef(side * 22.0, 0, 1, 0)      # 两耳向前后转开，侧面看有层次
            glRotatef(side * 24.0, 0, 0, 1)      # 外缘抬起、内端收在结上
            # 长轴远大于厚度：是"两片布"，不是两颗球。长轴取到中心距附近，
            # 两耳的根部才在结上交汇，而不是在中间鼓成一坨
            glScalef(0.176 * bw, 0.100 * bw, 0.030 * bw)
            gluSphere(quad, 1.0, 20, 14)
            glPopMatrix()

        # 中心结：颜色压深一档，否则和缎带、耳朵糊成一片金色的糊
        _set_mat([c * 0.80 for c in GOLD], specular=(0.9, 0.9, 0.9),
                 shininess=60, emission=(0.16, 0.10, 0.02))
        glPushMatrix()
        glTranslatef(0, y_base + 0.098 * bw, 0)
        glScalef(1.0, 0.90, 0.90)
        gluSphere(quad, 0.078 * bw, 18, 14)
        glPopMatrix()
        _set_mat(GOLD, specular=(1, 1, 1), shininess=70,
                 emission=(0.22, 0.15, 0.03))

        # 飘带：斜铺在盖子顶面上、从结向外撇开（再长就会插进盖子里）
        for side in (-1.0, 1.0):
            glPushMatrix()
            glTranslatef(side * 0.112 * bw, y_base + 0.040 * bw, 0.026 * bw)
            glRotatef(side * 52.0, 0, 0, 1)
            emit_cube(0.170 * bw, 0.058 * bw, 0.014 * bw)
            glPopMatrix()

    def _build_items(self):
        self.item_lists = []
        for i in range(6):
            lst = glGenLists(1)
            glNewList(lst, GL_COMPILE)
            if i == 0:
                self._item_star()
            elif i == 1:
                self._item_snowflake()
            elif i == 2:
                self._item_bell()
            elif i == 3:
                self._item_candy()
            elif i == 4:
                pass  # 捧心人物是贴图，单独绘制
            else:
                self._item_stocking()
            glEndList()
            self.item_lists.append(lst)

    def _item_star(self):
        _set_mat(GOLD, specular=(1, 1, 1), shininess=110,
                 emission=(0.6, 0.45, 0.10))
        emit_star_prism(0.30, 0.12, 0.12, 5)

    def _item_snowflake(self):
        _set_mat((0.60, 0.86, 1.0), specular=(1, 1, 1), shininess=110,
                 emission=(0.12, 0.22, 0.30))
        quad = gluNewQuadric()
        gluQuadricNormals(quad, GLU_SMOOTH)
        # 中心六棱
        glPushMatrix()
        glScalef(1, 1, 0.25)
        gluSphere(quad, 0.07, 18, 18)
        glPopMatrix()
        for i in range(6):
            glPushMatrix()
            glRotatef(i * 60, 0, 0, 1)
            glTranslatef(0.24, 0, 0)
            emit_cube(0.42, 0.045, 0.045)
            # 小分叉
            glPushMatrix()
            glTranslatef(0.14, 0.07, 0)
            glRotatef(35, 0, 0, 1)
            emit_cube(0.14, 0.03, 0.03)
            glPopMatrix()
            glPushMatrix()
            glTranslatef(0.14, -0.07, 0)
            glRotatef(-35, 0, 0, 1)
            emit_cube(0.14, 0.03, 0.03)
            glPopMatrix()
            glPopMatrix()
        # 六个尖点小球
        for i in range(6):
            a = math.radians(i * 60)
            glPushMatrix()
            glTranslatef(math.cos(a) * 0.45, math.sin(a) * 0.45, 0)
            gluSphere(quad, 0.028, 10, 10)
            glPopMatrix()

    def _item_bell(self):
        _set_mat(GOLD, specular=(1, 1, 1), shininess=120,
                 emission=(0.35, 0.24, 0.05))
        quad = gluNewQuadric()
        gluQuadricNormals(quad, GLU_SMOOTH)
        # 钟体：下宽上窄（r1 是底部半径，r2 是顶部半径）
        glPushMatrix()
        glTranslatef(0, -0.26, 0)
        emit_cylinder(0.30, 0.10, 0.36, 40, caps=True)
        glPopMatrix()
        # 底沿
        glPushMatrix()
        glTranslatef(0, -0.27, 0)
        glScalef(1, 0.35, 1)
        gluSphere(quad, 0.31, 32, 16)
        glPopMatrix()
        # 顶部提环
        glPushMatrix()
        glTranslatef(0, 0.13, 0)
        glRotatef(90, 1, 0, 0)
        emit_torus(0.055, 0.016, 18, 8)
        glPopMatrix()
        # 铃舌从底部露出来
        _set_mat((0.75, 0.58, 0.20), specular=(1, 1, 1), shininess=80)
        glPushMatrix()
        glTranslatef(0, -0.36, 0)
        gluSphere(quad, 0.065, 16, 16)
        glPopMatrix()

    def _item_candy(self):
        quad = gluNewQuadric()
        gluQuadricNormals(quad, GLU_SMOOTH)
        # 竖直条纹圆柱
        seg = 26
        for i in range(seg):
            y0 = -0.42 + i * (0.72 / seg)
            col = (0.86, 0.10, 0.14) if i % 2 == 0 else (0.97, 0.96, 0.94)
            _set_mat(col, specular=(0.9, 0.9, 0.9), shininess=60)
            glPushMatrix()
            glTranslatef(0, y0, 0)
            emit_cylinder(0.055, 0.055, 0.72 / seg + 0.001, 16, caps=False)
            glPopMatrix()
        # 顶部弯钩（半圈圆弧管）
        nseg = 16
        for i in range(nseg):
            a0 = math.pi * i / nseg
            a1 = math.pi * (i + 1) / nseg + 0.002
            col = (0.86, 0.10, 0.14) if i % 2 == 0 else (0.97, 0.96, 0.94)
            _set_mat(col, specular=(0.9, 0.9, 0.9), shininess=60)
            glPushMatrix()
            glTranslatef(0.10, 0.30, 0)
            emit_torus_arc(0.11, 0.05, a0, a1, 3, 10)
            glPopMatrix()

    def _item_stocking(self):
        quad = gluNewQuadric()
        gluQuadricNormals(quad, GLU_SMOOTH)
        _set_mat((0.80, 0.10, 0.13), specular=(0.7, 0.7, 0.7), shininess=40)
        # 袜筒（从 -0.10 到 0.34）
        glPushMatrix()
        glTranslatef(0, -0.10, 0)
        glScalef(1, 1, 0.62)
        emit_cylinder(0.15, 0.14, 0.44, 28, caps=True)
        glPopMatrix()
        # 袜脚：和筒底接上
        glPushMatrix()
        glTranslatef(0.10, -0.14, 0)
        glScalef(1.15, 0.85, 0.62)
        gluSphere(quad, 0.20, 24, 18)
        glPopMatrix()
        # 白色袜口
        _set_mat((0.96, 0.96, 0.97), specular=(0.6, 0.6, 0.6), shininess=40)
        glPushMatrix()
        glTranslatef(0, 0.34, 0)
        glScalef(1, 1, 0.64)
        emit_cylinder(0.175, 0.175, 0.12, 28, caps=True)
        glPopMatrix()
        # 挂环
        glPushMatrix()
        glTranslatef(-0.13, 0.45, 0)
        glRotatef(90, 0, 1, 0)
        emit_torus(0.05, 0.013, 14, 8)
        glPopMatrix()

    def _build_lights(self):
        """螺旋灯带：贴着树冠外轮廓盘旋而上，裸露的树干上不挂灯。"""
        n = 300
        t = np.linspace(0, 1, n)
        y = LIGHT_BOTTOM + t * (TREE_TOP - LIGHT_BOTTOM - 0.04)
        # 平滑锥形包络，而不是逐层取最大值——后者会在每层交叠处跳变，
        # 看起来像一圈圈独立的灯环，而不是一条盘旋而上的灯带。
        radius = np.array([foliage_radius(v) for v in y]) * 1.04
        ang = t * 2 * np.pi * 8.5
        x = np.cos(ang) * radius
        z = np.sin(ang) * radius
        self.light_pos = np.stack([x, y, z], axis=1)

    # ---- 绘制辅助 ----
    def draw_character(self, gift_index, angle_deg):
        """2D 贴图卡片绕 Y 轴自转；关闭背面剔除后，背面自动就是镜像。"""
        card = self.characters[gift_index] if self.characters else None
        if not card or not card["tex"]:
            return
        w, h = card["w"], card["h"]
        glPushMatrix()
        glRotatef(angle_deg, 0, 1, 0)
        glDisable(GL_CULL_FACE)
        glDisable(GL_LIGHTING)
        glEnable(GL_TEXTURE_2D)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glDepthMask(GL_FALSE)
        glBindTexture(GL_TEXTURE_2D, card["tex"])
        glColor4f(1, 1, 1, 1)
        glBegin(GL_QUADS)
        glTexCoord2f(0, 0); glVertex3f(-w * 0.5, -h * 0.5, 0)
        glTexCoord2f(1, 0); glVertex3f(w * 0.5, -h * 0.5, 0)
        glTexCoord2f(1, 1); glVertex3f(w * 0.5, h * 0.5, 0)
        glTexCoord2f(0, 1); glVertex3f(-w * 0.5, h * 0.5, 0)
        glEnd()
        glDepthMask(GL_TRUE)
        glDisable(GL_BLEND)
        glDisable(GL_TEXTURE_2D)
        glEnable(GL_LIGHTING)
        glEnable(GL_CULL_FACE)
        glPopMatrix()
