# SPDX-License-Identifier: GPL-3.0-or-later
# 灯光：运行时亮度随时间缓慢变化。修改参数即可改变游戏画面。
import math

class Script(Behaviour):
    def start(self):
        if self.object.type != 'LIGHT':
            raise TypeError('灯光脚本必须关联灯光')
        self.base_energy = self.object.data.energy
        self.pulse = 0.30
        self.frequency = 1.5

    def update(self, dt):
        self.object.data.energy = self.base_energy * (1 + self.pulse * math.sin(self.game.time * self.frequency))
