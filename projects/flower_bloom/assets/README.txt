花帧序列不随仓库分发，这里应该放：

    rose_frames.npz     120 帧玫瑰延时序列（约 19.5MB）

它由 tools/extract_rose_frames.py 从一段延时视频抽取，源视频不在仓库内。
缺失时 flower_app.py 会自动退化为程序化占位花型并在控制台提示，其余三个应用不受影响。

用自备视频生成：

    set ROSE_VIDEO=D:\path\to\rose.mp4
    py -3.12 tools/extract_rose_frames.py

裁剪框 CROP、取帧区间 RATIO_START/RATIO_END、帧数 FRAME_COUNT 都在脚本顶部，
换视频时按画面比例调整。
