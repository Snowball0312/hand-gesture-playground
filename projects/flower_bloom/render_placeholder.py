# -*- coding: utf-8 -*-
"""临时程序化花型占位渲染。素材帧到位后，用 sprite_render.py 替换 draw_flower 即可。"""
import math
import cv2


def draw_flower(canvas, cx, cy, openness):
    # 茎与一片小叶
    cv2.line(canvas, (cx, cy + 70), (cx, cy + 215), (45, 105, 45), 4, cv2.LINE_AA)
    cv2.ellipse(canvas, (cx - 18, cy + 150), (16, 7), -25, 0, 360,
                 (55, 125, 55), -1, cv2.LINE_AA)

    # 两层花瓣：外层 9 片，内层 7 片；开放度控制长度、宽度与外展
    rings = [
        (9, 34 + openness * 38, 13 + openness * 11, (195, 150, 235)),
        (7, 24 + openness * 26, 10 + openness * 8, (232, 190, 245)),
    ]
    for count, length, width, color in rings:
        for i in range(count):
            ang = 360.0 / count * i
            rad = math.radians(ang)
            reach = length * 0.55
            px = cx + math.cos(rad) * reach
            py = cy + math.sin(rad) * reach
            cv2.ellipse(canvas, (int(px), int(py)),
                        (int(width), int(length * 0.55)), ang, 0, 360,
                        color, -1, cv2.LINE_AA)

    # 花心
    cv2.circle(canvas, (cx, cy), int(9 + openness * 6), (45, 200, 240), -1, cv2.LINE_AA)
    cv2.circle(canvas, (cx, cy), int(4 + openness * 3), (15, 150, 210), -1, cv2.LINE_AA)
