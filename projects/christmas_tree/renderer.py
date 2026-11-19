# -*- coding: utf-8 -*-
"""圣诞树的渲染器：与 Qt 解耦，只依赖 OpenGL。

这样主程序用它渲染到窗口，tools_preview.py 用它渲染到离屏 FBO，
两边画面完全一致，改一处就够。

画面分层（从后到前）：
  夜空渐变 → 地面薄雪 → 松树/挂饰/彩灯/顶星 → 树脚礼物盒 →
  飘雪 →（聚焦时）背景虚化 → 居中礼物 → 镜头小窗
"""
import math

import ctypes

import cv2
import numpy as np
from OpenGL.GL import *
from OpenGL.GLU import *

import scene
from particles import Snow, Burst

SCENE_Y = -1.44          # 整棵树下移，让相机看向原点时树正好居中
FOV = 45.0
PINCH_PALETTE = {
    "gold": [(1.0, 0.88, 0.45), (1.0, 0.72, 0.20), (1.0, 0.97, 0.80)],
}
ITEM_SCALE = 1.0

# 六种礼物的粒子参数（顺序与 scene 的礼物一致）
BURST_SPECS = [
    dict(palette=[(1.0, 0.86, 0.40), (1.0, 0.70, 0.15), (1.0, 0.97, 0.85)],
         count=300, mode="burst", speed=2.4, life=1.4, gravity=-1.4,
         drag=0.965, size=8.0, additive=True),
    dict(palette=[(0.65, 0.88, 1.0), (0.85, 0.96, 1.0), (0.45, 0.75, 1.0)],
         count=260, mode="burst", speed=1.6, life=1.9, gravity=-0.55,
         drag=0.975, size=7.0, additive=True),
    dict(palette=[(1.0, 0.85, 0.42), (1.0, 0.68, 0.12), (1.0, 0.96, 0.78)],
         count=280, mode="ring", speed=2.3, life=1.5, gravity=-1.0,
         drag=0.97, size=7.0, additive=True),
    dict(palette=[(0.88, 0.12, 0.15), (0.10, 0.72, 0.40), (0.98, 0.97, 0.95),
                  (1.0, 0.78, 0.18)],
         count=340, mode="burst", speed=2.6, life=1.7, gravity=-3.2,
         drag=0.99, size=9.0, additive=False),
    dict(palette=[(1.0, 0.35, 0.52), (1.0, 0.55, 0.68), (0.95, 0.20, 0.38)],
         count=130, mode="rise", speed=0.9, life=2.0, gravity=0.10,
         drag=0.985, size=7.0, additive=True),
    dict(palette=[(1.0, 0.82, 0.35), (0.88, 0.15, 0.20), (0.95, 0.95, 1.0),
                  (0.15, 0.65, 0.85)],
         count=320, mode="rain", speed=1.0, life=2.0, gravity=-2.4,
         drag=0.995, size=7.0, additive=False),
]


def lerp3(a, b, t):
    return (a[0] + (b[0] - a[0]) * t,
            a[1] + (b[1] - a[1]) * t,
            a[2] + (b[2] - a[2]) * t)


