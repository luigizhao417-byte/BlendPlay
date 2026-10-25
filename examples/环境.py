# SPDX-License-Identifier: GPL-3.0-or-later
# 独立环境组件：运行时改变世界背景颜色。
import math

class Script(Behaviour):
    def start(self):
        self.world = self.game.scene.world
        if self.world is None:
            raise ValueError('场景尚未设置世界环境')
        self.original = tuple(self.world.color)

    def update(self, dt):
        pulse = 0.06 * (1 + math.sin(self.game.time * 1.2))
        self.world.color = (self.original[0] + pulse, self.original[1] + pulse, self.original[2] + pulse)
