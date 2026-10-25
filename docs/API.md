# 脚本 API

## 对象组件

```python
class Script(Behaviour):
    def start(self):
        self.elapsed = 0.0

    def update(self, dt):
        self.elapsed += dt
        self.object.rotation_euler.z += dt
```

引擎注入 `Behaviour` 和 `bpy`。回调：`awake()`、`start()`、`fixed_update(dt)`、`update(dt)`、`late_update(dt)`、`stop()`；碰撞／触发回调为 `on_collision_enter(other)`、`on_collision_exit(other)`、`on_trigger_enter(other)`、`on_trigger_exit(other)`。

## 全局脚本

`start(game)`、`update(game, dt)`、`stop(game)` 控制整个游戏；`game.state` 保存当前运行的共享状态，不是持久化存档。

## 常用运行时方法

| 方法 | 用途 |
| --- | --- |
| `game.find(name)` | 当前场景内按名字查找，未找到抛出KeyError |
| `game.log(message)` | 显示提示 |
| `game.get_key(key)` | 当前是否按住，如W、LEFT_SHIFT |
| `game.get_key_down(key)` | 本次更新是否刚按下 |
| `game.get_key_up(key)` | 本次更新是否刚松开 |
| `game.move_character(obj, direction, speed, jump=False, jump_speed=7)` | 控制指定玩家；方向Vector为局部移动输入 |
| `game.teleport(obj, position)` | 将模型或名称指定的对象移到世界位置 |
| `game.spawn(model_name, location=None)` | 复制当前场景中的一个模型，返回新对象；不是整套层级预制体复制器 |
| `game.destroy(obj)` | 本次运行隐藏／禁用对象，不能销毁玩家或游戏镜头 |
| `game.collect(obj)` | 收集并累计分数，重复调用不重复计分 |

组件使用 `controls_player = True` 接管玩家输入。`dt` 为秒。详细行为以 `blendplay/__init__.py` 中 Runtime 实现为准；底层 bpy API 也可直接使用，因此只应运行可信工程。
