# -*- coding: utf-8 -*-
"""离屏渲染地球，用来校准经纬度与视角，不需要摄像头也不需要真实窗口。

    py -3.12 projects/hand_3d/tools_preview_globe.py --out a.png
    py -3.12 projects/hand_3d/tools_preview_globe.py --rotx 18 --roty -105 --lat 39.9 --lon 116.4 --out b.png

渲染完成后会打印“屏幕正中央对应哪个经纬度”和“针钉在哪个经纬度”，
再配合同目录生成的 PNG 就能判断针是否落在中国的陆地上。
"""
import argparse
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


def load_texture(path):
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img = cv2.flip(img, 0)
    h, w = img.shape[:2]
    tex = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, tex)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
    gluBuild2DMipmaps(GL_TEXTURE_2D, GL_RGB, w, h, GL_RGB, GL_UNSIGNED_BYTE, img.tobytes())
    return tex


def draw(rot_x, rot_y, dist, tex_path, pin_latlon=None, light=True, marks=(), mat=None):
    tex = load_texture(tex_path)
    quad = gluNewQuadric()
    gluQuadricTexture(quad, GL_TRUE)
    gluQuadricNormals(quad, GLU_SMOOTH)

    glMatrixMode(GL_MODELVIEW)
    glLoadIdentity()
    gluLookAt(0, 0, dist, 0, 0, 0, 0, 1, 0)

    # 光照必须在单位矩阵下设置（与主程序 initializeGL 一致），
    # 否则光源会跟着地球一起转，转到背面就全黑了
    if light:
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glLightfv(GL_LIGHT0, GL_POSITION, [5.0, 2.0, 3.0, 1.0])
        glLightfv(GL_LIGHT0, GL_DIFFUSE, [1.05, 1.00, 0.92, 1.0])
        glLightModelfv(GL_LIGHT_MODEL_AMBIENT, [0.30, 0.30, 0.34, 1.0])

    glPushMatrix()
    if mat is None:
        glRotatef(rot_x, 1, 0, 0)
        glRotatef(rot_y, 0, 1, 0)
    else:
        m4 = np.eye(4, dtype=np.float32)
        m4[:3, :3] = mat
        glMultMatrixf(m4.T.flatten())

    glEnable(GL_TEXTURE_2D)
    glColor3f(1, 1, 1)
    gluSphere(quad, 1.0, 72, 72)

    if pin_latlon is not None:
        d = geo.latlon_to_dir(*pin_latlon)
        angle, ax, ay, az = geo.rotation_to_align(d)
        glDisable(GL_LIGHTING)
        glDisable(GL_TEXTURE_2D)
        glPushMatrix()
        glTranslatef(d[0], d[1], d[2])
        glRotatef(angle, ax, ay, az)
        glColor3f(1.0, 0.15, 0.15)
        gluSphere(quad, 0.028, 20, 20)
        glTranslatef(0.0, 0.0, 0.02)
        glColor3f(1.0, 0.45, 0.35)
        gluCylinder(quad, 0.011, 0.002, 0.18, 12, 12)
        glPopMatrix()

    # 校验用标点：按顺序给不同颜色的小球，用来肉眼确认经纬度换算是否正确
    palette = [(1, 0, 0), (0, 1, 0), (0, 0.6, 1), (1, 1, 0), (1, 0, 1), (0, 1, 1)]
    if marks:
        glDisable(GL_LIGHTING)
        glDisable(GL_TEXTURE_2D)
        for i, (mlat, mlon) in enumerate(marks):
            d = geo.latlon_to_dir(mlat, mlon)
            r, g, b = palette[i % len(palette)]
            glColor3f(r, g, b)
            glPushMatrix()
            glTranslatef(d[0] * 1.005, d[1] * 1.005, d[2] * 1.005)
            gluSphere(quad, 0.022, 16, 16)
            glPopMatrix()

    glPopMatrix()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "preview.png"))
    ap.add_argument("--rotx", type=float, default=18.0)
    ap.add_argument("--roty", type=float, default=-105.0)
    ap.add_argument("--dist", type=float, default=3.2)
    ap.add_argument("--w", type=int, default=900)
    ap.add_argument("--h", type=int, default=700)
    ap.add_argument("--lat", type=float, default=None)
    ap.add_argument("--lon", type=float, default=None)
    ap.add_argument("--tex", default=str(ROOT / "textures" / "day4k.jpg"))
    ap.add_argument("--no-light", action="store_true")
    ap.add_argument("--no-pin", action="store_true")
    ap.add_argument("--face-lat", type=float, default=None,
                    help="让该纬度正对屏幕（与 --face-lon 一起由 geo 算出 rot_x/rot_y）")
    ap.add_argument("--face-lon", type=float, default=None)
    ap.add_argument("--mark", action="append", default=[],
                    help="校验标点 LAT,LON，可重复；颜色顺序 红/绿/蓝/黄/品红/青")
    ap.add_argument("--from-main", action="store_true",
                    help="直接使用 main.initial_rotation() 的真实初始姿态渲染")
    args = ap.parse_args()

    mat = None
    if args.from_main:
        import main as app_main
        mat = app_main.initial_rotation()
        print("使用 main.initial_rotation() 的真实姿态")

    if args.face_lat is not None and args.face_lon is not None:
        d = geo.latlon_to_dir(args.face_lat, args.face_lon)
        args.rotx, args.roty = geo.view_rot_to_face(d)
        print(f"按正对 ({args.face_lat}, {args.face_lon}) 算出 rot_x={args.rotx:.2f} rot_y={args.roty:.2f}")

    fmt = QSurfaceFormat()
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    fmt.setVersion(2, 1)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.NoProfile)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication.instance() or QApplication(sys.argv)
    surface = QOffscreenSurface()
    surface.setFormat(fmt)
    surface.create()
    if not surface.isValid():
        raise SystemExit("离屏表面创建失败")

    ctx = QOpenGLContext()
    ctx.setFormat(fmt)
    if not ctx.create():
        raise SystemExit("OpenGL 上下文创建失败")
    if not ctx.makeCurrent(surface):
        raise SystemExit("makeCurrent 失败")

    w, h = args.w, args.h
    fbo = glGenFramebuffers(1)
    glBindFramebuffer(GL_FRAMEBUFFER, fbo)
    rb = glGenRenderbuffers(1)
    glBindRenderbuffer(GL_RENDERBUFFER, rb)
    glRenderbufferStorage(GL_RENDERBUFFER, GL_RGBA8, w, h)
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, rb)
    db = glGenRenderbuffers(1)
    glBindRenderbuffer(GL_RENDERBUFFER, db)
    glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, w, h)
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, db)
    if glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE:
        raise SystemExit("FBO 不完整，无法离屏渲染")

    glViewport(0, 0, w, h)
    glClearColor(0.01, 0.012, 0.03, 1.0)
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    glEnable(GL_DEPTH_TEST)
    glMatrixMode(GL_PROJECTION)
    glLoadIdentity()
    gluPerspective(45, w / max(1, h), 0.1, 100.0)

    pin = None if args.no_pin else (args.lat, args.lon)
    if pin is not None and (pin[0] is None or pin[1] is None):
        pin = (geo.PIN_LAT, geo.PIN_LON)
    marks = []
    for spec in args.mark:
        a, b = spec.split(",")
        marks.append((float(a), float(b)))
    draw(args.rotx, args.roty, args.dist, Path(args.tex), pin,
         not args.no_light, marks, mat)

    glPixelStorei(GL_PACK_ALIGNMENT, 1)
    raw = glReadPixels(0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE)
    img = np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 4)
    img = cv2.flip(img, 0)
    # cv2.imwrite 不支持中文路径，统一走 imencode + tofile
    ok, buf = cv2.imencode(".png", cv2.cvtColor(img, cv2.COLOR_RGBA2BGR))
    if not ok:
        raise SystemExit("PNG 编码失败")
    Path(args.out).write_bytes(buf.tobytes())

    rx, ry = math.radians(args.rotx), math.radians(args.roty)
    if mat is None:
        facing = (-math.sin(ry) * math.cos(rx), math.sin(rx), math.cos(ry) * math.cos(rx))
        flat, flon = geo.dir_to_latlon(facing)
        print(f"画布中央经纬度: {flat:6.1f}° {flon:7.1f}°")
    else:
        print(f"画布中央经纬度: 约 ({geo.CHINA_LAT}, {geo.CHINA_LON})，北朝上")
    if pin:
        print(f"针的位置      : {pin[0]:6.1f}° {pin[1]:7.1f}°")
    print(f"已保存 {args.out}")

    glBindFramebuffer(GL_FRAMEBUFFER, 0)
    ctx.doneCurrent()


if __name__ == "__main__":
    main()
