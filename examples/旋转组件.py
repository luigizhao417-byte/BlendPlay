# SPDX-License-Identifier: GPL-3.0-or-later
# 普通物体的可执行示例：运行时缓慢旋转，停止后恢复。
class Script(Behaviour):
    def start(self):
        self.rotation_speed = 1.0

    def update(self, dt):
        self.object.rotation_euler.z += self.rotation_speed * dt
