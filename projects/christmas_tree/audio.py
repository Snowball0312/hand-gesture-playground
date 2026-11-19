# -*- coding: utf-8 -*-
"""开礼物时的音效（现在只有"大笑"那一个盒子有声音）。

只在**打开**的那一刻播一次，选中/聚焦时不出声——用户明确要求过这点。

优先用 Qt 的 QSoundEffect（跟着应用生命周期、能随时 stop）；如果这台机器
没有 QtMultimedia 插件或没有音频输出设备，退回 Windows 自带的 winsound。
两条路都失败就安静地跳过，绝不因为没声音把整个应用拖崩。
"""
from pathlib import Path


class GiftAudio:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self._sound = None
        self._tried = False
        self._fallback = False

    def _ensure(self):
        if self._tried:
            return self._sound
        self._tried = True
        if not self.path.exists():
            return None
        try:
            from PyQt6.QtCore import QUrl
            from PyQt6.QtMultimedia import QSoundEffect

            eff = QSoundEffect()
            eff.setSource(QUrl.fromLocalFile(str(self.path)))
            eff.setVolume(0.95)
            if not eff.source().isValid():
                raise RuntimeError("音频源无效")
            self._sound = eff
        except Exception:
            self._fallback = True
            self._sound = None
        return self._sound

    def preload(self):
        """启动时就把音频加载好。

        QSoundEffect 的 setSource 是异步解码的，第一次 play 时若还没 Ready，
        会有几十到几百毫秒的空等。放在启动时加载，开盒那一下就只剩"按下播放"。
        """
        self._ensure()

    def play(self):
        eff = self._ensure()
        if eff is not None:
            eff.stop()
            eff.play()
            return
        if not self._fallback:
            return
        try:
            import winsound

            winsound.PlaySound(str(self.path),
                               winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception:
            pass

    def stop(self):
        if self._sound is not None:
            try:
                self._sound.stop()
            except Exception:
                pass
            return
        if not self._fallback:
            return
        try:
            import winsound

            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass
