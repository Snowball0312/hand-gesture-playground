# -*- coding: utf-8 -*-
"""离屏渲染各项目的代表性画面，输出到各自目录，供 README 引用。

    py -3.12 tools/make_screenshots.py

不需要摄像头，也不改任何应用代码：直接调用各项目自己的绘制函数
（render_sprite / strokes / particles），
所以出来的图和运行时看到的是同一套像素逻辑。

一处必须说明：花开画的是真实玫瑰帧（本地有 rose_frames.npz 时），没有则用程序化花型。
地球与中国地图的图不走这里，见文件末尾的提示。
"""
import math
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "projects" / "flower_bloom"))
sys.path.insert(0, str(ROOT / "projects" / "hand_paint"))

FONT = cv2.FONT_HERSHEY_SIMPLEX


def save(path, img):
    """cv2.imwrite 在中文路径下会静默失败，统一走 imencode。"""
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError(f"编码失败：{path}")
    Path(path).write_bytes(buf.tobytes())
    print(f"  已保存 {Path(path).relative_to(ROOT)}  {img.shape[1]}x{img.shape[0]}  "
          f"{Path(path).stat().st_size / 1024:.0f} KB")


# ---------------------------------------------------------------- 花开
def shot_flower():
    print("[花开]")
    W, H = 800, 720
    openness = 0.86
    try:
        import render_sprite as sprite
        if not sprite.has_frames():
            raise RuntimeError("无花帧")
        draw_flower = sprite.draw_flower
        src = f"真实玫瑰帧 {len(sprite._frames)} 张"
    except Exception as e:
        from render_placeholder import draw_flower
        src = f"程序化花型（{e}）"

    canvas = np.zeros((H, W, 3), dtype=np.uint8)
    draw_flower(canvas, W // 2, int(H * 0.46), openness)

    # HUD 与 flower_app.py 主循环里的文案、字号、颜色保持一致
    hud = f"开放度 {openness * 100:3.0f}%   状态: 开放中   FPS: 60"
    cv2.putText(canvas, hud, (16, 34), FONT, 0.68, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(canvas, "推理 9ms   检测 30fps",
                (16, 62), FONT, 0.55, (180, 180, 190), 1, cv2.LINE_AA)
    cv2.putText(canvas, "张开手掌开花 / 握拳合花 / ESC退出",
                (16, H - 18), FONT, 0.55, (170, 170, 170), 1, cv2.LINE_AA)

    print(f"  素材：{src}")
    save(ROOT / "projects" / "flower_bloom" / "preview.png", canvas)


# ---------------------------------------------------------------- 手势作画
def cubic(p0, p1, p2, p3, n=90):
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        x = u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0]
        y = u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]
        out.append((x, y))
    return out


def shot_paint():
    print("[手势作画]")
    from strokes import StrokeManager
    from particles import ExplosionParticles

    W, H = 960, 720          # 与 paint_app.py 一致
    BG = (18, 14, 12)
    CURSOR_PAINT = (120, 220, 120)

    mgr = StrokeManager()

    # 一条横贯画面的长曲线
    mgr.begin()
    for x, y in cubic((70, 470), (300, 130), (640, 620), (896, 250)):
        mgr.extend(x, y)
    mgr.end()

    # 右上一个螺旋
    mgr.begin()
    for i in range(200):
        t = i / 17.0
        r = 8 + t * 13
        mgr.extend(676 + math.cos(t) * r, 178 + math.sin(t) * r * 0.82)
    mgr.end()

    # 左下一个环，正在被「张掌爆炸擦除」
    mgr.begin()
    for i in range(90):
        a = i / 89 * 2 * math.pi
        mgr.extend(226 + math.cos(a) * 82, 596 + math.sin(a) * 66)
    erased = mgr.strokes[-1]
    mgr.end()

    particles = ExplosionParticles()
    particles.explode(erased.points)
    for _ in range(9):
        particles.update(1 / 60)
    mgr.strokes.remove(erased)      # 擦除会先把笔画删掉，再让粒子飞散

    canvas = np.full((H, W, 3), BG, dtype=np.uint8)
    mgr.render(canvas)
    particles.render(canvas)

    # 光标停在长曲线末端，PAINT 模式
    sx, sy = (896, 250)
    cv2.circle(canvas, (sx, sy), 10, CURSOR_PAINT, 2, cv2.LINE_AA)
    cv2.circle(canvas, (sx, sy), 2, CURSOR_PAINT, -1, cv2.LINE_AA)

    hud = (f"mode: 画笔   strokes: {len(mgr.strokes)}   "
           f"FPS: 60   infer: 9ms")
    cv2.putText(canvas, hud, (12, 28), FONT, 0.62, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(canvas, "食指画 / 捏合拖动 / 张掌爆炸擦除 / c清空 / ESC退出",
                (12, H - 14), FONT, 0.55, (230, 230, 230), 1, cv2.LINE_AA)

    save(ROOT / "projects" / "hand_paint" / "preview.png", canvas)


if __name__ == "__main__":
    shot_flower()
    shot_paint()
    print("\n地球的两张图已存在，如需重出：")
    print("  py -3.12 projects/hand_3d/tools_preview_globe.py --from-main "
          "--out projects/hand_3d/globe_preview.png")
    print("  py -3.12 projects/hand_3d/tools_check_patch.py --save "
          "projects/hand_3d/map_preview.png")
