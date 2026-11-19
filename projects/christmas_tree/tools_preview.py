# -*- coding: utf-8 -*-
"""离屏渲染几张代表性画面，用于出 preview.png 和检查观感。"""
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from PyQt6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat
from PyQt6.QtWidgets import QApplication
from OpenGL.GL import *


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="browse", choices=["browse", "focus", "open"])
    ap.add_argument("--gift", type=int, default=4, help="0-5，聚焦/打开用哪个礼物")
    ap.add_argument("--yaw", type=float, default=0.0)
    ap.add_argument("--pitch", type=float, default=2.5)
    ap.add_argument("--dist", type=float, default=4.95)
    ap.add_argument("--look-y", type=float, default=0.0, help="视线中心的世界高度")
    ap.add_argument("--pointer", default="", help="食指尖光标位置 x,y（归一化坐标）")
    ap.add_argument("--hit", action="store_true", help="光标压在礼物上（金色）")
    ap.add_argument("--w", type=int, default=1280)
    ap.add_argument("--h", type=int, default=720)
    ap.add_argument("--out", default=str(HERE / "preview.png"))
    args = ap.parse_args()

    fmt = QSurfaceFormat()
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    fmt.setSamples(4)
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
        raise SystemExit("FBO 不完整")

    import renderer
    r = renderer.Renderer(HERE)
    r.build()
    r.yaw = args.yaw
    r.pitch = args.pitch
    r.cam_dist = args.dist
    r.target_dist = args.dist
    r.look_y = args.look_y

    if args.scene == "browse":
        r.state = "browse"
        r.selected = -1
    else:
        r.state = args.scene
        r.selected = args.gift
        r.focus_idx = args.gift
        r.focus_t = 1.0
        r.open_t = 1.0 if args.scene == "open" else 0.0
        r.box_rot = 20.0
        r.char_rot = 25.0
        if args.scene == "open":
            r.bursts[args.gift].emit((0.0, 0.10, args.dist - 2.0))
            for _ in range(12):
                r.bursts[args.gift].update(0.016)

    # 让雪落下一点，画面不呆
    for _ in range(20):
        r.snow.update(0.03)

    if args.pointer:
        px, py = (float(v) for v in args.pointer.split(","))
        r.pointer = (px, py)
        r.pointer_hit = args.hit

    glBindFramebuffer(GL_FRAMEBUFFER, fbo)
    glViewport(0, 0, w, h)
    r.draw(w, h)

    glPixelStorei(GL_PACK_ALIGNMENT, 1)
    raw = glReadPixels(0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE)
    img = np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 4)
    img = cv2.flip(img, 0)
    ok, buf = cv2.imencode(".png", cv2.cvtColor(img, cv2.COLOR_RGBA2BGR))
    if not ok:
        raise SystemExit("PNG 编码失败")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(buf.tobytes())
    print("已保存", out.resolve())

    glBindFramebuffer(GL_FRAMEBUFFER, 0)
    ctx.doneCurrent()


if __name__ == "__main__":
    main()
