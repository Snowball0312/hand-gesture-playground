# -*- coding: utf-8 -*-
"""逐像素验证球面贴图映射是否正确。

思路：渲染一帧地球（无光照，纯贴图颜色），对球面上的每个像素：
  屏幕像素 → 视线与球求交 → 世界坐标 → 反旋转得到球面方向
  → geo.dir_to_latlon → 贴图行列 → 从 day4k.jpg 取样
把“按映射算出来的颜色”和“实际渲染出来的颜色”逐像素比对。
两者一致（误差小）就说明经纬度换算与贴图朝向完全正确。

    py -3.12 projects/hand_3d/tools_verify_mapping.py
"""
import math
import sys
from pathlib import Path

import numpy as np
import cv2
from PyQt6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat
from PyQt6.QtWidgets import QApplication
from OpenGL.GL import *
from OpenGL.GLU import *

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import geo  # noqa: E402

W, H, DIST, FOV = 640, 480, 3.2, 45.0


def render(rot_x, rot_y):
    fmt = QSurfaceFormat()
    fmt.setDepthBufferSize(24)
    fmt.setVersion(2, 1)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.NoProfile)
    QSurfaceFormat.setDefaultFormat(fmt)
    # QApplication 必须保持引用，否则被 GC 回收后一创建表面就段错误
    app = QApplication.instance() or QApplication(sys.argv)
    surface = QOffscreenSurface()
    surface.setFormat(fmt)
    surface.create()
    ctx = QOpenGLContext()
    ctx.setFormat(fmt)
    if not ctx.create() or not ctx.makeCurrent(surface):
        raise SystemExit("OpenGL 上下文不可用")

    fbo = glGenFramebuffers(1)
    glBindFramebuffer(GL_FRAMEBUFFER, fbo)
    rb = glGenRenderbuffers(1)
    glBindRenderbuffer(GL_RENDERBUFFER, rb)
    glRenderbufferStorage(GL_RENDERBUFFER, GL_RGBA8, W, H)
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, rb)
    db = glGenRenderbuffers(1)
    glBindRenderbuffer(GL_RENDERBUFFER, db)
    glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, W, H)
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, db)

    tex_path = ROOT / "textures" / "day4k.jpg"
    raw = np.fromfile(str(tex_path), dtype=np.uint8)
    img = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    tex_h, tex_w = img.shape[:2]
    flipped = np.flip(img, 0).copy()

    tex = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, tex)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, tex_w, tex_h, 0, GL_RGB,
                 GL_UNSIGNED_BYTE, flipped.tobytes())

    quad = gluNewQuadric()
    gluQuadricTexture(quad, GL_TRUE)

    glViewport(0, 0, W, H)
    glClearColor(0, 0, 0, 1)
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    glDisable(GL_LIGHTING)
    glDisable(GL_CULL_FACE)
    glEnable(GL_DEPTH_TEST)
    glMatrixMode(GL_PROJECTION)
    glLoadIdentity()
    gluPerspective(FOV, W / H, 0.1, 100.0)
    glMatrixMode(GL_MODELVIEW)
    glLoadIdentity()
    gluLookAt(0, 0, DIST, 0, 0, 0, 0, 1, 0)
    glPushMatrix()
    glRotatef(rot_x, 1, 0, 0)
    glRotatef(rot_y, 0, 1, 0)
    glEnable(GL_TEXTURE_2D)
    glColor3f(1, 1, 1)
    gluSphere(quad, 1.0, 96, 96)
    glPopMatrix()

    glPixelStorei(GL_PACK_ALIGNMENT, 1)
    px = glReadPixels(0, 0, W, H, GL_RGBA, GL_UNSIGNED_BYTE)
    out = np.frombuffer(px, dtype=np.uint8).reshape(H, W, 4)[:, :, :3]
    out = np.flip(out, 0).copy()        # 变成自上而下
    glBindFramebuffer(GL_FRAMEBUFFER, 0)
    ctx.doneCurrent()
    return out, img


def main():
    rot_x, rot_y = geo.view_rot_to_face(geo.latlon_to_dir(geo.CHINA_LAT, geo.CHINA_LON))
    print(f"以中国为中心渲染, rot=({rot_x:.2f}, {rot_y:.2f})")
    shot, tex = render(rot_x, rot_y)
    tex_h, tex_w = tex.shape[:2]

    rx, ry = math.radians(rot_x), math.radians(rot_y)
    tan = math.tan(math.radians(FOV) / 2)
    aspect = W / H

    errs = []
    checked = 0
    for py in range(0, H, 4):
        for pxx in range(0, W, 4):
            ndc_x = (pxx + 0.5) / W * 2 - 1
            ndc_y = 1 - (py + 0.5) / H * 2
            d = np.array([ndc_x * tan * aspect, ndc_y * tan, -1.0])
            d /= np.linalg.norm(d)
            o = np.array([0.0, 0.0, DIST])
            b = 2 * o.dot(d)
            c = o.dot(o) - 1.0
            disc = b * b - 4 * c
            if disc <= 0:
                continue
            t = (-b - math.sqrt(disc)) / 2
            wpt = o + t * d

            # 反旋转：p = Ry(-ry) · Rx(-rx) · w
            x, y, z = wpt
            cx, sx = math.cos(-rx), math.sin(-rx)
            y, z = cx * y - sx * z, sx * y + cx * z
            cy, sy = math.cos(-ry), math.sin(-ry)
            x, z = cy * x + sy * z, -sy * x + cy * z
            p = np.array([x, y, z])
            p /= np.linalg.norm(p)

            lat, lon = geo.dir_to_latlon(p)
            s = (lon + 180.0) / 360.0
            row = (90.0 - lat) / 180.0
            col_px = int(min(tex_w - 1, max(0, s * tex_w)))
            row_px = int(min(tex_h - 1, max(0, row * tex_h)))

            expect = tex[row_px, col_px].astype(int)
            actual = shot[py, pxx].astype(int)
            errs.append(np.abs(expect - actual).mean())
            checked += 1

    e = np.array(errs)
    print(f"抽样 {checked} 个球面像素")
    print(f"平均色差 {e.mean():.2f}/255   中位数 {np.median(e):.2f}   90分位 {np.percentile(e,90):.2f}")
    frac = (e < 12).mean()
    print(f"色差 <12 的比例: {frac*100:.1f}%")
    verdict = "PASS 映射正确" if e.mean() < 10 else "FAIL 映射仍然不对"
    print("结论:", verdict)


if __name__ == "__main__":
    main()
