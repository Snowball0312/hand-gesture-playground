# -*- coding: utf-8 -*-
"""爆炸粒子：笔画被张开手掌命中后，沿笔画散开并渐隐。"""
import random
import math
import cv2


class ExplosionParticles:
    def __init__(self):
        self.parts = []

    def explode(self, points, color=(255, 245, 220)):
        if len(points) < 2:
            return
        step = max(1, len(points) // 90)
        for i in range(0, len(points), step):
            x, y = points[i]
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(0.8, 4.2)
            self.parts.append([
                float(x), float(y),
                math.cos(angle) * speed, math.sin(angle) * speed,
                random.uniform(0.35, 0.85),
                color,
                random.uniform(1.6, 3.2),
            ])

    def update(self, dt):
        k = dt * 60.0
        alive = []
        for x, y, vx, vy, life, color, size in self.parts:
            life -= dt
            if life <= 0:
                continue
            x += vx * k
            y += vy * k
            vy += 0.045 * k
            vx *= 0.96 ** k
            vy *= 0.98 ** k
            alive.append([x, y, vx, vy, life, color, size])
        self.parts = alive

    def render(self, canvas):
        for x, y, vx, vy, life, color, size in self.parts:
            alpha = max(0.0, min(1.0, life / 0.55))
            c = tuple(int(ch * alpha) for ch in color)
            cv2.circle(canvas, (int(x), int(y)), max(1, int(size)), c, -1, cv2.LINE_AA)
