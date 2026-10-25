# SPDX-License-Identifier: GPL-3.0-or-later
# 游戏镜头：使用公开 camera_target() 实现三种真实视角。

class Script(Behaviour):
    controls_camera = True
    def start(self):
        if self.object.type != 'CAMERA':
            raise TypeError('镜头脚本必须关联摄像机')
        self.follow_speed = 12.0
        self.focal_length = self.object.data.lens
        self.game.set_camera(self.object, automatic=False)
        self.object.data.lens = self.focal_length

    def late_update(self, dt):
        game = self.game
        target, rotation, hide_player = game.camera_target()
        game.set_character_visible(not hide_player)
        blend = min(1.0, dt * self.follow_speed)
        self.object.location += (target - self.object.location) * blend
        self.object.rotation_euler = rotation