class Renderer:
    def __init__(self, here):
        self.assets = scene.SceneAssets(here)
        self.snow = Snow(n=1000, y_lo=-1.5, y_hi=3.0, z_range=2.6)
        self.bursts = [Burst(**spec) for spec in BURST_SPECS]
        self.built = False

        # 视角
        self.yaw = 0.0
        self.pitch = 2.5
        self.cam_dist = 4.95
        self.target_dist = 4.95
        self.look_y = 0.0

        # 交互显示状态（由主程序写入）
        self.state = "browse"
        self.selected = -1
        self.focus_idx = -1
        self.pointer = None          # 右手食指尖的归一化屏幕坐标，None 表示没有右手
        self.pointer_hit = False     # 光标正压在某个礼物上
        self.focus_t = 0.0
        self.open_t = 0.0
        self.box_rot = 0.0
        self.char_rot = 0.0
        self.time = 0.0

        # 后处理
        self.blur_tex = 0
        self.blur_ok = True
        self._blur_fail = 0
        self._blur_ready = False
        self._blur_last = -1.0
        self.resolve_fbo = 0
        self._blur_size = (0, 0)
        self.small_tex = 0
        self.small_fbo = 0
        self._small_size = (0, 0)

        # 镜头小窗
        self.cam_tex = 0
        self.cam_w = 0
        self.cam_h = 0
        self.show_camera = True

    # ---- 构建 ----
    def build(self):
        self.assets.build()
        self.blur_tex = glGenTextures(1)
        self.cam_tex = glGenTextures(1)
        self.built = True

    # ---- 视角数学 ----
    def rot_matrix(self):
        """只含 yaw 的旋转：树绕自己的竖轴转。

        pitch 不在这里 —— 俯仰是相机抬高，不是把树翻过去。
        以前把整棵树按 pitch 侧翻、雪地却保持水平，俯视时礼物悬空、
        雪面横切树干，全是穿模。
        """
        ry = math.radians(self.yaw)
        cy, sy = math.cos(ry), math.sin(ry)
        return np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]])

    def cam_offset(self):
        """相机相对视线中心的偏移 (y, z)。pitch 越大相机越高、越靠近顶视。"""
        p = math.radians(self.pitch)
        return (math.sin(p) * self.cam_dist, math.cos(p) * self.cam_dist)

    def world_of(self, local):
        p = self.rot_matrix() @ np.array(local, dtype=float)
        return (float(p[0]), float(p[1]) + SCENE_Y, float(p[2]))

    def gift_screen_positions(self, w, h):
        import tree_rules as R
        aspect = w / max(1, h)
        Rm = self.rot_matrix()
        cam_y = self.cam_offset()[0]
        out = []
        for (x, _, z) in self.assets.gifts:
            p = Rm @ np.array([x, 0.17, z], dtype=float)
            p[1] += SCENE_Y
            out.append(R.project(p, self.cam_dist, aspect, FOV,
                                 cam_y=cam_y, look_y=self.look_y))
        return out

    def focus_center(self, dist=3.1):
        """屏幕中心、距离相机 dist 的那个世界点（聚焦时礼物飞到这里）。"""
        cy, cz = self.cam_offset()
        k = 1.0 - dist / max(self.cam_dist, 1e-3)
        return (0.0, self.look_y + cy * k, cz * k)

    # ---- 动画推进 ----
    def update(self, dt):
        self.time += dt
        target_focus = 1.0 if self.state in ("focus", "open") else 0.0
        target_open = 1.0 if self.state == "open" else 0.0
        self.focus_t += (target_focus - self.focus_t) * min(1.0, dt * 7.5)
        self.open_t += (target_open - self.open_t) * min(1.0, dt * 7.5)
        if self.state in ("focus", "open"):
            self.box_rot += 28.0 * dt
        if self.state == "open":
            self.char_rot += 42.0 * dt
        self.cam_dist += (self.target_dist - self.cam_dist) * min(1.0, dt * 6.0)
        if self.state == "browse":
            self._blur_ready = False
        self.snow.update(dt)
        for b in self.bursts:
            b.update(dt)

    # ---- 绘制 ----
    def draw(self, w, h, frame=None):
        w = max(1, w)
        h = max(1, h)
        self.width = w
        self.height = h
        glViewport(0, 0, w, h)
        glClearColor(0.010, 0.016, 0.045, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        self._draw_sky_gradient(w, h)

        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(FOV, w / max(1, h), 0.1, 100.0)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        cy, cz = self.cam_offset()
        gluLookAt(0, self.look_y + cy, cz, 0, self.look_y, 0, 0, 1, 0)

        glEnable(GL_DEPTH_TEST)
        glEnable(GL_CULL_FACE)
        glCullFace(GL_BACK)
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glLightfv(GL_LIGHT0, GL_POSITION, [4.5, 5.2, 6.0, 1.0])
        glLightfv(GL_LIGHT0, GL_DIFFUSE, [1.30, 1.22, 1.08, 1.0])
        glLightfv(GL_LIGHT0, GL_SPECULAR, [0.55, 0.55, 0.55, 1.0])
        # 冷色补光，压掉树身背光面过黑的地方，层次更柔和
        glEnable(GL_LIGHT1)
        glLightfv(GL_LIGHT1, GL_POSITION, [-5.0, 2.0, 4.0, 1.0])
        glLightfv(GL_LIGHT1, GL_DIFFUSE, [0.30, 0.40, 0.60, 1.0])
        glLightfv(GL_LIGHT1, GL_SPECULAR, [0.0, 0.0, 0.0, 1.0])
        glLightModelfv(GL_LIGHT_MODEL_AMBIENT, [0.30, 0.32, 0.40, 1.0])

        self._draw_ground()
        self._draw_tree_group()
        self._draw_snow_mound()
        self._draw_lights()
        self._draw_star()
        self.snow.draw()
        self._draw_star_glow()

        if self.focus_t > 0.02 and (self.selected >= 0 or self.focus_idx >= 0):
            self._blur_background(self.focus_t)
            self._draw_focused()

        if frame is not None and self.show_camera:
            self._upload_camera(frame)
        if self.show_camera and self.cam_tex:
            self._draw_camera_preview(w, h)

        # 指尖光标画在最上层：它只是一块屏幕标记，不该被树或小窗挡住
        if self.pointer is not None and self.state == "browse":
            self._draw_pointer(w, h)

    def _draw_pointer(self, w, h):
        """右手食指尖的光标：一个细圆环 + 中心点。

        正交像素坐标、关掉深度测试，所以不管手在树前面还是后面都清晰可见；
        命中礼物时换成暖金色并放大一圈，等于"可以捏了"的提示。
        """
        px = float(self.pointer[0]) * w
        py = float(self.pointer[1]) * h
        s = h / 800.0                       # 按窗口高度缩放，换分辨率不会突然变大变小
        hit = self.pointer_hit

        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        glOrtho(0, w, h, 0, -1, 1)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()

        glDisable(GL_DEPTH_TEST)
        glDisable(GL_LIGHTING)
        glDisable(GL_TEXTURE_2D)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glEnable(GL_LINE_SMOOTH)

        r = (17.0 if hit else 13.0) * s
        # 先描一圈深色底：光标经常压在亮色礼物上，只有亮环会和礼物的缎带糊在一起
        glColor4f(0.0, 0.0, 0.02, 0.45)
        glLineWidth(max(2.5, 4.0 * s))
        glBegin(GL_LINE_LOOP)
        for i in range(28):
            a = 2.0 * math.pi * i / 28.0
            glVertex2f(px + math.cos(a) * r, py + math.sin(a) * r)
        glEnd()

        if hit:
            glColor4f(1.0, 0.86, 0.52, 0.95)
        else:
            glColor4f(1.0, 1.0, 1.0, 0.80)
        glLineWidth(max(1.5, 2.0 * s))
        glBegin(GL_LINE_LOOP)
        for i in range(28):
            a = 2.0 * math.pi * i / 28.0
            glVertex2f(px + math.cos(a) * r, py + math.sin(a) * r)
        glEnd()

        glEnable(GL_POINT_SMOOTH)
        if hit:
            glColor4f(1.0, 0.88, 0.55, 0.95)
        else:
            glColor4f(1.0, 1.0, 1.0, 0.85)
        glPointSize(max(3.5, 4.2 * s))
        glBegin(GL_POINTS)
        glVertex2f(px, py)
        glEnd()

        if hit:
            # 命中再套一层更淡的大圈：尺寸变化比单纯变色更容易被注意到
            glColor4f(1.0, 0.86, 0.52, 0.30)
            glLineWidth(max(1.0, 1.2 * s))
            glBegin(GL_LINE_LOOP)
            for i in range(28):
                a = 2.0 * math.pi * i / 28.0
                glVertex2f(px + math.cos(a) * r * 1.42,
                           py + math.sin(a) * r * 1.42)
            glEnd()

        glDisable(GL_LINE_SMOOTH)
        glDisable(GL_POINT_SMOOTH)
        glDisable(GL_BLEND)
        glEnable(GL_DEPTH_TEST)
        glLineWidth(1.0)
        glPointSize(1.0)

        glPopMatrix()
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)

    # ---- 各层 ----
    def _draw_sky_gradient(self, w, h):
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_LIGHTING)
        glDisable(GL_TEXTURE_2D)
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        glOrtho(0, 1, 0, 1, -1, 1)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()
        glDisable(GL_BLEND)
        glBegin(GL_QUADS)
        glColor3f(0.016, 0.026, 0.070)
        glVertex3f(0, 0, 0)
        glVertex3f(1, 0, 0)
        glColor3f(0.030, 0.055, 0.110)
        glVertex3f(1, 1, 0)
        glVertex3f(0, 1, 0)
        glEnd()
        glPopMatrix()
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)
        glEnable(GL_DEPTH_TEST)

    def _draw_ground(self):
        glPushMatrix()
        glTranslatef(0, SCENE_Y, 0)
        glDisable(GL_LIGHTING)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        # 地面要写深度：否则树干伸到雪面以下的那一截会画在地面之上，
        # 看起来像穿过了半透明的雪面。写了深度，地面以下的部分就被真正埋掉。
        glDepthMask(GL_TRUE)
        glDisable(GL_CULL_FACE)
        glCallList(self.assets.ground_list)
        glEnable(GL_CULL_FACE)
        glDisable(GL_BLEND)
        glEnable(GL_LIGHTING)
        glPopMatrix()

    def _draw_tree_group(self):
        glPushMatrix()
        glTranslatef(0, SCENE_Y, 0)
        glMultMatrixf(self._to_gl(self.rot_matrix()))

        glDisable(GL_CULL_FACE)
        glCallList(self.assets.tree_list)
        self._draw_needles()
        glCallList(self.assets.ornament_list)
        glEnable(GL_CULL_FACE)


        # 礼物盒在雪地上的软阴影：盒子才像压在地上。
        # 用带顶点 alpha 的扇形，而不是贴图四边形——glow_tex 的混合模式在
        # 这条绘制路径上不可靠（加色混合下黑色阴影等于没画）。
        glPushMatrix()
        glDisable(GL_LIGHTING)
        glDisable(GL_TEXTURE_2D)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glDisable(GL_CULL_FACE)
        glDepthMask(GL_FALSE)
        for (gx, _, gz) in self.assets.gifts:
            glBegin(GL_TRIANGLE_FAN)
            glColor4f(0.0, 0.0, 0.01, 0.62)
            glVertex3f(gx, 0.005, gz)
            for k in range(19):
                a = 2 * math.pi * k / 18
                glColor4f(0.0, 0.0, 0.01, 0.0)
                glVertex3f(gx + math.cos(a) * 0.36, 0.005,
                           gz + math.sin(a) * 0.36)
            glEnd()
        glDepthMask(GL_TRUE)
        glDisable(GL_BLEND)
        glEnable(GL_CULL_FACE)
        glEnable(GL_LIGHTING)
        glPopMatrix()

        # 树脚礼物盒（聚焦中的那个不在原位画）
        for i, (x, _, z) in enumerate(self.assets.gifts):
            if i == self.focus_idx and self.focus_t > 0.02:
                continue
            hi = (i == self.selected and self.state == "browse")
            self._draw_box((x, 0.17, z), 1.0, 0.0, scene.BOX_COLS[i], hi)

        glPopMatrix()

    def _draw_snow_mound(self):
        """树脚积雪：画在树之后，才能盖住树干底部的接缝。"""
        glPushMatrix()
        glTranslatef(0, SCENE_Y, 0)
        glDisable(GL_LIGHTING)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glDepthMask(GL_FALSE)
        glDisable(GL_CULL_FACE)
        glCallList(self.assets.snow_mound_list)
        glEnable(GL_CULL_FACE)
        glDepthMask(GL_TRUE)
        glDisable(GL_BLEND)
        glEnable(GL_LIGHTING)
        glPopMatrix()

    def _draw_needles(self):
        """一万多根松针：顶点数组一次画完。

        每顶点 颜色(3)+法线(3)+坐标(3) 交错存放，绘制时按 offset 分别指向
        color / normal / vertex，省掉逐根 glBegin 的调用开销。
        """
        arr = self.assets.needles
        if arr is None or arr.size == 0:
            return
        n = int(arr.shape[0])
        base = arr.ctypes.data
        stride = 9 * 4
        glEnable(GL_COLOR_MATERIAL)
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)
        glMaterialfv(GL_FRONT_AND_BACK, GL_SPECULAR, [0.09, 0.11, 0.09, 1.0])
        glMaterialf(GL_FRONT_AND_BACK, GL_SHININESS, 14.0)
        glEnableClientState(GL_COLOR_ARRAY)
        glEnableClientState(GL_NORMAL_ARRAY)
        glEnableClientState(GL_VERTEX_ARRAY)
        glColorPointer(3, GL_FLOAT, stride, ctypes.c_void_p(base))
        glNormalPointer(GL_FLOAT, stride, ctypes.c_void_p(base + 12))
        glVertexPointer(3, GL_FLOAT, stride, ctypes.c_void_p(base + 24))
        glDrawArrays(GL_TRIANGLES, 0, n)
        glDisableClientState(GL_VERTEX_ARRAY)
        glDisableClientState(GL_NORMAL_ARRAY)
        glDisableClientState(GL_COLOR_ARRAY)
        glDisable(GL_COLOR_MATERIAL)

    def _draw_box(self, local, scale, rot_y, color, highlight=False, ):
        glPushMatrix()
        glTranslatef(local[0], local[1], local[2])
        if rot_y:
            glRotatef(rot_y, 0, 1, 0)
        glScalef(scale, scale, scale)
        # 蝴蝶结的两个耳是"非均匀缩放"的椭球：法线经逆转置变换后会被拉长十几倍，
        # 不归一化就会整片过曝成白色（看着像没受光的白团）。这里局部开一下，
        # 画完恢复，不影响别处依赖默认状态的几何。
        glEnable(GL_NORMALIZE)
        em = (0.10, 0.07, 0.01) if highlight else (0.0, 0.0, 0.0)
        scene._set_mat(color, specular=(0.35, 0.35, 0.35), shininess=45, emission=em)
        glCallList(self.assets.box_body)
        # 盖子比盒身亮一档：光从上方来，顶盖本来就该更亮，层次才分得开
        lit = tuple(min(1.0, c * 1.14 + 0.02) for c in color)
        scene._set_mat(lit, specular=(0.45, 0.45, 0.45), shininess=55, emission=em)
        glCallList(self.assets.box_lid)
        glCallList(self.assets.box_ribbon)
        glDisable(GL_NORMALIZE)
        glPopMatrix()

    def _draw_lights(self):
        lp = self.assets.light_pos
        if lp is None:
            return
        Rm = self.rot_matrix()
        worlds = lp @ Rm.T
        worlds[:, 1] += SCENE_Y

        glDisable(GL_LIGHTING)
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, self.assets.glow_tex)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE)
        glDepthMask(GL_FALSE)
        glBegin(GL_QUADS)
        half = 0.050
        for i in range(len(worlds)):
            ph = i * 0.30 - self.time * 2.4
            b = 0.5 + 0.5 * math.sin(ph)
            m = i % 3
            if m == 0:
                c = (1.0, 0.86, 0.45)
            elif m == 1:
                c = (1.0, 0.60, 0.26)
            else:
                c = (1.0, 0.95, 0.78)
            a = 0.22 + 0.52 * b
            x, y, z = worlds[i]
            glColor4f(c[0], c[1], c[2], a)
            glTexCoord2f(0, 0); glVertex3f(x - half, y - half, z)
            glTexCoord2f(1, 0); glVertex3f(x + half, y - half, z)
            glTexCoord2f(1, 1); glVertex3f(x + half, y + half, z)
            glTexCoord2f(0, 1); glVertex3f(x - half, y + half, z)
        glEnd()
        # 点亮的小灯芯
        glDisable(GL_TEXTURE_2D)
        glPointSize(3.4)
        glBegin(GL_POINTS)
        for i in range(len(worlds)):
            x, y, z = worlds[i]
            glColor4f(1.0, 0.96, 0.82, 0.95)
            glVertex3f(x, y, z + 0.02)
        glEnd()
        glPointSize(1.0)
        glDepthMask(GL_TRUE)
        glDisable(GL_BLEND)
        glEnable(GL_LIGHTING)

        # 高亮礼物脚下的一圈暖光
        if self.selected >= 0 and self.state == "browse":
            gx, _, gz = self.assets.gifts[self.selected]
            p = self.world_of((gx, 0.02, gz))
            pulse = 0.5 + 0.5 * math.sin(self.time * 4.0)
            self._draw_glow_xz(p, 0.95 + 0.12 * pulse,
                               (1.0, 0.82, 0.42), 0.35 + 0.25 * pulse)

    def _draw_star(self):
        """顶星：绑在树干尖上，跟着树一起转。

        位置用 world_of 算，姿态也要带上 yaw——只摆位置不转姿态，树在转、
        星却一直正对镜头，看着就像贴在屏幕上的一块贴纸。
        俯仰不做抵消：星本来就是竖直插在树尖上的，相机抬高时它自然俯视
        缩短一点才是对的；实体星有厚度和棱面，缩短也不塌。
        """
        pos = self.world_of((0.0, scene.STAR_Y, 0.0))
        glPushMatrix()
        glTranslatef(float(pos[0]), float(pos[1]), float(pos[2]))
        glRotatef(self.yaw, 0.0, 1.0, 0.0)
        glCallList(self.assets.star_list)
        glPopMatrix()

    def _draw_star_glow(self):
        pos = self.world_of((0.0, scene.STAR_Y, 0.0))
        pulse = 0.5 + 0.5 * math.sin(self.time * 2.2)
        self._draw_glow_xy(pos, 1.15 + 0.25 * pulse,
                           (1.0, 0.82, 0.40), 0.30 + 0.22 * pulse)

    def _draw_glow_xy(self, pos, size, color, alpha):
        if not self.assets.glow_tex:
            return
        glPushMatrix()
        glTranslatef(pos[0], pos[1], pos[2])
        # 光晕是一块朝向 +Z 的四边形，相机一抬高就会侧过去变成薄片
        glRotatef(-self.pitch, 1.0, 0.0, 0.0)
        glDisable(GL_LIGHTING)
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, self.assets.glow_tex)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE)
        glDepthMask(GL_FALSE)
        glColor4f(color[0], color[1], color[2], alpha)
        h = size * 0.5
        glBegin(GL_QUADS)
        glTexCoord2f(0, 0); glVertex3f(-h, -h, 0)
        glTexCoord2f(1, 0); glVertex3f(h, -h, 0)
        glTexCoord2f(1, 1); glVertex3f(h, h, 0)
        glTexCoord2f(0, 1); glVertex3f(-h, h, 0)
        glEnd()
        glDepthMask(GL_TRUE)
        glDisable(GL_BLEND)
        glDisable(GL_TEXTURE_2D)
        glEnable(GL_LIGHTING)
        glPopMatrix()

    def _draw_glow_xz(self, pos, size, color, alpha):
        if not self.assets.glow_tex:
            return
        glPushMatrix()
        glTranslatef(pos[0], pos[1], pos[2])
        glDisable(GL_LIGHTING)
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, self.assets.glow_tex)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE)
        glDepthMask(GL_FALSE)
        glColor4f(color[0], color[1], color[2], alpha)
        h = size * 0.5
        glBegin(GL_QUADS)
        glTexCoord2f(0, 0); glVertex3f(-h, 0, -h)
        glTexCoord2f(1, 0); glVertex3f(h, 0, -h)
        glTexCoord2f(1, 1); glVertex3f(h, 0, h)
        glTexCoord2f(0, 1); glVertex3f(-h, 0, h)
        glEnd()
        glDepthMask(GL_TRUE)
        glDisable(GL_BLEND)
        glDisable(GL_TEXTURE_2D)
        glEnable(GL_LIGHTING)
        glPopMatrix()

    # ---- 聚焦态 ----
    def _focused_parts(self):
        i = self.selected if self.selected >= 0 else self.focus_idx
        gx, _, gz = self.assets.gifts[i]
        base = self.world_of((gx, 0.17, gz))
        # 屏幕中心不是世界坐标里的一条固定直线：相机抬高后，
        # 中心点必须沿视线方向取，否则礼物会偏到画面上方/下方
        center = self.focus_center(3.1)
        t = self._ease(self.focus_t)
        pos = lerp3(base, center, t)
        return i, pos, t

    @staticmethod
    def _ease(t):
        t = max(0.0, min(1.0, t))
        return 1.0 - (1.0 - t) ** 3

    def _draw_focused(self):
        i, pos, t = self._focused_parts()
        # 背后的一团柔光，把礼物从暗背景里托出来
        self._draw_glow_xy((pos[0], pos[1], pos[2] - 0.6), 2.6, (1.0, 0.85, 0.55),
                           0.16 * self.focus_t)

        box_scale = (1.0 + 0.22 * t) * (1.0 - 0.55 * self.open_t)
        if self.open_t < 0.55:
            self._draw_box(pos, box_scale, self.box_rot, scene.BOX_COLS[i], True)

        if self.open_t > 0.02:
            item_scale = ITEM_SCALE * self._ease(self.open_t)
            card = self.assets.characters[i] if self.assets.characters else None
            glPushMatrix()
            glTranslatef(pos[0], pos[1], pos[2])
            # 人物是一张平面卡片：相机抬高后必须跟着补一个 -pitch，
            # 否则会被看成一张斜躺着的纸片。旋转轴也在这个"面向镜头"的坐标系里。
            glRotatef(-self.pitch, 1.0, 0.0, 0.0)
            glScalef(item_scale, item_scale, item_scale)
            if card and card["tex"]:
                self.assets.draw_character(i, self.char_rot)
            else:
                # 素材缺失时退回原来的小物件，别让盒子开出个空
                glRotatef(self.char_rot, 0, 1, 0)
                glDisable(GL_CULL_FACE)
                glCallList(self.assets.item_lists[i])
                glEnable(GL_CULL_FACE)
            glPopMatrix()

        # 粒子
        b = self.bursts[i]
        if b.active:
            b.draw()

    def _capture_background(self, w, h):
        """把已经画好的背景抓进 blur_tex。

        窗口的默认帧缓冲是多采样的，直接 glReadPixels 会报 INVALID_OPERATION
        （离屏预览用的是单采样 FBO，所以这个问题只在真窗口里暴露）。正确做法
        是用 blit 把它解析(resolve)到一张单采样纹理，再拿这张纹理当模糊源。
        """
        cur = int(glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING))
        if self._blur_size != (w, h) or not self.resolve_fbo:
            glBindTexture(GL_TEXTURE_2D, self.blur_tex)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA,
                         GL_UNSIGNED_BYTE, None)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
            if not self.resolve_fbo:
                self.resolve_fbo = int(glGenFramebuffers(1))
            glBindFramebuffer(GL_FRAMEBUFFER, self.resolve_fbo)
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                                   GL_TEXTURE_2D, self.blur_tex, 0)
            glBindFramebuffer(GL_FRAMEBUFFER, cur)
            self._blur_size = (w, h)

        glBindFramebuffer(GL_READ_FRAMEBUFFER, cur)
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, self.resolve_fbo)
        # 窗口的帧缓冲可能是 sRGB，直接 blit 会把已经编码好的颜色再编码一次，
        # 抓出来的背景会发亮发蓝。临时关掉它，做一次纯拷贝。
        srgb_on = False
        try:
            srgb_on = bool(glIsEnabled(GL_FRAMEBUFFER_SRGB))
            if srgb_on:
                glDisable(GL_FRAMEBUFFER_SRGB)
        except Exception:
            srgb_on = False
        glBlitFramebuffer(0, 0, w, h, 0, 0, w, h, GL_COLOR_BUFFER_BIT, GL_NEAREST)
        if srgb_on:
            glEnable(GL_FRAMEBUFFER_SRGB)
        glBindFramebuffer(GL_FRAMEBUFFER, cur)

    def _blur_background(self, strength):
        """把已经画好的背景抓成纹理，再用多个偏移采样叠出模糊，然后压暗。"""
        if not self.blur_ok:
            return
        w = max(1, self.width)
        h = max(1, self.height)
        try:
            self._capture_background(w, h)
        except Exception:
            # 极老的驱动可能没有 framebuffer_blit，退回直接读回（单采样下可用）。
            try:
                glPixelStorei(GL_PACK_ALIGNMENT, 1)
                raw = glReadPixels(0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE)
                glBindTexture(GL_TEXTURE_2D, self.blur_tex)
                glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA,
                             GL_UNSIGNED_BYTE, raw)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            except Exception:
                # 连续失败几次就彻底关掉虚化，免得每帧都抛一次、白费开销。
                self._blur_fail += 1
                if self._blur_fail >= 3:
                    self.blur_ok = False
                return

        # 降采样再放大：把背景缩到 1/5 分辨率（丢掉细节），双线性放大回去，
        # 就得到干净柔和的虚化。比多次偏移叠加稳定——叠加会一点点累积模糊和
        # 亮度，跑几秒就糊成一团亮雾。
        sw = max(8, int(round(w / 6.5)))
        sh = max(8, int(round(h / 6.5)))
        self._ensure_small(sw, sh)
        cur = int(glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING))

        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        glOrtho(0, 1, 0, 1, -1, 1)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_LIGHTING)
        glDisable(GL_CULL_FACE)
        glDisable(GL_BLEND)
        glEnable(GL_TEXTURE_2D)
        glDepthMask(GL_FALSE)

        def quad():
            glBegin(GL_QUADS)
            glTexCoord2f(0, 0); glVertex3f(0, 0, 0)
            glTexCoord2f(1, 0); glVertex3f(1, 0, 0)
            glTexCoord2f(1, 1); glVertex3f(1, 1, 0)
            glTexCoord2f(0, 1); glVertex3f(0, 1, 0)
            glEnd()

        # 1) 全尺寸背景 → 小纹理
        glBindFramebuffer(GL_FRAMEBUFFER, self.small_fbo)
        glViewport(0, 0, sw, sh)
        glBindTexture(GL_TEXTURE_2D, self.blur_tex)
        glColor4f(1, 1, 1, 1.0)
        quad()

        # 2) 小纹理 → 全屏（双线性放大 = 柔和虚化，淡入用 strength 控制）
        glBindFramebuffer(GL_FRAMEBUFFER, cur)
        glViewport(0, 0, w, h)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glBindTexture(GL_TEXTURE_2D, self.small_tex)
        glColor4f(1, 1, 1, min(1.0, max(0.0, strength)))
        quad()

        # 3) 压暗，让居中礼物更突出
        glDisable(GL_TEXTURE_2D)
        glColor4f(0.01, 0.02, 0.05, 0.30 * strength)
        glBegin(GL_QUADS)
        glVertex3f(0, 0, 0); glVertex3f(1, 0, 0)
        glVertex3f(1, 1, 0); glVertex3f(0, 1, 0)
        glEnd()

        glDepthMask(GL_TRUE)
        glDisable(GL_BLEND)
        glDisable(GL_TEXTURE_2D)
        glPopMatrix()
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_LIGHTING)
        glEnable(GL_CULL_FACE)

    def _ensure_small(self, sw, sh):
        """虚化用的小尺寸纹理与它的 FBO。"""
        if self.small_fbo and self._small_size == (sw, sh):
            return
        if not self.small_tex:
            self.small_tex = int(glGenTextures(1))
        glBindTexture(GL_TEXTURE_2D, self.small_tex)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, sw, sh, 0, GL_RGBA,
                     GL_UNSIGNED_BYTE, None)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        if not self.small_fbo:
            self.small_fbo = int(glGenFramebuffers(1))
        cur = int(glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING))
        glBindFramebuffer(GL_FRAMEBUFFER, self.small_fbo)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                               GL_TEXTURE_2D, self.small_tex, 0)
        glBindFramebuffer(GL_FRAMEBUFFER, cur)
        self._small_size = (sw, sh)

    # ---- 镜头小窗 ----
    def _upload_camera(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        glBindTexture(GL_TEXTURE_2D, self.cam_tex)
        if (w, h) != (self.cam_w, self.cam_h):
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, w, h, 0, GL_RGB,
                         GL_UNSIGNED_BYTE, rgb.tobytes())
            self.cam_w, self.cam_h = w, h
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        else:
            glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, w, h, GL_RGB,
                            GL_UNSIGNED_BYTE, rgb.tobytes())

    def _draw_camera_preview(self, w, h):
        if self.cam_w == 0:
            return
        pw = 236
        ph = int(pw * self.cam_h / max(1, self.cam_w))
        margin = 16
        x0 = w - pw - margin
        y0 = margin

        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        glOrtho(0, w, 0, h, -1, 1)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_LIGHTING)
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, self.cam_tex)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glColor4f(1, 1, 1, 0.94)
        # 相机画面上下是反的（OpenGL 顶在上），这里 t 轴翻转过来
        glBegin(GL_QUADS)
        glTexCoord2f(0, 1); glVertex2f(x0, y0)
        glTexCoord2f(1, 1); glVertex2f(x0 + pw, y0)
        glTexCoord2f(1, 0); glVertex2f(x0 + pw, y0 + ph)
        glTexCoord2f(0, 0); glVertex2f(x0, y0 + ph)
        glEnd()
        # 细边框
        glDisable(GL_TEXTURE_2D)
        glDisable(GL_BLEND)
        glColor4f(1, 1, 1, 0.35)
        glLineWidth(1.0)
        glBegin(GL_LINE_LOOP)
        glVertex2f(x0, y0); glVertex2f(x0 + pw, y0)
        glVertex2f(x0 + pw, y0 + ph); glVertex2f(x0, y0 + ph)
        glEnd()
        glPopMatrix()
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_LIGHTING)

    @staticmethod
    def _to_gl(mat33):
        m = np.eye(4, dtype=np.float32)
        m[:3, :3] = mat33
        return m.T.flatten()
