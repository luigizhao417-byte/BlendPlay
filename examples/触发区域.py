# SPDX-License-Identifier: GPL-3.0-or-later
# 触发区域：玩家进入时记录次数和位置。
class Script(Behaviour):
    def on_trigger_enter(self, other):
        if other == self.game.player:
            key = self.object.name + '触发次数'
            self.game.state[key] = self.game.state.get(key, 0) + 1
            self.game.log(self.object.name + ' 已触发')
