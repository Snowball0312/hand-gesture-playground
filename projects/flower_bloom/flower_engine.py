# -*- coding: utf-8 -*-
"""开放度状态机：目标状态驱动，缓慢平滑地向目标靠近。"""


class BloomEngine:
    def __init__(self, open_speed=0.0050, close_speed=0.0040, snap=0.0015):
        self.openness = 0.0
        self.target = 0.0
        self.open_speed = open_speed
        self.close_speed = close_speed
        self.snap = snap

    def open(self):
        self.target = 1.0

    def close(self):
        self.target = 0.0

    def update(self):
        diff = self.target - self.openness
        if abs(diff) < self.snap:
            self.openness = self.target
            return self.openness
        speed = self.open_speed if diff > 0 else self.close_speed
        self.openness += diff * speed
        return self.openness
