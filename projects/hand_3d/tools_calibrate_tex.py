# -*- coding: utf-8 -*-
"""标定 gluSphere 的贴图坐标约定。

做法：用一张“自编码贴图”——R 通道存列号、G 通道存行号——
      渲染球体后读取正中央像素，就能精确知道
      某个三维方向对应贴图的哪个 s/t。
不需要推理，也不需要肉眼判断颜色像什么大陆。

    py -3.12 projects/hand_3d/tools_calibrate_tex.py
"""
import math
import sys
from pathlib import Path

import numpy as np
from PyQt6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat
from PyQt6.QtWidgets import QApplication
from OpenGL.GL import *
from OpenGL.GLU import *

HERE = Path(__file__).resolve().parent
W, H, SIZE = 640, 480, 720


def make_debug_texture():
    """R = 列进度, G = 行进度（0 在图像顶部）。"""
    cols, rows = SIZE, SIZE // 2
    col = np.linspace(0, 255, cols, dtype=np.uint8)[None, :]
    row = np.linspace(0, 255, rows, dtype=np.uint8)[:, None]
    img = np.zeros((rows, cols, 3), dtype=np.uint8)
    img[:, :, 0] = col
    img[:, :, 1] = row
    return img


def upload(img):
    # 与项目 load_texture 一致：垂直翻转后上传
    img = np.flip(img, 0).copy()
    h, w = img.shape[:2]
    tex = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, tex)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, w, h, 0, GL_RGB, GL_UNSIGNED_BYTE, img.tobytes())
    return tex


def main():
    fmt = QSurfaceFormat()
    fmt.setDepthBufferSize(24)
    fmt.setVersion(2, 1)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.NoProfile)
    QSurfaceFormat.setDefaultFormat(fmt)
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

    tex = upload(make_debug_texture())
    quad = gluNewQuadric()
    gluQuadricTexture(quad, GL_TRUE)

    glViewport(0, 0, W, H)
    glMatrixMode(GL_PROJECTION)
    glLoadIdentity()
    gluPerspective(45, W / H, 0.1, 100.0)
    glDisable(GL_LIGHTING)
    glDisable(GL_CULL_FACE)
    glEnable(GL_DEPTH_TEST)
    glEnable(GL_TEXTURE_2D)
    glBindTexture(GL_TEXTURE_2D, tex)
    glColor3f(1, 1, 1)

    print("rot  -> 正对屏幕的方向            -> 贴图 s / 原始行进度")
    probes = [(0, 0), (0, 90), (0, 180), (0, 270), (45, 0), (-45, 0), (90, 0)]
    for rx, ry in probes:
        glClearColor(0, 0, 0, 1)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        gluLookAt(0, 0, 3.2, 0, 0, 0, 0, 1, 0)
        glPushMatrix()
        glRotatef(rx, 1, 0, 0)
        glRotatef(ry, 0, 1, 0)
        gluSphere(quad, 1.0, 96, 96)
        glPopMatrix()

        glPixelStorei(GL_PACK_ALIGNMENT, 1)
        px = glReadPixels(W // 2, H // 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE)
        r, g = px[0], px[1]
        s = r / 255.0
        t_data = g / 255.0              # 翻转后数据的行进度
        row_frac = 1.0 - t_data         # 还原成原始图像自顶向下的行进度

        # 反算模型矩阵下正对屏幕的方向：v = Rx(-rx) * Ry(-ry) * (0,0,1)
        ax, ay = math.radians(-rx), math.radians(-ry)
        v = np.array([math.sin(ay) * math.cos(ax), math.sin(ax), math.cos(ay) * math.cos(ax)])

        # 由 s,t 反推球面角度
        theta = s * 2 * math.pi
        phi = (1.0 - t_data) * math.pi
        print(f"({rx:4.0f},{ry:4.0f})  方向({v[0]:+.3f},{v[1]:+.3f},{v[2]:+.3f})  "
              f"s={s:.4f} 原始行={row_frac:.4f}  => theta={math.degrees(theta):6.1f}° "
              f"phi={math.degrees(phi):5.1f}°")

        # 校验：按 (theta,phi) 的正/负号组合还原方向，看哪一组等于 v
        sphi = math.sin(phi)
        cands = {
            "(cos,cos,+sin)": (math.cos(theta) * sphi, math.cos(phi), math.sin(theta) * sphi),
            "(cos,cos,-sin)": (math.cos(theta) * sphi, math.cos(phi), -math.sin(theta) * sphi),
            "(-cos,cos,+sin)": (-math.cos(theta) * sphi, math.cos(phi), math.sin(theta) * sphi),
            "(-cos,cos,-sin)": (-math.cos(theta) * sphi, math.cos(phi), -math.sin(theta) * sphi),
            "(cos,-cos,+sin)": (math.cos(theta) * sphi, -math.cos(phi), math.sin(theta) * sphi),
            "(cos,-cos,-sin)": (math.cos(theta) * sphi, -math.cos(phi), -math.sin(theta) * sphi),
        }
        best = min(cands.items(), key=lambda kv: sum((kv[1][i] - v[i]) ** 2 for i in range(3)))
        err = math.sqrt(sum((best[1][i] - v[i]) ** 2 for i in range(3)))
        print(f"          最接近的约定: {best[0]}  误差 {err:.4f}")

    glBindFramebuffer(GL_FRAMEBUFFER, 0)
    ctx.doneCurrent()


if __name__ == "__main__":
    main()
