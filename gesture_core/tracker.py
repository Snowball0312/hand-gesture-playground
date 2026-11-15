# -*- coding: utf-8 -*-
"""唯一的手部检测线程：摄像头采集 + MediaPipe 推理。

所有项目共用这一份实现。回调只交出原始 landmarks 和预览帧，
手势语义交给 rules.py，业务动作交给各前端。

    def on_hands(hands, frame):
        for lm in hands:            # lm 是 21 个归一化关键点
            ...

    det = HandTracker(model_path, on_hands)
    det.start()                     # 后台守护线程
    ...
    det.stop(); det.join(2000)

为什么模型用字节缓冲加载：Windows 中文路径下 mediapipe 原生层
用 fopen 打不开文件，直接传路径会失败。
"""
import threading
import time
from pathlib import Path

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

# 21 点骨架连线，仅用于预览画面
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20), (0, 17),
]


MODEL_MISSING_HINT = """\
[HandTracker] 缺少手部模型文件：{path}

  在项目根目录执行一次即可自动下载（约 7.5MB）：
      py -3.12 tools/fetch_assets.py
"""


def ensure_model(model_path):
    """模型缺失时直接给出可操作的提示，而不是让线程里抛一堆堆栈。

    仓库不收录模型二进制，所以第一次运行前必须先取一次素材。
    """
    p = Path(model_path)
    if not p.exists():
        raise SystemExit(MODEL_MISSING_HINT.format(path=p))
    return p


def draw_skeleton(frame, lm, color=(60, 220, 60)):
    """在 BGR 帧上画 21 点骨架，原地修改。"""
    h, w = frame.shape[:2]
    for a, b in HAND_CONNECTIONS:
        cv2.line(frame,
                 (int(lm[a].x * w), int(lm[a].y * h)),
                 (int(lm[b].x * w), int(lm[b].y * h)), color, 2)
    for p in lm:
        cv2.circle(frame, (int(p.x * w), int(p.y * h)), 3, (255, 200, 0), -1)


class HandTracker(threading.Thread):
    """后台检测线程。

    参数
    ----
    model_path     : hand_landmarker.task 路径（支持中文路径）
    on_hands       : callback(hands, frame)，hands 为 landmarks 列表，frame 为 BGR
    num_hands      : 1 或 2，只要单手设 1 更省 CPU
    cam_size       : (宽, 高)，卡顿可降到 (640, 480)
    infer_interval : 两次推理的最小间隔（秒），用来控制 CPU 占用
    mirror         : 是否自拍镜像。开着才符合“手往右、光标往右”的直觉
    draw           : 是否在回调帧上画骨架，不需要预览就关掉省 CPU
    cam_fps        : 向摄像头请求的帧率，None 表示不设置

    属性
    ----
    last_infer_ms  : 最近一次推理耗时（毫秒）
    fps            : 处理帧率的指数平滑值
    """

    def __init__(self, model_path, on_hands, num_hands=1, cam_size=(640, 480),
                 infer_interval=0.016, mirror=True, draw=False, cam_fps=None,
                 cam_index=0, min_detection_confidence=0.5,
                 min_tracking_confidence=0.5, max_read_failures=120):
        super().__init__(daemon=True)
        self.model_path = str(ensure_model(model_path))
        self.on_hands = on_hands
        self.num_hands = num_hands
        self.cam_w, self.cam_h = cam_size
        self.infer_interval = infer_interval
        self.mirror = mirror
        self.draw = draw
        self.cam_fps = cam_fps
        self.cam_index = cam_index
        self.min_detection_confidence = min_detection_confidence
        self.min_tracking_confidence = min_tracking_confidence
        self.max_read_failures = max_read_failures

        self.last_infer_ms = 0.0
        self.fps = 0.0
        self.error = None            # 启动或运行失败时记录原因，供前端提示
        # 注意：名称不能叫 _stop。threading.Thread 内部有 _stop() 方法，
        # 用实例属性覆盖它会让线程结束后的 join() 抛 TypeError。
        self._stop_event = threading.Event()
        self._det = None
        self._cap = None
        self._last_infer = 0.0

    def stop(self):
        self._stop_event.set()

    # ---- 内部 ----
    def _build_landmarker(self):
        try:
            base = mp_python.BaseOptions(
                model_asset_buffer=Path(self.model_path).read_bytes())
        except OSError:
            base = mp_python.BaseOptions(model_asset_path=self.model_path)
        opts = mp_vision.HandLandmarkerOptions(
            base_options=base,
            num_hands=self.num_hands,
            running_mode=mp_vision.RunningMode.VIDEO,
            min_hand_detection_confidence=self.min_detection_confidence,
            min_tracking_confidence=self.min_tracking_confidence,
        )
        return mp_vision.HandLandmarker.create_from_options(opts)

    def _open_camera(self):
        cap = cv2.VideoCapture(self.cam_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(self.cam_index)
        if not cap.isOpened():
            cap.release()
            return None
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cam_w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cam_h)
        if self.cam_fps:
            cap.set(cv2.CAP_PROP_FPS, self.cam_fps)
        return cap

    def run(self):
        try:
            self._det = self._build_landmarker()
        except Exception as e:                      # 模型缺失/损坏
            self.error = f"模型加载失败：{e}"
            print(f"[HandTracker] {self.error}")
            return

        self._cap = self._open_camera()
        if self._cap is None:
            self.error = "摄像头打不开，可能被其它程序占用"
            print(f"[HandTracker] {self.error}")
            self._det.close()
            self._det = None
            return

        prev_t = time.time()
        fails = 0

        while not self._stop_event.is_set():
            ok, frame = self._cap.read()
            if not ok:
                fails += 1
                if fails >= self.max_read_failures:
                    self.error = "摄像头连续读取失败，已停止"
                    print(f"[HandTracker] {self.error}")
                    break
                time.sleep(0.002)
                continue
            fails = 0

            now = time.monotonic()
            if now - self._last_infer < self.infer_interval:
                time.sleep(0.001)
                continue
            self._last_infer = now

            if self.mirror:
                frame = cv2.flip(frame, 1)

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            t0 = time.perf_counter()
            res = self._det.detect_for_video(mp_img, int(now * 1000))
            self.last_infer_ms = (time.perf_counter() - t0) * 1000

            hands = res.hand_landmarks if res.hand_landmarks else []
            if self.draw:
                for lm in hands:
                    draw_skeleton(frame, lm)

            t = time.time()
            dt = t - prev_t
            prev_t = t
            if dt > 0:
                self.fps = 0.9 * self.fps + 0.1 * (1.0 / dt)

            if self.on_hands:
                self.on_hands(hands, frame)

        self.release()

    def release(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        if self._det is not None:
            self._det.close()
            self._det = None
