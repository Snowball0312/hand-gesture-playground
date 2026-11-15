# 花开交互 · 玫瑰帧序列版

## 目标
- 张开手掌 → 花朵缓慢盛开；握拳 → 花朵缓慢收拢；其他手势或手移出画面时保持当前状态。
- 花朵固定画面中央；不做发光、粒子、花瓣飘落等附加动效。
- 显示渲染目标节奏 60FPS，识别线程在后台独立运行。

## 文件
- `flower_app.py`        主循环、HUD、主入口；自动选择贴图渲染，素材缺失时回退占位花型
- `flower_engine.py`     目标状态驱动的开放度平滑过渡（控制开/合速度）
- `flower_detector.py`   检测器：gesture_core.HandTracker 的薄封装，沿用本项目参数（480x360 / 30fps / 不镜像）
- `flower_rules.py`      手势语义：五指张开=开花，握拳=合花（几何判定来自 gesture_core）
- `render_sprite.py`     贴图精灵渲染：按开放度在相邻玫瑰帧之间过渡
- `render_placeholder.py` 程序化占位花型（无素材时兜底）
- `assets/rose_frames.npz` 120 帧玫瑰延时序列（已裁掉手机状态栏与播放控件）
  —— 体积 19.5MB，**不随仓库分发**，需按下方「素材重新生成」自备视频生成
- `tools/extract_rose_frames.py` 一次性素材提取脚本，可重新生成 npz

## 素材缺失时的行为
`flower_app.py` 启动时会检查帧序列是否真的加载成功：缺失或为空则在控制台打印一行提示，
自动切换到 `render_placeholder.py` 的程序化花型，其余逻辑完全一致。
（只判断导入是否成功是不够的 —— `render_sprite` 在缺 npz 时导入不报错，只是帧列表为空。）

## 操作
- 张开手掌：开花
- 握拳：合花
- `ESC` 退出
- 手不在画面时不自动改变开放度

## 手感/速度调节
- 开/合速度在 `flower_engine.py`：`open_speed`、`close_speed`；越大越快、越小越慢，默认偏慢。
- 帧流畅度取决于 `assets/rose_frames.npz` 中的帧数；当前 120 帧，相邻帧做轻微柔化过渡。

## 素材重新生成
1. 准备新的延时摄影视频（黑/暗背景、画面稳定、无明显晃动）。
2. 运行：`py -3.12 tools/extract_rose_frames.py`；如需指定视频路径，先设置环境变量 `ROSE_VIDEO`。
3. 脚本内 `CROP` 是固定裁剪框，可按新视频位置调整；结尾 UI 帧通过 `RATIO_START/RATIO_END` 排除。
4. `FRAME_COUNT` 越大过渡越密；`SAVE_WIDTH` 控制素材保存分辨率。
