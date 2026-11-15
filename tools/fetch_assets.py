# -*- coding: utf-8 -*-
"""一次性素材获取：下载手部模型，并检查花帧序列是否就位。

    py -3.12 tools/fetch_assets.py           # 缺什么补什么
    py -3.12 tools/fetch_assets.py --force   # 强制重新下载模型

只用标准库，所以在 pip install 之前也能跑通。

为什么仓库不收录这些文件
  hand_landmarker.task  7.5MB，MediaPipe 官方模型，随手能下载，没必要占仓库体积
  rose_frames.npz       19.5MB，从一段玫瑰延时视频抽的帧，源视频不在仓库里，
                        也不适合随仓库分发，需要自备视频重新生成
"""
import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "assets" / "hand_landmarker.task"
ROSE_PATH = ROOT / "projects" / "flower_bloom" / "assets" / "rose_frames.npz"

# MediaPipe 官方托管地址（float16 版，与训练时的输入一致）
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/1/hand_landmarker.task")
MODEL_SIZE = 7819105
MODEL_SHA256 = "fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1"


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest, expect_size=None):
    """带进度地把 url 下到 dest，先写 .part 再改名，避免中断留下半截文件。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    got = 0
    tty = sys.stdout.isatty()          # 重定向到文件时不刷回车，避免日志刷屏
    try:
        with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as out:
            total = expect_size or int(resp.headers.get("Content-Length") or 0)
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                out.write(chunk)
                got += len(chunk)
                if total:
                    pct = got * 100 / total
                    if tty:
                        bar = "#" * int(pct // 4)
                        sys.stdout.write(f"\r  下载中 {pct:5.1f}%  [{bar:<25}] "
                                         f"{got / 1048576:.1f}/{total / 1048576:.1f} MB")
                        sys.stdout.flush()
                    elif got % (2 << 20) < (1 << 16):   # 每约 2MB 报一次
                        print(f"  下载中 {pct:5.1f}%")
        if tty:
            print()
        tmp.replace(dest)
        return got
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def ensure_model(force=False):
    if MODEL_PATH.exists() and not force:
        size = MODEL_PATH.stat().st_size
        if size == MODEL_SIZE:
            print(f"[模型] 已存在，跳过（{size / 1048576:.1f} MB）")
            return True
        print(f"[模型] 大小不符（{size} 字节，应为 {MODEL_SIZE}），重新下载")

    print(f"[模型] 从 MediaPipe 官方地址下载\n       {MODEL_URL}")
    try:
        download(MODEL_URL, MODEL_PATH, MODEL_SIZE)
    except Exception as e:
        print(f"[模型] 下载失败：{type(e).__name__}: {e}")
        print("       可以手动下载后保存为 assets/hand_landmarker.task：")
        print(f"       {MODEL_URL}")
        return False

    digest = sha256_of(MODEL_PATH)
    if digest != MODEL_SHA256:
        print(f"[模型] 校验不符！\n       sha256={digest}\n       期望={MODEL_SHA256}")
        print("       文件可能不完整，删掉后重新运行本脚本。")
        return False
    print(f"[模型] 完成，sha256 校验通过（{MODEL_PATH.stat().st_size / 1048576:.1f} MB）")
    return True


def check_rose():
    if ROSE_PATH.exists():
        print(f"[花帧] 已存在（{ROSE_PATH.stat().st_size / 1048576:.1f} MB）")
        return True
    print("[花帧] 缺失：projects/flower_bloom/assets/rose_frames.npz")
    print("       这个文件从一段玫瑰延时视频抽取，源视频不在仓库里，无法自动下载。")
    print("       影响：只会让『花开』退化成程序化占位花型，其余三个应用不受影响。")
    print("       要还原真实玫瑰，自备一段花朵延时视频后执行：")
    print('           set ROSE_VIDEO=D:\\path\\to\\rose.mp4')
    print("           py -3.12 projects/flower_bloom/tools/extract_rose_frames.py")
    print("       裁剪框和取帧区间在脚本顶部，换视频时需要按画面比例改 CROP。")
    return False


def main():
    ap = argparse.ArgumentParser(description="下载/检查运行所需素材")
    ap.add_argument("--force", action="store_true", help="强制重新下载模型")
    args = ap.parse_args()

    print(f"项目根目录：{ROOT}\n")
    ok_model = ensure_model(args.force)
    print()
    ok_rose = check_rose()
    print()
    if ok_model:
        print("可以运行了。四个应用分别双击根目录的 启动*.bat。")
    else:
        print("模型未就位，应用会在启动时提示缺少文件。")
        return 1
    if not ok_rose:
        print("（花开将以占位花型运行，属预期行为）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
