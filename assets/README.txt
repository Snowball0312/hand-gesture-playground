模型文件不随仓库分发，这里应该放：

    hand_landmarker.task      MediaPipe Hand Landmarker（float16，7.5MB）

获取方式（在项目根目录执行，会下载并校验 sha256）：

    py -3.12 tools/fetch_assets.py

四个应用共用这一个模型。如果启动时看到

    [HandTracker] 缺少手部模型文件：.../assets/hand_landmarker.task

就是这个文件还没下载。
