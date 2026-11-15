# -*- coding: utf-8 -*-
"""验证“中国地图贴片”是不是真的贴在球面上（不用摄像头，也不用显示窗口）。

    py -3.12 projects/hand_3d/tools_check_patch.py
    py -3.12 projects/hand_3d/tools_check_patch.py --save map_preview.png

做法：离屏渲染四个朝向，统计地图红色像素的数量和位置。
  front   正对中国 → 应该大面积可见、且居中
  side45  转 45°   → 应该跟着往侧面移
  side90  转 90°   → 应该几乎看不见
  back    转 180°  → 应该完全被地球挡住（0 像素）
这四组数字就是“粘在球上”和“浮在屏幕前”的区别：后者在任何朝向都会满量显示。
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import cv2
from PyQt6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat
from PyQt6.QtWidgets import QApplication
from OpenGL.GL import *

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))


def make_context(w, h):
    fmt = QSurfaceFormat()
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    fmt.setVersion(2, 1)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.NoProfile)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication.instance() or QApplication(sys.argv)   # 必须留存引用，否则段错误
    surface = QOffscreenSurface()
    surface.setFormat(fmt)
    surface.create()
    ctx = QOpenGLContext()
    ctx.setFormat(fmt)
    ctx.create()
    ctx.makeCurrent(surface)

    fbo = glGenFramebuffers(1)
    glBindFramebuffer(GL_FRAMEBUFFER, fbo)
    for target, dfmt in ((GL_COLOR_ATTACHMENT0, GL_RGBA8),
                         (GL_DEPTH_ATTACHMENT, GL_DEPTH_COMPONENT24)):
        rb = glGenRenderbuffers(1)
        glBindRenderbuffer(GL_RENDERBUFFER, rb)
        glRenderbufferStorage(GL_RENDERBUFFER, dfmt, w, h)
        glFramebufferRenderbuffer(GL_FRAMEBUFFER, target, GL_RENDERBUFFER, rb)
    return app, surface, ctx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--w", type=int, default=900)
    ap.add_argument("--h", type=int, default=720)
    ap.add_argument("--save", default="", help="把正面那张存成 PNG（中文路径安全）")
    args = ap.parse_args()

    W, H = args.w, args.h
    app, surface, ctx = make_context(W, H)

    import main as m  # noqa: E402  需要 context 之后再导入，initializeGL 才有 GL 可用

    glw = m.GLWidget()
    glw._timer.stop()
    glw.initializeGL()
    glw.resizeGL(W, H)
    glw.mode = m.MODE_MAP
    glw._focus_target = None
    glw.china_alpha = 1.0

    base = m.initial_rotation()
    cases = [
        ("front", base),
        ("side45", m.rotation("y", 45) @ base),
        ("side90", m.rotation("y", 90) @ base),
        ("back", m.rotation("y", 180) @ base),
    ]

    def render(rot, with_patch):
        """with_patch=False 时临时把显示列表摘掉——chinav_alpha 保持不变，
        这样云层状态两次一致，差分出来的就只有贴片本身。"""
        glw.rot = rot
        glw.china_alpha = 1.0
        saved = glw._china_list
        if not with_patch:
            glw._china_list = 0
        try:
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            glw.paintGL()
            glPixelStorei(GL_PACK_ALIGNMENT, 1)
            raw = glReadPixels(0, 0, W, H, GL_RGBA, GL_UNSIGNED_BYTE)
            return cv2.flip(np.frombuffer(raw, dtype=np.uint8).reshape(H, W, 4), 0)
        finally:
            glw._china_list = saved

    print(f"画布 {W}x{H}，中心 ({W // 2},{H // 2})")
    print("判据：同一朝向分别渲染“不画/画贴片”再逐像素比较，差异即贴片真正画出的像素")
    print(f"{'朝向':8s} {'贴图像素':>8s}  {'范围 x':>16s}  {'范围 y':>16s}  {'质心':>14s}")
    counts = {}
    centre = None
    for name, rot in cases:
        off = render(rot, False)
        on = render(rot, True)
        bgr = cv2.cvtColor(on, cv2.COLOR_RGBA2BGR)
        if name == "front" and args.save:
            ok, buf = cv2.imencode(".png", bgr)
            Path(args.save).write_bytes(buf.tobytes())
            print(f"  已保存 {args.save}")

        diff = np.abs(on[:, :, :3].astype(int) - off[:, :, :3].astype(int)).sum(axis=2)
        mask = diff > 45
        ys, xs = np.nonzero(mask)
        counts[name] = len(xs)
        if len(xs) < 20:
            print(f"{name:8s} {len(xs):8d}  {'—':>16s}  {'—':>16s}  {'—':>14s}")
        else:
            print(f"{name:8s} {len(xs):8d}  [{xs.min():4d},{xs.max():4d}]  "
                  f"[{ys.min():4d},{ys.max():4d}]  ({xs.mean():4.0f},{ys.mean():4.0f})")
            if name == "front":
                centre = (xs.mean(), ys.mean())

    off = None if centre is None else np.hypot(centre[0] - W / 2, centre[1] - H / 2)
    print()
    checks = [
        ("正对时地图大面积可见", counts["front"] > 15000),
        (f"正对时地图大致居中（偏移 {off:.0f}px）" if off is not None else "正对时能定位到地图",
         off is not None and off < 0.12 * W),
        ("转 45° 后可见面积明显减少（跟着转到侧面）",
         0 < counts["side45"] < counts["front"] * 0.8),
        ("转 90° 后几乎看不见", counts["side90"] < counts["front"] * 0.05),
        ("转到背面完全被地球挡住", counts["back"] == 0),
    ]
    ok = True
    for label, cond in checks:
        ok = ok and cond
        print(("  OK   " if cond else "  FAIL ") + label)
    print("\n" + ("贴片确实贴在球面上" if ok else "贴片行为不符合预期"))
    ctx.doneCurrent()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
