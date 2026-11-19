# -*- coding: utf-8 -*-
"""把用户提供的五个抠图角色导入 assets/，顺带裁掉透明边、按统一高度缩好。

用法：
  py -3.12 tools_import_chars.py                # 用默认素材目录
  py -3.12 tools_import_chars.py <素材目录>

角色原图四周留了很多透明边，直接当卡片贴会因为"留白比例不同"导致
每个人看起来高矮不一。这里统一裁到不透明区域（留一点边），所以运行时
按"可见高度"缩放就够，不用给每个人单独调参。
"""
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
DEFAULT_SRC = Path(r"C:/Users/21254/Desktop/抠图角色素材")
OUT_MAX_SIDE = 760
PAD = 6

NAMES = ["角色1_手势", "角色2_大笑", "角色3_天使", "角色4_跳跃", "角色5_功夫"]


def crop_alpha(img):
    a = img[:, :, 3]
    ys, xs = np.where(a > 8)
    if len(xs) == 0:
        return img
    h, w = img.shape[:2]
    x0, x1 = max(0, xs.min() - PAD), min(w, xs.max() + 1 + PAD)
    y0, y1 = max(0, ys.min() - PAD), min(h, ys.max() + 1 + PAD)
    return img[y0:y1, x0:x1]


def kill_white_fringe(img, opaque=250):
    """去掉抠图边缘那圈白边。

    这批素材是从白底上抠的，半透明边缘像素的 RGB 里混着白色（a=71 的地方
    颜色还是 236,226,177 这种发白的值）。它直接贴到深色背景上就是一道白边，
    缩放时还会继续把白色渗进里层。

    做法是标准的"颜色扩散"：把每个半透明/透明像素的颜色换成离它最近的那个
    全不透明像素的颜色，alpha 原样不动。这样边缘合成出来是"人物色 × 透明度"，
    白边消失，同时保留抗锯齿的柔和过渡（不去动 alpha，就不会把边缘啃出锯齿）。
    """
    a = img[:, :, 3]
    solid = (a >= opaque).astype(np.uint8)
    if solid.all() or not solid.any():
        return img
    holes = (1 - solid).astype(np.uint8)
    _, labels = cv2.distanceTransformWithLabels(
        holes, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    # 每个零像素（也就是不透明像素）自己带一个 label，记下它的坐标当颜色源
    ys, xs = np.where(holes == 0)
    src = np.zeros((int(labels.max()) + 1, 2), np.int32)
    src[labels[ys, xs]] = np.stack([ys, xs], axis=1)
    nearest = src[labels]
    out = img.copy()
    out[:, :, :3] = img[nearest[:, :, 0], nearest[:, :, 1], :3]
    return out


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    if not src.is_dir():
        raise SystemExit(f"素材目录不存在：{src}")
    out_dir = HERE / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, name in enumerate(NAMES, start=1):
        p = src / f"{name}.png"
        if not p.exists():
            raise SystemExit(f"缺少素材：{p}")
        img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if img is None or img.shape[2] != 4:
            raise SystemExit(f"{p.name} 不是带透明通道的 PNG")
        img = kill_white_fringe(img)
        img = crop_alpha(img)
        h, w = img.shape[:2]
        k = OUT_MAX_SIDE / max(h, w)
        if k < 1.0:
            img = cv2.resize(img, (max(1, round(w * k)), max(1, round(h * k))),
                             interpolation=cv2.INTER_AREA)
        out = out_dir / f"gift_char_{i}.png"
        ok, buf = cv2.imencode(".png", img)
        if not ok:
            raise SystemExit("PNG 编码失败")
        buf.tofile(str(out))
        print(f"{p.name} -> {out.name}  {img.shape[1]}x{img.shape[0]}  "
              f"{out.stat().st_size / 1024:.0f}KB")

    wav_src = src / "laugh.wav"
    if wav_src.exists():
        wav_out = out_dir / "laugh.wav"
        wav_out.write_bytes(wav_src.read_bytes())
        print(f"laugh.wav -> assets/laugh.wav  {wav_out.stat().st_size / 1024:.0f}KB")
    else:
        print("没找到 laugh.wav，跳过音频")


if __name__ == "__main__":
    main()
