# -*- coding: utf-8 -*-
"""经纬度 ↔ 球面方向 ↔ 视图旋转 的换算。

gluSphere 的贴图约定（本机实测标定，不是猜的）：
  顶点方向 = ( sin(经度)·sinφ,  -cos(经度)·sinφ,  cosφ )
    φ = (90° - 纬度) 的弧度
  也就是说 **北极在 +Z 轴**，而非常见的 +Y 轴。这一点如果搞错，
  任何按经纬度摆放的物体都会跑到别的半球去。

标定方法（见 tools_calibrate_tex.py）：用 R=列号、G=行号的自编码贴图
渲染球体，读正面像素反推 s/t：
   正对 -X 时 u = 0.2471（理论 0.25）
   正对 +X 时 u = 0.7490（理论 0.75）
误差 1° 以内，且与“无旋转时北极正对镜头、欧洲在下方、亚洲在右方”
的渲染结果一致。

view_rot_to_face 只跟模型矩阵有关（摄像机在 +Z 看向原点，模型矩阵是
Rx(rot_x)·Ry(rot_y)），与贴图约定无关，单独验证过：rot=(18,-105) 时
正对方向确实是 (0.919, 0.309, -0.246)。
"""
import math


def latlon_to_dir(lat, lon):
    """(纬度, 经度) 度数 → 单位球面方向。北纬/东经为正。"""
    phi = math.radians(90.0 - lat)
    s = math.sin(phi)
    lam = math.radians(lon)
    return (math.sin(lam) * s, -math.cos(lam) * s, math.cos(phi))


def dir_to_latlon(d):
    """单位方向 → (纬度, 经度)，用于验证针到底钉在哪。"""
    x, y, z = d
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    x, y, z = x / n, y / n, z / n
    lat = math.degrees(math.asin(max(-1.0, min(1.0, z))))
    lon = math.degrees(math.atan2(x, -y))
    return lat, lon


def latlon_to_dir_grid(lats, lons):
    """latlon_to_dir 的向量化版本：(n_lat,) × (n_lon,) → (n_lat, n_lon, 3)。

    贴球面用的地图网格要走这条，逐点调用标量版本太慢。
    公式与 latlon_to_dir 完全一致：φ = 90° - 纬度，sinφ 就是 cos(纬度)。
    """
    import numpy as np
    lat = np.radians(np.asarray(lats, dtype=np.float64))[:, None]
    lon = np.radians(np.asarray(lons, dtype=np.float64))[None, :]
    s = np.cos(lat)
    x = np.sin(lon) * s
    y = -np.cos(lon) * s
    z = np.broadcast_to(np.sin(lat), x.shape)
    return np.stack([x, y, z], axis=-1)


def rotation_to_align(d):
    """返回 (angle, ax, ay, az)，使 +Z 轴转到方向 d。

    gluCylinder 沿 +Z 生成，所以“沿表面法线朝外立起来”就是让 +Z 对齐 d。
    轴取 z×d = (-dy, dx, 0)，角度取 acos(dz)。
    原来的代码把轴写成了 z×d 的相反数，导致针杆扎进地球内部。
    """
    x, y, z = d
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    x, y, z = x / n, y / n, z / n
    angle = math.degrees(math.acos(max(-1.0, min(1.0, z))))
    ax, ay = -y, x
    k = math.hypot(ax, ay)
    if k < 1e-9:            # d 与 ±Z 重合，轴任取
        return angle, 1.0, 0.0, 0.0
    return angle, ax / k, ay / k, 0.0


def view_rot_to_face(d, pitch_limit=88.0):
    """返回 (rot_x, rot_y)，使方向 d 正对摄像机。

    摄像机在 +Z 看向原点，模型矩阵为 Rx(rot_x)·Ry(rot_y)，
    故正对屏幕的方向是 v = (-sin(ry)cos(rx), sin(rx), cos(ry)cos(rx))，
    反解得 rx = asin(dy)，ry = atan2(-dx, dz)。
    """
    x, y, z = d
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    x, y, z = x / n, y / n, z / n
    rx = math.degrees(math.asin(max(-1.0, min(1.0, y))))
    rx = max(-pitch_limit, min(pitch_limit, rx))
    ry = math.degrees(math.atan2(-x, z))
    return rx, ry


# 中国的地理中心（甘肃—四川一带），用来对准初始视角
CHINA_LAT, CHINA_LON = 34.5, 103.0
# 大头针默认钉在北京
PIN_LAT, PIN_LON = 39.9, 116.4
