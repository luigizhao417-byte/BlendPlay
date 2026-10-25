# SPDX-License-Identifier: GPL-3.0-or-later
# 玩家控制器。修改这里的速度、冲刺倍率和跳跃速度会改变游戏行为。
from mathutils import Vector

class Script(Behaviour):
    controls_player = True

    def start(self):
        self.speed_multiplier = 1.0
        self.sprint_multiplier = 1.6
        self.game.log('WASD 移动 · Shift 冲刺 · 空格跳跃')

    def update(self, dt):
        game = self.game
        direction = Vector((
            int(game.get_key('D')) - int(game.get_key('A')),
            int(game.get_key('W')) - int(game.get_key('S')),
            0,
        ))
        speed = game.scene.bp.speed * self.speed_multiplier
        if game.get_key('LEFT_SHIFT') or game.get_key('RIGHT_SHIFT'):
            speed *= self.sprint_multiplier
        game.move_character(
            self.object, direction, speed,
            jump=game.get_key_down('SPACE'),
            jump_speed=game.scene.bp.jump,
        )

    def on_trigger_enter(self, other):
        if other.bp.role == 'COIN':
            self.game.log('碰到金币：' + other.name)
