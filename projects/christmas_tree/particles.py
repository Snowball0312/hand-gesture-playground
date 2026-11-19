# -*- coding: utf-8 -*-
"""粒子系统：飘雪 + 礼物爆开特效。

全部用 numpy 批量更新位置，绘制用 GL_POINTS 立即模式。
粒子数控制在几百，单速足够，不拖帧。
"""
import numpy as np
from OpenGL.GL import *


class Snow:
    """深蓝夜空里缓慢飘落的雪，铺满镜头前方的一个体积。"""

    def __init__(self, n=1000, x_range=3.4, y_lo=-2.2, y_hi=4.6, z_range=2.6):
        rng = np.random.default_rng(11)
        self.n = n
        self.x = rng.uniform(-x_range, x_range, n)
        self.y = rng.uniform(y_lo, y_hi, n)
        self.z = rng.uniform(-z_range, z_range, n)
        self.vy = rng.uniform(0.22, 0.68, n)
        self.drift = rng.uniform(-0.10, 0.10, n)
        self.phase = rng.uniform(0.0, 2 * np.pi, n)
        self.x_range = x_range
        self.y_lo, self.y_hi = y_lo, y_hi
        self._t = 0.0

    def update(self, dt):
        self._t += dt
        self.y -= self.vy * dt
        self.x += self.drift * dt
        # 下落到底就从顶上重新飘下
        low = self.y < self.y_lo
        if low.any():
            self.y[low] += (self.y_hi - self.y_lo)
        # 横向出界就回卷
        self.x[self.x > self.x_range] -= 2 * self.x_range
        self.x[self.x < -self.x_range] += 2 * self.x_range

    def draw(self):
        glDisable(GL_LIGHTING)
        glDisable(GL_TEXTURE_2D)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glDepthMask(GL_FALSE)
        glPointSize(2.0)
        glColor4f(0.86, 0.92, 1.0, 0.80)
        glBegin(GL_POINTS)
        for i in range(self.n):
            sway = 0.05 * np.sin(self._t * 0.8 + self.phase[i])
            glVertex3f(self.x[i] + sway, self.y[i], self.z[i])
        glEnd()
        glDisable(GL_POINT_SMOOTH)
        glPointSize(1.0)
        glDepthMask(GL_TRUE)
        glDisable(GL_BLEND)


class Burst:
    """一次性爆开的粒子团。每种礼物用不同参数配置出不同性格。

    mode:
        burst —— 向四面八方炸开
        ring  —— 水平一圈向外扩散（铃铛涟漪）
        rain  —— 从上方落下（糖果雨）
        rise  —— 向上飘散（爱心）
    """

    def __init__(self, palette, count=260, mode="burst", speed=1.5, life=1.5,
                 gravity=-1.6, drag=0.965, size=7.0, additive=True,
                 spread=0.10, up_bias=0.0):
        self.palette = np.array(palette, dtype=float)
        self.count = count
        self.mode = mode
        self.speed = speed
        self.life0 = life
        self.gravity = gravity
        self.drag = drag
        self.size = size
        self.additive = additive
        self.spread = spread
        self.up_bias = up_bias

        self.pos = np.zeros((count, 3))
        self.vel = np.zeros((count, 3))
        self.life = np.zeros(count)
        self.col = np.zeros((count, 3))
        self.active = False

    def emit(self, origin=(0.0, 0.0, 0.0)):
        rng = np.random.default_rng()
        n = self.count
        ox, oy, oz = origin

        if self.mode == "ring":
            ang = rng.uniform(0, 2 * np.pi, n)
            r = rng.uniform(0.02, 0.10, n)
            self.pos[:, 0] = ox + np.cos(ang) * r
            self.pos[:, 1] = oy + rng.uniform(-0.04, 0.04, n)
            self.pos[:, 2] = oz + np.sin(ang) * r
            spd = self.speed * rng.uniform(0.7, 1.3, n)
            self.vel[:, 0] = np.cos(ang) * spd
            self.vel[:, 1] = rng.uniform(0.05, 0.35, n)
            self.vel[:, 2] = np.sin(ang) * spd
        elif self.mode == "rain":
            self.pos[:, 0] = ox + rng.uniform(-0.7, 0.7, n)
            self.pos[:, 1] = oy + rng.uniform(1.2, 2.2, n)
            self.pos[:, 2] = oz + rng.uniform(-0.5, 0.5, n)
            self.vel[:, 0] = rng.uniform(-0.15, 0.15, n)
            self.vel[:, 1] = -rng.uniform(0.8, 1.8, n)
            self.vel[:, 2] = rng.uniform(-0.15, 0.15, n)
        elif self.mode == "rise":
            # 从人物下方向两侧升起，避免糊在脸上
            ang = rng.uniform(0, 2 * np.pi, n)
            rad = rng.uniform(0.18, 0.42, n)
            self.pos[:, 0] = ox + np.cos(ang) * rad
            self.pos[:, 1] = oy - 0.45 + rng.uniform(-0.1, 0.1, n)
            self.pos[:, 2] = oz + np.sin(ang) * rad * 0.7
            self.vel[:, 0] = np.cos(ang) * rng.uniform(0.1, 0.35, n)
            self.vel[:, 1] = rng.uniform(0.6, 1.3, n)
            self.vel[:, 2] = np.sin(ang) * rng.uniform(0.1, 0.35, n)
        else:  # burst
            v = rng.normal(size=(n, 3))
            v /= np.linalg.norm(v, axis=1, keepdims=True) + 1e-9
            spd = self.speed * rng.uniform(0.45, 1.25, n)
            self.pos[:, 0] = ox + rng.normal(0, self.spread, n)
            self.pos[:, 1] = oy + rng.normal(0, self.spread, n)
            self.pos[:, 2] = oz + rng.normal(0, self.spread, n)
            self.vel = v * spd[:, None]
            self.vel[:, 1] += self.up_bias

        idx = rng.integers(0, len(self.palette), n)
        self.col = self.palette[idx]
        self.life = self.life0 * rng.uniform(0.65, 1.15, n)
        self.maxlife = self.life.copy()
        self.active = True

    def update(self, dt):
        if not self.active:
            return
        alive = self.life > 0
        if not alive.any():
            self.active = False
            return
        self.life[alive] -= dt
        self.vel[alive, 1] += self.gravity * dt
        self.vel[alive] *= self.drag
        self.pos[alive] += self.vel[alive] * dt

    def draw(self):
        if not self.active:
            return
        alive = self.life > 0
        if not alive.any():
            return
        glDisable(GL_LIGHTING)
        glDisable(GL_TEXTURE_2D)
        glEnable(GL_BLEND)
        if self.additive:
            glBlendFunc(GL_SRC_ALPHA, GL_ONE)
        else:
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glDepthMask(GL_FALSE)
        glPointSize(self.size)
        glEnable(GL_POINT_SMOOTH)
        glBegin(GL_POINTS)
        idx = np.nonzero(alive)[0]
        for i in idx:
            a = max(0.0, min(1.0, self.life[i] / max(self.maxlife[i], 1e-6)))
            r, g, b = self.col[i]
            glColor4f(r, g, b, a)
            glVertex3f(self.pos[i, 0], self.pos[i, 1], self.pos[i, 2])
        glEnd()
        glDisable(GL_POINT_SMOOTH)
        glPointSize(1.0)
        glDepthMask(GL_TRUE)
        glDisable(GL_BLEND)
