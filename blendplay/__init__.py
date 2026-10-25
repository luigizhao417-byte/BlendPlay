# SPDX-License-Identifier: GPL-3.0-or-later
bl_info = {'name': 'BlendPlay 游戏运行器', 'author': 'BlendPlay contributors (AI-assisted)', 'version': (2, 5, 1), 'blender': (5, 1, 0), 'category': '3D View'}
import bpy, time, math, traceback, blf
from mathutils import Vector, Quaternion
from pathlib import Path
from bpy.app.handlers import persistent
from bpy_extras.io_utils import ImportHelper, ExportHelper
from bpy.props import PointerProperty, FloatProperty, FloatVectorProperty, EnumProperty, BoolProperty, StringProperty, CollectionProperty, IntProperty
from .character import build_character, action_curves

ACTIVE = None

def bounds(obj):
    pts = [obj.matrix_world @ Vector(v) for v in obj.bound_box]
    return Vector(tuple(min(p[i] for p in pts) for i in range(3))), Vector(tuple(max(p[i] for p in pts) for i in range(3)))

def overlaps(a, b):
    return all(a[0][i] < b[1][i] and a[1][i] > b[0][i] for i in range(3))

class BPLink(bpy.types.PropertyGroup):
    text: PointerProperty(name='代码文件', type=bpy.types.Text)
    enabled: BoolProperty(name='启用', default=True)

def file_selected(self, context):
    if context.window and 0 <= self.file_index < len(bpy.data.texts):
        text = bpy.data.texts[self.file_index]
        show_code(context.window, text)

class BPSettings(bpy.types.PropertyGroup):
    file_index: IntProperty(default=0, update=file_selected)
    files: CollectionProperty(type=BPLink)
    follow_selection: BoolProperty(name='选中模型时显示它的代码', default=True)
    perspective: EnumProperty(name='游戏视角', items=[('THIRD', '第三人称', '跟随角色的镜头'), ('FIRST', '第一人称', '角色眼部镜头'), ('MAP', '斜角俯视', '斜上方跟随角色')], default='THIRD')
    distance: FloatProperty(name='第三人称距离', default=9, min=1, max=30)
    map_height: FloatProperty(name='斜角距离', default=14, min=3, max=100)
    map_scale: FloatProperty(name='画面范围', default=20, min=4, max=200)
    map_angle: FloatProperty(name='俯视角度', default=math.radians(38), min=math.radians(15), max=math.radians(75), subtype='ANGLE', unit='ROTATION')
    first_fov: FloatProperty(name='第一人称视野角度', default=85, min=50, max=110, description='增大角度可以看到更多周围环境')
    head_bob: BoolProperty(name='第一人称步伐晃动', default=True)
    head_bob_strength: FloatProperty(name='步伐晃动强度', default=1.0, min=0, max=3)
    sensitivity: FloatProperty(name='视角灵敏度', default=.004, min=.001, max=.02)
    error: StringProperty(name='最近错误', default='')
    script: PointerProperty(name='游戏脚本', type=bpy.types.Text)
    fullscreen: BoolProperty(name='运行时全屏', default=True)
    player: PointerProperty(name='角色控制器', type=bpy.types.Object)
    character: PointerProperty(name='角色模型（骨骼）', type=bpy.types.Object, poll=lambda self, obj: obj.type == 'ARMATURE')
    idle_action: PointerProperty(name='待机动画', type=bpy.types.Action)
    walk_action: PointerProperty(name='走路动画', type=bpy.types.Action)
    run_action: PointerProperty(name='奔跑动画', type=bpy.types.Action)
    jump_action: PointerProperty(name='跳跃动画', type=bpy.types.Action)
    mouse_look: EnumProperty(name='鼠标视角', items=[('DIRECT','直接移动鼠标','运行后鼠标直接控制镜头'),('RIGHT','按住右键','按住右键再移动鼠标')], default='DIRECT')
    camera_control: EnumProperty(name='镜头控制', items=[('PLAYER','玩家输入','鼠标视角始终由控制器驱动'),('SCRIPT','脚本控制','允许镜头脚本完全接管')], default='PLAYER')
    camera_source: EnumProperty(name='初始镜头', items=[('CAMERA','使用摄像机位置和旋转','在场景中调整摄像机来配置初始视角'),('SETTINGS','使用视角参数','由距离与斜角参数决定初始镜头')], default='CAMERA')
    speed: FloatProperty(name='移动速度', default=5, min=.1, max=100)
    jump: FloatProperty(name='跳跃速度', default=7, min=0, max=50)
    gravity: FloatProperty(name='重力', default=18, min=0, max=100)

class BPObject(bpy.types.PropertyGroup):
    scripts: CollectionProperty(type=BPLink)
    role: EnumProperty(name='游戏类型', items=[('NONE','普通物体',''), ('SOLID','碰撞体','轴对齐包围盒碰撞'), ('COIN','收集物','触碰后隐藏'), ('TRIGGER','触发区域','进入/退出触发回调')])
    invisible_in_game: BoolProperty(name='运行时不可见', description='保留碰撞或触发，但试玩时隐藏模型', default=False)

TEMPLATE = """# 全局环境代码：负责游戏开始、胜利条件和退出。
import bpy

def start(game):
    game.state['游戏已完成'] = False

def update(game, dt):
    if game.total > 0 and game.score >= game.total and not game.state['游戏已完成']:
        game.state['游戏已完成'] = True
        game.log('所有金币已收集，游戏完成！')

def stop(game):
    game.log('游戏已结束')
"""

def ensure_script(scene):
    if scene.bp.script is None:
        text = bpy.data.texts.new('游戏主脚本.py')
        text.write(TEMPLATE)
        text.use_fake_user = True
        scene.bp.script = text
    return scene.bp.script

COMPONENT_TEMPLATE = """# 普通物体的可执行示例：运行时缓慢旋转，停止后恢复。
class Script(Behaviour):
    def start(self):
        self.rotation_speed = 1.0

    def update(self, dt):
        self.object.rotation_euler.z += self.rotation_speed * dt
"""

PLAYER_TEMPLATE = """# 玩家控制器。修改这里的速度、冲刺倍率和跳跃速度会改变游戏行为。
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
"""

COIN_TEMPLATE = """# 金币旋转和收集行为。可修改旋转速度与收集后的提示。
class Script(Behaviour):
    handles_collection = True

    def start(self):
        self.rotation_speed = 2.0

    def update(self, dt):
        self.object.rotation_euler.z += self.rotation_speed * dt

    def on_trigger_enter(self, other):
        if other == self.game.player and self.game.collect(self.object):
            self.game.log('已收集 ' + self.object.name)
"""

CAMERA_TEMPLATE = """# 游戏镜头：使用公开 camera_target() 实现三种真实视角。

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
"""

CHARACTER_TEMPLATE = """# 角色动画控制器：读取实际移动速度，播放绑定的 Blender 动画。
class Script(Behaviour):
    def late_update(self, dt):
        self.game.animate_character(self.object, dt)
"""

LIGHT_TEMPLATE = """# 灯光：运行时亮度随时间缓慢变化。修改参数即可改变游戏画面。
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
"""

WORLD_TEMPLATE = """# 独立环境组件：运行时改变世界背景颜色。
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
"""

PLATFORM_TEMPLATE = """# 地面/平台行为。把移动距离改为非零数值即可水平往返移动。
import math

class Script(Behaviour):
    def start(self):
        self.origin = self.object.location.copy()
        self.move_distance = float(self.object.get('移动距离', 0.0))
        self.move_speed = 1.0

    def update(self, dt):
        self.object.location.x = self.origin.x + math.sin(self.game.time * self.move_speed) * self.move_distance

    def on_collision_enter(self, other):
        if other == self.game.player:
            self.game.state['最近碰撞物体'] = self.object.name
"""

TRIGGER_TEMPLATE = """# 触发区域：玩家进入时记录次数和位置。
class Script(Behaviour):
    def on_trigger_enter(self, other):
        if other == self.game.player:
            key = self.object.name + '触发次数'
            self.game.state[key] = self.game.state.get(key, 0) + 1
            self.game.log(self.object.name + ' 已触发')
"""

NPC_TEMPLATE = """# 非玩家角色：在出生点附近巡逻，保留关卡碰撞。
import math

class Script(Behaviour):
    def start(self):
        self.origin = self.object.location.copy()
        self.distance = float(self.object.get('巡逻距离', 1.0))
        self.speed = float(self.object.get('巡逻速度', 1.0))

    def update(self, dt):
        self.object.location.x = self.origin.x + math.sin(self.game.time * self.speed) * self.distance
"""

def template_for(obj):
    if obj.type == 'ARMATURE': return CHARACTER_TEMPLATE
    if obj.type == 'CAMERA': return CAMERA_TEMPLATE
    if obj.type == 'LIGHT': return LIGHT_TEMPLATE
    if any(scene.bp.player == obj for scene in bpy.data.scenes): return PLAYER_TEMPLATE
    if obj.get('游戏角色') == 'NPC': return NPC_TEMPLATE
    if obj.bp.role == 'COIN': return COIN_TEMPLATE
    if obj.bp.role == 'TRIGGER': return TRIGGER_TEMPLATE
    if obj.bp.role == 'SOLID': return PLATFORM_TEMPLATE
    return COMPONENT_TEMPLATE

class Behaviour:
    def awake(self): pass
    def start(self): pass
    def fixed_update(self, dt): pass
    def update(self, dt): pass
    def late_update(self, dt): pass
    def on_collision_enter(self, other): pass
    def on_collision_exit(self, other): pass
    def on_trigger_enter(self, other): pass
    def on_trigger_exit(self, other): pass
    def stop(self): pass

def object_script(obj):
    links = obj.bp.scripts
    for link in links:
        if link.text:
            return link.text
    text = bpy.data.texts.new(obj.name + '.py')
    text.write(template_for(obj))
    text.use_fake_user = True
    links.add().text = text
    return text

def show_code(window, text, force=False):
    for area in window.screen.areas:
        if area.type == 'TEXT_EDITOR':
            previous = area.spaces.active.text
            area.spaces.active.text = text
            if text is not None and (previous != text or force):
                text.cursor_set(0, character=0)
                region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                if region:
                    with bpy.context.temp_override(window=window, area=area, region=region):
                        if bpy.ops.text.jump.poll(): bpy.ops.text.jump(line=1)
            area.tag_redraw()

SELECTIONS = {}
def selection_sync():
    if ACTIVE is None:
        for window in bpy.context.window_manager.windows:
            if not window.workspace.name.startswith('游戏 IDE'): continue
            if not window.scene.bp.follow_selection: continue
            obj = window.view_layer.objects.active
            key = (window.scene.as_pointer(), obj.as_pointer() if obj else 0)
            if SELECTIONS.get(window.as_pointer()) != key:
                SELECTIONS[window.as_pointer()] = key
                owner = obj
                text = None
                visited = set()
                while owner is not None and owner not in visited and text is None:
                    visited.add(owner)
                    text = next((link.text for link in owner.bp.scripts if link.text), None)
                    owner = window.scene.bp.player if owner == window.scene.bp.character and owner != window.scene.bp.player else owner.parent
                if obj is None: text = window.scene.bp.script
                window.scene.bp.file_index = list(bpy.data.texts).index(text) if text else -1
                show_code(window, text, force=True)
    return .2

class Runtime:
    def __init__(self, scene):
        self.state = {}
        self.keys = set()
        self.pressed = set()
        self.released = set()
        self.hooks = {}
        self.components = []
        self.contacts = set()
        self.triggers = set()
        self.fixed_accumulator = 0
        self.time = 0
        self.move_request = None
        self.has_controller = False
        self.coin_contacts = set()
        self.spawned = []
        self.disabled = set()
        self.scene = scene
        self.player = scene.bp.player
        self.objects = list(scene.objects)
        self.saved = [(o, o.matrix_world.copy(), o.hide_get()) for o in self.objects]
        self.start = self.player.location.copy()
        self.velocity = 0
        self.grounded = False
        self.score = 0
        self.collected = set()
        self.total = sum(o.bp.role == 'COIN' for o in self.objects)
        self.camera = scene.camera
        self.auto_camera = True
        self.saved_camera = scene.camera
        self.saved_lights = [(o.data, o.data.energy, tuple(o.data.color)) for o in self.objects if o.type == 'LIGHT']
        self.saved_cameras = [(o.data, o.data.lens, o.data.clip_start, o.data.clip_end, o.data.type, o.data.ortho_scale) for o in self.objects if o.type == 'CAMERA']
        self.saved_world = (scene.world, tuple(scene.world.color)) if scene.world else None
        self.camera_lenses = {obj: obj.data.lens for obj in self.objects if obj.type == 'CAMERA'}
        self.character = scene.bp.character
        self.saved_pose = [(bone, bone.matrix_basis.copy())
                           for bone in self.character.pose.bones] if self.character and self.character.type == 'ARMATURE' else []
        self.saved_character_action = self.character.animation_data.action if self.character and self.character.animation_data else None
        self.saved_character_slot = self.character.animation_data.action_slot if self.character and self.character.animation_data and hasattr(self.character.animation_data, 'action_slot') else None
        self.animation_phase = 0.0
        self.bob_phase = 0.0
        self.bob_weight = 0.0
        self.animation_mode = 'IDLE'
        self.animation_curves = {}
        self.movement_velocity = Vector((0, 0, 0))
        self.animation_updated = False
        self.offset = self.camera.location - self.player.location if self.camera else None
        self.yaw = 0.0
        self.pitch = -.25
        self.map_yaw = math.radians(30)
        self.map_pitch = scene.bp.map_angle
        self.follow_distance = scene.bp.distance
        if self.camera and scene.bp.camera_source == 'CAMERA':
            forward = self.camera.matrix_world.to_quaternion() @ Vector((0, 0, -1))
            self.yaw = math.atan2(forward.x, forward.y)
            self.pitch = math.asin(max(-1, min(1, forward.z)))
            eye = self.player.location + Vector((0, 0, self.player.dimensions.z * .35))
            offset = self.camera.location - eye
            self.follow_distance = max(1, offset.length)
            if offset.length > .1 and scene.bp.perspective == 'MAP':
                self.map_yaw = math.atan2(offset.x, -offset.y)
                self.map_pitch = max(math.radians(15), min(math.radians(75), math.asin(max(-1, min(1, offset.z / offset.length)))))
        self.initial_view = (self.yaw, self.pitch, self.map_yaw, self.map_pitch)
        self.running = True
        self.paused = False
        self.messages = []

    def log(self, message):
        self.messages.append(str(message))
        print('BlendPlay:', message)

    def quit(self):
        self.running = False

    def look(self, dx, dy):
        if self.scene.bp.perspective == 'MAP':
            self.map_yaw -= dx * self.scene.bp.sensitivity
            self.map_pitch = max(math.radians(15), min(math.radians(75), self.map_pitch + dy * self.scene.bp.sensitivity))
            return
        self.yaw += dx * self.scene.bp.sensitivity
        ceiling = -.03 if self.scene.bp.perspective == 'THIRD' else 1.3
        self.pitch = max(-1.3, min(ceiling, self.pitch + dy * self.scene.bp.sensitivity))

    def set_character_visible(self, visible):
        self.player.hide_set(bool(self.character) or not visible)
        if self.character:
            for obj in [self.character, *self.character.children_recursive]:
                obj.hide_set(not visible)

    def animate_character(self, rig, dt):
        if rig != self.character or rig.type != 'ARMATURE' or self.animation_updated:
            return
        self.animation_updated = True
        speed = self.movement_velocity.length
        mode = 'JUMP' if not self.grounded else ('RUN' if speed > self.scene.bp.speed * 1.2 else ('WALK' if speed > .1 else 'IDLE'))
        if mode != self.animation_mode:
            self.animation_mode = mode
            self.animation_phase = 0.0
        self.animation_phase += dt * (max(.5, speed * .35) if mode in {'WALK', 'RUN'} else .4)
        action = getattr(self.scene.bp, mode.lower() + '_action')
        if action:
            curves = self.animation_curves.setdefault(action.name, action_curves(action))
            start, end = action.frame_range
            frame = start + (self.animation_phase % 1.0) * max(1, end - start)
            blend = min(1, dt * 18)
            for curve in curves:
                try:
                    vector = rig.path_resolve(curve.data_path)
                    index = curve.array_index
                    vector[index] += (curve.evaluate(frame) - vector[index]) * blend
                except (ValueError, AttributeError, IndexError):
                    continue
        if speed > .1:
            angle = math.atan2(-self.movement_velocity.x, self.movement_velocity.y)
            difference = (angle - rig.rotation_euler.z + math.pi) % (2 * math.pi) - math.pi
            rig.rotation_euler.z += difference * min(1, dt * 12)

    def update_head_bob(self, dt):
        # 依据碰撞结算后的真实移动量产生脚步；撞墙、停下和腾空时淡出。
        cfg = self.scene.bp
        speed = self.movement_velocity.length
        moving = cfg.head_bob and cfg.perspective == 'FIRST' and self.grounded and speed > .1
        target = min(1.5, speed / max(.1, cfg.speed)) if moving else 0.0
        self.bob_weight += (target - self.bob_weight) * (1 - math.exp(-12 * dt))
        if moving:
            self.bob_phase = (self.bob_phase + speed * dt * math.tau / 2.8) % math.tau

    def camera_target(self):
        """返回当前视角的镜头位置、旋转和角色隐藏状态。"""
        cfg = self.scene.bp
        if cfg.perspective == 'MAP':
            # 固定斜上方的 2.5D 跟随镜头：角色始终在画面里，关卡仍有纵深。
            horizontal = cfg.map_height * math.cos(self.map_pitch)
            focus = self.player.location + Vector((0, 0, self.player.dimensions.z * .35))
            position = focus + Vector((horizontal * math.sin(self.map_yaw),
                                       -horizontal * math.cos(self.map_yaw),
                                       cfg.map_height * math.sin(self.map_pitch)))
            return position, (focus - position).to_track_quat('-Z', 'Y').to_euler(), False
        forward = Vector((math.sin(self.yaw)*math.cos(self.pitch), math.cos(self.yaw)*math.cos(self.pitch), math.sin(self.pitch)))
        eye = self.player.location + Vector((0,0,self.player.dimensions.z*.35))
        if cfg.perspective == 'FIRST':
            position, hide_player = eye, True
        else:
            distance = self.follow_distance if cfg.camera_source == 'CAMERA' else cfg.distance
            position, hide_player = eye - forward * distance, False
        rotation = forward.to_track_quat('-Z','Y')
        if cfg.perspective == 'FIRST' and cfg.head_bob:
            amount = self.bob_weight * cfg.head_bob_strength
            right = rotation @ Vector((1, 0, 0))
            position = position + right * (math.sin(self.bob_phase) * .018 * amount)
            position.z += math.sin(self.bob_phase * 2) * .035 * amount
            rotation = rotation @ Quaternion((0, 0, 1), math.sin(self.bob_phase) * .006 * amount)
        return position, rotation.to_euler(), hide_player

    def update_camera(self, force=False):
        if not self.camera: return
        cfg = self.scene.bp
        self.camera.data.type = 'ORTHO' if cfg.perspective == 'MAP' else 'PERSP'
        if cfg.perspective == 'MAP': self.camera.data.ortho_scale = cfg.map_scale
        if cfg.camera_control == 'PLAYER':
            if cfg.perspective == 'FIRST':
                self.camera.data.lens = self.camera.data.sensor_width / (2 * math.tan(math.radians(cfg.first_fov) / 2))
            elif self.camera in self.camera_lenses:
                self.camera.data.lens = self.camera_lenses[self.camera]
        if not self.auto_camera and not force: return
        position, rotation, hide_player = self.camera_target()
        self.camera.location = position
        self.camera.rotation_euler = rotation
        self.set_character_visible(not hide_player)

    def set_camera(self, camera, automatic=True):
        if isinstance(camera, str): camera = self.find(camera)
        if camera.type != 'CAMERA' or self.scene.objects.get(camera.name) != camera:
            raise ValueError('游戏镜头必须是当前场景中的摄像机')
        self.camera = camera
        self.scene.camera = camera
        self.auto_camera = bool(automatic)

    def find(self, name):
        obj = self.scene.objects.get(name)
        if obj is None: raise KeyError('找不到模型：' + name)
        return obj

    def teleport(self, obj, position):
        if isinstance(obj, str): obj = self.find(obj)
        obj.location = Vector(position)
        if obj == self.player:
            self.velocity = 0
            self.grounded = False
        self.scene.view_layers[0].update()

    def move_character(self, obj, direction, speed, jump=False, jump_speed=7):
        if obj != self.player: raise ValueError('当前角色物理控制器只能控制指定的玩家')
        self.move_request = (Vector(direction), max(0, float(speed)), bool(jump), float(jump_speed))

    def collect(self, obj):
        if obj.name in self.collected: return False
        self.collected.add(obj.name)
        obj.hide_set(True)
        self.score += 1
        return True

    def get_key(self, key):
        return key.upper() in self.keys

    def get_key_down(self, key):
        return key.upper() in self.pressed

    def get_key_up(self, key):
        return key.upper() in self.released

    def spawn(self, model_name, location=None):
        source = self.find(model_name)
        obj = source.copy()
        if source.data: obj.data = source.data.copy()
        self.scene.collection.objects.link(obj)
        if location is not None: obj.location = Vector(location)
        if obj.bp.invisible_in_game: obj.hide_set(True)
        self.spawned.append(obj)
        self.objects.append(obj)
        if obj.bp.role == 'COIN': self.total += 1
        old_count = len(self.components)
        for link in obj.bp.scripts:
            if link.enabled and link.text: self.attach(link.text, obj)
        for component in self.components[old_count:]:
            component.awake()
            component.start()
        return obj

    def destroy(self, obj):
        if isinstance(obj, str): obj = self.find(obj)
        if obj in {self.player, self.camera}: raise ValueError('不能销毁运行中的玩家或游戏镜头')
        if obj.name not in self.disabled and obj.bp.role == 'COIN' and obj.name not in self.collected: self.total -= 1
        self.disabled.add(obj.name)
        obj.hide_set(True)

    def attach(self, text, obj):
        if not text.as_string().strip(): return
        namespace = {'__name__': '__blendplay_component__', 'bpy': bpy, 'Behaviour': Behaviour}
        exec(compile(text.as_string(), text.name, 'exec'), namespace)
        cls = namespace.get('Script')
        if not isinstance(cls, type) or not issubclass(cls, Behaviour):
            raise TypeError(text.name + ' 需要定义 class Script(Behaviour)')
        instance = cls()
        instance.game, instance.object = self, obj
        instance.script_name = text.name
        self.components.append(instance)

    def load_script(self):
        self.components.clear()
        if self.character and self.character.animation_data:
            self.character.animation_data.action = None
        text = self.scene.bp.script
        if text:
            namespace = {'__name__': '__blendplay_game__', 'bpy': bpy, 'Behaviour': Behaviour}
            exec(compile(text.as_string(), text.name, 'exec'), namespace)
            for name in ('start', 'update', 'stop'):
                fn = namespace.get(name)
                if fn is not None and not callable(fn): raise TypeError(name + ' 必须是函数')
                self.hooks[name] = fn
        for link in self.scene.bp.files:
            if link.enabled and link.text: self.attach(link.text, None)
        for obj in self.objects:
            for link in obj.bp.scripts:
                if link.enabled and link.text: self.attach(link.text, obj)
        self.has_controller = any(c.object == self.player and getattr(c, 'controls_player', False) for c in self.components)
        for component in self.components: component.awake()
        self.call('start')

    def call(self, name, *args):
        fn = self.hooks.get(name)
        if fn: fn(self, *args)
        for component in list(self.components):
            if name == 'stop' or self.component_active(component):
                getattr(component, name)(*args)

    def component_active(self, component):
        obj = component.object
        if obj is not None and obj.name in self.disabled: return False
        if getattr(component, 'controls_player', False) and obj != self.player: return False
        if getattr(component, 'controls_camera', False) and obj != self.camera: return False
        return True

    def event(self, name, first, second):
        for component in self.components:
            if component.object == first: getattr(component, name)(second)
            elif component.object == second: getattr(component, name)(first)

    def reset(self):
        self.components = [c for c in self.components if c.object not in self.spawned]
        for obj in self.spawned:
            if obj.data and obj.data.users == 1:
                data = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                if isinstance(data, bpy.types.Mesh): bpy.data.meshes.remove(data)
            else: bpy.data.objects.remove(obj, do_unlink=True)
        self.spawned.clear()
        self.objects = [entry[0] for entry in self.saved]
        self.disabled.clear()
        self.total = sum(o.bp.role == 'COIN' for o in self.objects)
        for obj, matrix, hidden in self.saved:
            obj.matrix_world = matrix
            obj.hide_set(hidden)
        for data, energy, color in self.saved_lights:
            data.energy = energy
            data.color = color
        for data, lens, near, far, projection, scale in self.saved_cameras:
            data.lens, data.clip_start, data.clip_end = lens, near, far
            data.type, data.ortho_scale = projection, scale
        if self.saved_world:
            world, color = self.saved_world
            world.color = color
        self.scene.camera = self.saved_camera
        self.camera = self.saved_camera
        self.auto_camera = True
        for bone, matrix in self.saved_pose:
            bone.matrix_basis = matrix
        if self.character and self.character.animation_data:
            self.character.animation_data.action = self.saved_character_action
            if self.saved_character_slot:
                self.character.animation_data.action_slot = self.saved_character_slot
        self.scene.view_layers[0].update()
        self.velocity = 0
        self.grounded = False
        self.score = 0
        self.collected.clear()
        self.contacts.clear()
        self.coin_contacts.clear()
        self.triggers.clear()
        self.time = 0
        self.fixed_accumulator = 0
        self.yaw, self.pitch, self.map_yaw, self.map_pitch = self.initial_view
        self.animation_phase = 0.0
        self.bob_phase = 0.0
        self.bob_weight = 0.0
        self.animation_mode = 'IDLE'
        self.paused = False

    def step(self, keys, dt, jump=False):
        self.keys = set(keys)
        dt = min(dt, 1 / 30)
        previous_location = self.player.location.copy()
        self.animation_updated = False
        self.time += dt
        self.move_request = None
        self.call('update', dt)
        self.fixed_accumulator += dt
        while self.fixed_accumulator >= 1/60:
            for component in list(self.components):
                if self.component_active(component): component.fixed_update(1/60)
            self.fixed_accumulator -= 1/60
        cfg = self.scene.bp
        direction = Vector((float('D' in keys)-float('A' in keys), float('W' in keys)-float('S' in keys), 0))
        speed = cfg.speed
        jump_speed = cfg.jump
        if self.has_controller:
            direction = Vector((0,0,0))
            if self.move_request:
                direction, speed, requested_jump, jump_speed = self.move_request
                jump = jump or requested_jump
        if direction.length: direction.normalize()
        if cfg.perspective == 'MAP':
            # 键盘方向对应画面方向，斜镜头下仍能直观地向上、下、左、右移动。
            rotation = self.camera_target()[1].to_quaternion()
            right = rotation @ Vector((1, 0, 0))
            up = rotation @ Vector((0, 1, 0))
            right.z = up.z = 0
            right.normalize(); up.normalize()
            direction = right * direction.x + up * direction.y
            if direction.length: direction.normalize()
        else:
            direction = Vector((direction.x*math.cos(self.yaw)+direction.y*math.sin(self.yaw), -direction.x*math.sin(self.yaw)+direction.y*math.cos(self.yaw), 0))
        if jump and self.grounded:
            self.velocity = jump_speed
        self.velocity -= cfg.gravity * dt
        delta = direction * speed * dt
        delta.z = self.velocity * dt
        # 无父级且未旋转的角色控制器可直接平移包围盒，避免每个轴刷新全场景。
        # 旋转或带父级的控制器沿用完整求值，兼容已有项目。
        fast_controller = self.player.parent is None and sum(abs(v) for v in self.player.rotation_euler) < 1e-6
        if fast_controller:
            self.scene.view_layers[0].update()
            origin_location = self.player.location.copy()
            origin_box = bounds(self.player)
        solids = [(o, bounds(o)) for o in self.objects if o != self.player and o.bp.role == 'SOLID' and o.name not in self.disabled]
        contacts = set()
        self.grounded = False
        def player_box():
            if fast_controller:
                shift = self.player.location - origin_location
                return (origin_box[0] + shift, origin_box[1] + shift)
            self.scene.view_layers[0].update()
            return bounds(self.player)
        for axis in range(3):
            self.player.location[axis] += delta[axis]
            box = player_box()
            for solid_obj, solid in solids:
                if overlaps(box, solid):
                    contacts.add(solid_obj.name)
                    if axis < 2 and solid_obj.get('可步行台阶'):
                        rise = solid[1].z - box[0].z
                        if 0 < rise <= .32:
                            self.player.location.z += rise + .002
                            candidate = player_box()
                            if not any(overlaps(candidate, other) for other_obj, other in solids if other_obj != solid_obj):
                                box = candidate
                                continue
                            self.player.location.z -= rise + .002
                    if delta[axis] > 0:
                        self.player.location[axis] -= box[1][axis] - solid[0][axis]
                    elif delta[axis] < 0:
                        self.player.location[axis] += solid[1][axis] - box[0][axis]
                    if axis == 2:
                        self.grounded = delta.z < 0
                        self.velocity = 0
                    box = player_box()
        if fast_controller: self.scene.view_layers[0].update()
        for name in contacts - self.contacts: self.event('on_collision_enter', self.player, self.find(name))
        for name in self.contacts - contacts:
            if self.scene.objects.get(name): self.event('on_collision_exit', self.player, self.find(name))
        self.contacts = contacts
        triggers = set()
        coin_contacts = set()
        for obj in self.objects:
            if obj.name in self.disabled: continue
            if obj.bp.role == 'TRIGGER' and overlaps(bounds(self.player), bounds(obj)): triggers.add(obj.name)
            if obj.bp.role == 'COIN' and obj.name not in self.collected and overlaps(bounds(self.player), bounds(obj)):
                coin_contacts.add(obj.name)
                if obj.name not in self.coin_contacts:
                    handles = any(c.object == obj and getattr(c, 'handles_collection', False) for c in self.components)
                    if not handles: self.collect(obj)
                    self.event('on_trigger_enter', self.player, obj)
        self.coin_contacts = coin_contacts
        for name in triggers - self.triggers: self.event('on_trigger_enter', self.player, self.find(name))
        for name in self.triggers - triggers: self.event('on_trigger_exit', self.player, self.find(name))
        self.triggers = triggers
        if self.player.location.z < -30:
            self.player.location = self.start
            self.velocity = 0
        self.movement_velocity = (self.player.location - previous_location) / max(dt, 1e-6)
        self.movement_velocity.z = 0
        self.update_head_bob(dt)

        for component in list(self.components):
            if self.component_active(component): component.late_update(dt)
        if self.character and not self.animation_updated: self.animate_character(self.character, dt)
        self.update_camera(force=cfg.camera_control == 'PLAYER' or cfg.perspective == 'MAP')

def draw_game_hud(operator):
    r = operator.runtime
    blf.size(0, 18)
    blf.color(0, 1, 1, 1, 1)
    blf.position(0, 24, 38, 0)
    label = '暂停' if r.paused else ('完成' if r.total and r.score == r.total else '游戏运行中')
    mode_name = {'FIRST':'第一人称','THIRD':'第三人称','MAP':'斜角俯视'}[r.scene.bp.perspective]
    blf.draw(0, f'{label} · {mode_name} | 金币 {r.score}/{r.total} | 1/2/3 切换视角 | P 暂停 | Esc 退出')
    if r.messages:
        blf.position(0, 24, 66, 0)
        blf.draw(0, r.messages[-1][:90])
    if r.scene.bp.perspective == 'FIRST':
        region = bpy.context.region
        blf.position(0, region.width/2-5, region.height/2-6, 0)
        blf.draw(0, '+')

class BPPlay(bpy.types.Operator):
    bl_idname = 'bp.play'
    bl_label = '运行整个游戏'
    bl_options = {'BLOCKING'}
    @classmethod
    def poll(cls, context):
        return context.area and context.area.type in {'VIEW_3D', 'TEXT_EDITOR'} and context.scene.bp.player and ACTIVE is None and context.mode == 'OBJECT'

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        global ACTIVE
        player = context.scene.bp.player
        if player.parent or player.type != 'MESH' or player not in list(context.scene.objects):
            self.report({'ERROR'}, '角色必须是当前场景中没有父级的网格物体')
            return {'CANCELLED'}
        context.scene.bp.error = ''
        bpy.ops.bp.check()
        if context.scene.bp.error:
            self.report({'ERROR'}, context.scene.bp.error)
            return {'CANCELLED'}
        if context.scene.camera is None:
            self.report({'ERROR'}, '请先给场景设置摄像机，或用游戏项目创建器创建项目')
            return {'CANCELLED'}
        self.runtime = Runtime(context.scene)
        try:
            self.runtime.load_script()
        except Exception as exc:
            record_error(context.scene)
            self.runtime.reset()
            self.report({'ERROR'}, '脚本启动失败: ' + str(exc))
            return {'CANCELLED'}
        for obj in self.runtime.objects:
            if obj.bp.invisible_in_game:
                obj.hide_set(True)
        self.keys = set()
        self.mouse = None
        self.looking = False
        self.input_active = True
        self.window = context.window
        self.area = context.area
        if context.workspace.name.startswith('游戏 IDE'):
            self.area = next(a for a in self.window.screen.areas if a.type == 'VIEW_3D')
        self.original_area = self.area
        self.original_type = self.area.type
        self.area.type = 'VIEW_3D'
        self.entered_full = False
        if context.scene.bp.fullscreen and not context.screen.show_fullscreen:
            with context.temp_override(window=self.window, area=self.area):
                bpy.ops.screen.screen_full_area(use_hide_panels=True)
            self.area = next(a for a in self.window.screen.areas if a.type == 'VIEW_3D')
            self.entered_full = True
        self.space = self.area.spaces.active
        self.view = self.space.region_3d.view_perspective
        self.camera_zoom = self.space.region_3d.view_camera_zoom
        self.camera_offset = tuple(self.space.region_3d.view_camera_offset)
        self.overlays = self.space.overlay.show_overlays
        self.saved_shading = (self.space.shading.type, self.space.shading.color_type, self.space.shading.light,
                              self.space.shading.use_scene_lights, self.space.shading.use_scene_world)
        self.space.overlay.show_overlays = False
        self.space.shading.type = 'SOLID'
        self.space.shading.color_type = 'MATERIAL'
        self.space.shading.light = 'STUDIO'
        self.space.shading.use_scene_lights = True
        self.space.shading.use_scene_world = True
        if context.scene.camera:
            self.space.region_3d.view_perspective = 'CAMERA'
            self.space.region_3d.view_camera_offset = (0, 0)
            region = next(r for r in self.area.regions if r.type == 'WINDOW')
            viewport_aspect = region.width / max(1, region.height)
            render = context.scene.render
            render_aspect = (render.resolution_x * render.pixel_aspect_x) / max(1, render.resolution_y * render.pixel_aspect_y)
            aspect_mismatch = max(viewport_aspect / render_aspect, render_aspect / viewport_aspect)
            self.space.region_3d.view_camera_zoom = min(150, 50 * (math.sqrt(4.0 * aspect_mismatch) - math.sqrt(2)))
        self.runtime.update_camera(force=context.scene.bp.camera_control == 'PLAYER')
        self.last = time.perf_counter()
        self.timer = context.window_manager.event_timer_add(1/60, window=context.window)
        context.window_manager.modal_handler_add(self)
        self.hud = bpy.types.SpaceView3D.draw_handler_add(draw_game_hud, (self,), 'WINDOW', 'POST_PIXEL')
        ACTIVE = self
        return {'RUNNING_MODAL'}

    def finish(self, context):
        global ACTIVE
        if getattr(self, 'finished', False): return {'CANCELLED'}
        self.finished = True
        ACTIVE = None
        try: context.window_manager.event_timer_remove(self.timer)
        except (ReferenceError, RuntimeError): pass
        try: bpy.types.SpaceView3D.draw_handler_remove(self.hud, 'WINDOW')
        except (ReferenceError, ValueError): pass
        try: self.runtime.call('stop')
        except Exception as exc:
            record_error(self.runtime.scene)
            self.report({'ERROR'}, '脚本停止失败: ' + str(exc))
        try: self.runtime.reset()
        except Exception as exc:
            self.report({'WARNING'}, '部分场景数据无法恢复: ' + str(exc))
        try:
            self.space.region_3d.view_perspective = self.view
            self.space.region_3d.view_camera_zoom = self.camera_zoom
            self.space.region_3d.view_camera_offset = self.camera_offset
            self.space.overlay.show_overlays = self.overlays
            (self.space.shading.type, self.space.shading.color_type, self.space.shading.light,
             self.space.shading.use_scene_lights, self.space.shading.use_scene_world) = self.saved_shading
            self.area.header_text_set(None)
            if self.entered_full:
                region = next(r for r in self.area.regions if r.type == 'WINDOW')
                with context.temp_override(window=self.window, area=self.area, region=region):
                    bpy.ops.screen.screen_full_area(use_hide_panels=True)
            self.original_area.type = self.original_type
        except (ReferenceError, RuntimeError, StopIteration): pass
        return {'CANCELLED'}

    def modal(self, context, event):
        if event.type == 'ESC': return self.finish(context)
        if event.type == 'WINDOW_DEACTIVATE':
            self.keys.clear()
            self.looking = False
            self.input_active = False
            self.mouse = None
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            self.input_active = True
            self.mouse = (event.mouse_x, event.mouse_y)
        if event.type == 'RIGHTMOUSE':
            self.looking = event.value == 'PRESS'
            self.mouse = (event.mouse_x, event.mouse_y)
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            enabled = self.looking or (self.runtime.scene.bp.mouse_look == 'DIRECT' and self.input_active)
            previous = self.mouse or (getattr(event, 'mouse_prev_x', event.mouse_x), getattr(event, 'mouse_prev_y', event.mouse_y))
            if enabled and self.mouse is not None and not self.runtime.paused:
                dx = event.mouse_x - previous[0]
                dy = event.mouse_y - previous[1]
                # 指针回绕或窗口切换产生的跳变不应让镜头突然翻转。
                if abs(dx) < 256 and abs(dy) < 256:
                    self.runtime.look(dx, dy)
                    # 鼠标事件只累计角度；镜头和场景统一在下一帧刷新。
                    # 高频鼠标输入不再触发整场景依赖图刷新。
            self.mouse = (event.mouse_x, event.mouse_y)
            if enabled and (event.mouse_x < self.area.x + 8 or event.mouse_x > self.area.x + self.area.width - 8
                            or event.mouse_y < self.area.y + 8 or event.mouse_y > self.area.y + self.area.height - 8):
                self.window.cursor_warp(self.area.x + self.area.width // 2, self.area.y + self.area.height // 2)
                self.mouse = None
        if event.type not in {'TIMER', 'WINDOW_DEACTIVATE'}:
            if event.shift: self.keys.add('LEFT_SHIFT')
            else: self.keys.difference_update({'LEFT_SHIFT', 'RIGHT_SHIFT'})
        if event.type == 'P' and event.value == 'PRESS':
            self.runtime.paused = not self.runtime.paused
        if event.type in {'ONE','TWO','THREE'} and event.value == 'PRESS':
            mode = {'ONE':'FIRST','TWO':'THIRD','THREE':'MAP'}[event.type]
            self.runtime.scene.bp.perspective = mode
            self.runtime.update_camera(force=True)
            self.runtime.log('视角：' + {'FIRST':'第一人称','THIRD':'第三人称','MAP':'斜角俯视'}[mode])
        if event.value in {'PRESS','RELEASE'} and event.type not in {'TIMER','MOUSEMOVE','INBETWEEN_MOUSEMOVE'}:
            if event.value == 'PRESS':
                if event.type not in self.keys: self.runtime.pressed.add(event.type)
                self.keys.add(event.type)
            else:
                self.keys.discard(event.type)
                self.runtime.released.add(event.type)
        try:
            if event.type == 'R' and event.value == 'PRESS':
                self.runtime.call('stop')
                self.runtime.reset()
                self.runtime.state.clear()
                self.runtime.load_script()
            if event.type == 'SPACE' and event.value == 'PRESS' and self.runtime.grounded and not self.runtime.has_controller:
                self.runtime.velocity = self.runtime.scene.bp.jump
                self.runtime.grounded = False
            if event.type == 'TIMER':
                now = time.perf_counter()
                if not self.runtime.paused: self.runtime.step(self.keys, now-self.last)
                self.runtime.pressed.clear()
                self.runtime.released.clear()
                if not self.runtime.running: return self.finish(context)
                self.last = now
                r = self.runtime
                status = '完成！' if r.total and r.score == r.total else '收集金币'
                self.area.header_text_set(f'BlendPlay | {status} {r.score}/{r.total} | WASD 移动 · 空格跳跃 · 鼠标转动视角 · P 暂停 · R 重来 · Esc 退出')
                self.area.tag_redraw()
        except Exception as exc:
            record_error(self.runtime.scene)
            self.report({'ERROR'}, str(exc))
            return self.finish(context)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        if ACTIVE is self: self.finish(context)

class BPStop(bpy.types.Operator):
    bl_idname = 'bp.stop'
    bl_label = '停止游戏'
    def execute(self, context):
        if ACTIVE:
            window = ACTIVE.window
            with context.temp_override(window=window): ACTIVE.finish(context)
        return {'FINISHED'}

@persistent
def before_file_load(_):
    global ACTIVE
    if ACTIVE:
        try:
            with bpy.context.temp_override(window=ACTIVE.window): ACTIVE.finish(bpy.context)
        except Exception:
            ACTIVE = None
    SELECTIONS.clear()

@persistent
def after_file_load(_):
    def activate_layout():
        for window in bpy.context.window_manager.windows:
            if window.workspace.name.startswith('游戏 IDE') and not window.workspace.get('bp_library'):
                add_library(window)
        return None
    bpy.app.timers.register(activate_layout, first_interval=.5)

class BPDemo(bpy.types.Operator):
    bl_idname = 'bp.demo'
    bl_label = '创建示例（新场景）'
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        scene = bpy.data.scenes.new('游戏项目')
        context.window.scene = scene
        def cube(name, loc, scale, color, role='NONE'):
            bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
            obj = context.object
            obj.name = name
            obj.scale = scale
            obj.bp.role = role
            mat = bpy.data.materials.new(name)
            mat.diffuse_color = (*color, 1)
            obj.data.materials.append(mat)
            return obj
        cube('地面', (0,0,-.5), (18,18,1), (.08,.16,.23), 'SOLID')
        player = cube('玩家控制器',(0,-5,.9),( .65,.45,1.8),(.12,.75,1))
        scene.bp.player = player
        rig = build_character(context, player)
        object_script(rig)
        ensure_script(scene)
        for x,y,z,s in [(-3,0,.5,(3,3,1)),(2,2,1,(3,3,2)),(0,6,1.5,(4,2,3))]:
            cube('平台',(x,y,z),s,(.3,.45,.5),'SOLID')
        for x,y,z in [(0,-2,1),(-3,0,1.7),(2,2,2.7),(0,6,3.7),(5,-1,1)]:
            bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=.35, location=(x,y,z))
            obj=context.object
            obj.name='金币'
            obj.bp.role='COIN'
            mat=bpy.data.materials.new('金币材质')
            mat.diffuse_color=(1,.65,.03,1)
            obj.data.materials.append(mat)
        eye = player.location + Vector((0, 0, player.dimensions.z * .35))
        forward = Vector((0, math.cos(-.25), math.sin(-.25)))
        bpy.ops.object.camera_add(location=eye - forward * scene.bp.distance)
        scene.camera=context.object
        scene.camera.name="玩家摄像机"
        scene.camera.rotation_euler=forward.to_track_quat('-Z','Y').to_euler()
        scene.camera.data.lens=24
        scene.world=bpy.data.worlds.new('游戏世界')
        scene.world.color = (.04, .07, .12)
        world_code = bpy.data.texts.new('世界环境.py')
        world_code.write(WORLD_TEMPLATE)
        world_code.use_fake_user = True
        scene.bp.files.add().text = world_code
        bpy.ops.object.light_add(type='SUN',location=(0,0,10))
        context.object.name="阳光"
        context.object.data.energy=3
        for obj in scene.objects:
            if obj == player or obj.bp.role in {'COIN','SOLID'} or obj.type in {'CAMERA','LIGHT'}:
                object_script(obj)
        # 演示工程中一块平台真的移动；新建任意模型仍没有自动脚本。
        moving = next((o for o in scene.objects if o.name.startswith('平台')), None)
        if moving: moving['移动距离'] = .7
        for area in context.screen.areas:
            if area.type=='VIEW_3D':
                area.spaces.active.region_3d.view_perspective='CAMERA'
                area.spaces.active.shading.color_type='MATERIAL'
        return {'FINISHED'}

def record_error(scene):
    detail = traceback.format_exc()
    scene.bp.error = detail.strip().splitlines()[-1]
    text = bpy.data.texts.get('游戏错误.log') or bpy.data.texts.new('游戏错误.log')
    text.clear()
    text.write(detail)

class BPLaunch(bpy.types.Operator):
    bl_idname = 'bp.launch'
    bl_label = '开始游戏'
    perspective: EnumProperty(name='选择视角', items=[('THIRD','第三人称',''),('FIRST','第一人称',''),('MAP','斜角俯视','')], default='THIRD')
    def invoke(self, context, event):
        self.perspective = context.scene.bp.perspective
        return context.window_manager.invoke_props_dialog(self, width=420)
    def draw(self, context):
        self.layout.label(text='BlendPlay · 游戏启动')
        self.layout.prop(self, 'perspective', expand=True)
        self.layout.label(text='WASD / 空格 / 鼠标转动视角 / Esc 退出')
    def execute(self, context):
        context.scene.bp.perspective = self.perspective
        return bpy.ops.bp.play('INVOKE_DEFAULT')

class BPWelcome(bpy.types.Operator):
    bl_idname = 'bp.welcome'
    bl_label = '欢迎使用 BlendPlay'
    perspective: EnumProperty(name='游戏视角', items=[('THIRD','第三人称',''),('FIRST','第一人称',''),('MAP','斜角俯视','')], default='THIRD')
    def invoke(self, context, event):
        self.perspective = context.scene.bp.perspective
        return context.window_manager.invoke_props_dialog(self, width=420)
    def draw(self, context):
        self.layout.label(text='BlendPlay 2.5.1 · 创建、编写、运行你的游戏')
        self.layout.prop(self, 'perspective', expand=True)
        self.layout.label(text='确认后进入游戏 IDE；运行中按 1/2/3 也可切换视角')
        self.layout.label(text='左侧场景 · 中间场景与代码 · 右侧游戏设置')
        self.layout.label(text='确认后进入 IDE，顶部运行按钮启动整个游戏')
    def execute(self, context):
        if not context.scene.bp.player: bpy.ops.bp.demo()
        context.scene.bp.perspective = self.perspective
        make_ide(context)
        return {'FINISHED'}

class BPProject(bpy.types.Operator):
    bl_idname = 'bp.project'
    bl_label = '创建游戏项目'
    perspective: EnumProperty(name='控制模板', items=[('THIRD', '第三人称', '角色跟随镜头'), ('FIRST', '第一人称', '角色眼部镜头'), ('MAP', '斜角俯视', '斜上方跟随角色')], default='THIRD')
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=430)
    def draw(self, context):
        self.layout.label(text='BlendPlay 游戏项目 · Python')
        self.layout.label(text='创建独立场景、角色、关卡和游戏入口脚本')
        self.layout.prop(self, 'perspective', expand=True)
        self.layout.label(text='WASD 移动 · 空格跳跃 · 鼠标转动视角')
    def execute(self, context):
        bpy.ops.bp.demo()
        context.scene.bp.perspective = self.perspective
        if context.area: bpy.ops.bp.edit_script()
        return {'FINISHED'}

class BPCheck(bpy.types.Operator):
    bl_idname = 'bp.check'
    bl_label = '检查游戏项目'
    def execute(self, context):
        scene = context.scene
        issues = []
        if not scene.bp.player: issues.append('未指定角色')
        elif scene.bp.player.type != 'MESH' or scene.bp.player.parent: issues.append('角色必须是无父级网格')
        if not scene.camera: issues.append('未设置摄像机')
        if scene.bp.character and scene.bp.character.type != 'ARMATURE': issues.append('角色模型应选择骨骼对象')
        try:
            texts = [scene.bp.script] + [link.text for link in scene.bp.files if link.enabled]
            texts += [link.text for obj in scene.objects for link in obj.bp.scripts if link.enabled]
            for text in texts:
                if text: compile(text.as_string(), text.name, 'exec')
        except SyntaxError:
            record_error(scene)
            issues.append(scene.bp.error)
        if issues:
            scene.bp.error = '；'.join(issues)
            self.report({'WARNING'}, scene.bp.error)
        else:
            scene.bp.error = ''
            self.report({'INFO'}, '项目检查通过，可以运行整个游戏')
        return {'FINISHED'}

class BPError(bpy.types.Operator):
    bl_idname = 'bp.errors'
    bl_label = '打开错误日志'
    def execute(self, context):
        text = bpy.data.texts.get('游戏错误.log')
        if text:
            context.area.type = 'TEXT_EDITOR'
            context.area.spaces.active.text = text
        return {'FINISHED'}

def add_library(window):
    workspace = window.workspace
    if workspace.get('bp_library_building'): return
    workspace['bp_library_building'] = True
    def split_library():
        area = next((a for a in window.screen.areas if a.type == 'OUTLINER'), None)
        if area:
            with bpy.context.temp_override(window=window, area=area):
                bpy.ops.screen.area_split(direction='HORIZONTAL', factor=.45)
            bpy.app.timers.register(finish_library, first_interval=.2)
        return None
    def finish_library():
        areas = sorted([a for a in window.screen.areas if a.type == 'OUTLINER'], key=lambda a:a.y)
        if len(areas)<2 or not areas[0].width: return .2
        area = areas[0]
        with bpy.context.temp_override(window=window, area=area): area.type = 'PROPERTIES'
        def focus():
            with bpy.context.temp_override(window=window, area=area):
                try: area.spaces.active.context = 'WORLD'
                except TypeError: return .2
            workspace['bp_library'] = True
            workspace['bp_library_building'] = False
            return None
        bpy.app.timers.register(focus,first_interval=.2)
        return None
    bpy.app.timers.register(split_library,first_interval=.2)

def make_ide(context):
    window = context.window
    workspace = bpy.data.workspaces.get('游戏 IDE')
    if workspace and workspace.get('bp_building') and not workspace.get('bp_ready'):
        window.workspace = workspace
        return workspace
    if workspace and workspace.get('bp_ready'):
        window.workspace = workspace
        for area in window.screen.areas:
            if area.type == 'TEXT_EDITOR': area.spaces.active.text = ensure_script(context.scene)
        if not workspace.get('bp_library'):
            add_library(window)
        return workspace
    if not workspace:
        bpy.ops.workspace.duplicate()
        workspace = window.workspace
        workspace.name = '游戏 IDE'
    else: window.workspace = workspace
    stage = [0]
    def build():
        screen = window.screen
        if any(a.width == 0 or a.height == 0 for a in screen.areas): return .15
        def split(area, direction, factor):
            with bpy.context.temp_override(window=window, area=area):
                bpy.ops.screen.area_split(direction=direction, factor=factor)
        if stage[0] == 0:
            if len(screen.areas) > 1:
                area = min(screen.areas, key=lambda a:a.width*a.height)
                with bpy.context.temp_override(window=window, area=area): bpy.ops.screen.area_close()
                return .15
            screen.areas[0].type = 'VIEW_3D'
            split(screen.areas[0], 'VERTICAL', .18)
            stage[0] = 1
        elif stage[0] == 1:
            areas = sorted(screen.areas, key=lambda a:a.x)
            areas[0].type = 'OUTLINER'
            split(areas[1], 'VERTICAL', .76)
            stage[0] = 2
        elif stage[0] == 2:
            areas = sorted(screen.areas, key=lambda a:a.x)
            areas[2].type = 'PROPERTIES'
            split(areas[1], 'HORIZONTAL', .40)
            stage[0] = 3
        else:
            ordered = sorted(screen.areas, key=lambda a:(a.x,a.y))
            ordered[0].type = 'OUTLINER'
            ordered[-1].type = 'PROPERTIES'
            ordered[1].type = 'TEXT_EDITOR'
            ordered[2].type = 'VIEW_3D'
            for area in screen.areas:
                with bpy.context.temp_override(window=window, area=area):
                    space = area.spaces.active
                    if area.type == 'TEXT_EDITOR':
                        space.text = ensure_script(window.scene)
                        space.show_line_numbers = True
                        space.show_syntax_highlight = True
                        space.show_region_ui = False
                        space.font_size = 15
                    elif area.type == 'PROPERTIES': space.context = 'SCENE'
                    elif area.type == 'VIEW_3D':
                        space.show_region_ui = False
                        space.show_region_toolbar = False
                        space.shading.color_type = 'MATERIAL'
                        space.region_3d.view_perspective = 'CAMERA'
            workspace['bp_ready'] = True
            workspace['bp_building'] = False
            add_library(window)
            return None
        return .15
    workspace['bp_building'] = True
    bpy.app.timers.register(build, first_interval=.15)
    return workspace

class BPEdit(bpy.types.Operator):
    bl_idname = 'bp.edit_script'
    bl_label = '打开游戏 IDE'
    def execute(self, context):
        if not context.scene.bp.player:
            return bpy.ops.bp.project('INVOKE_DEFAULT')
        make_ide(context)
        return {'FINISHED'}

class BPSettingsPanel(bpy.types.Panel):
    bl_label = '游戏设置'
    bl_idname = 'BP_PT_inspector'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'scene'
    bl_order = -1000
    @classmethod
    def poll(cls, context):
        return context.workspace.name.startswith('游戏 IDE')
    def draw(self, context):
        l = self.layout
        l.use_property_split = True
        l.use_property_decorate = False
        cfg = context.scene.bp
        l.operator_context = 'INVOKE_DEFAULT'
        l.operator('bp.play', text='运行整个游戏', icon='PLAY')
        l.prop(cfg, 'follow_selection')
        l.prop(cfg, 'perspective')
        l.prop(cfg, 'player')
        l.prop(cfg, 'character')
        l.prop(context.scene, 'camera', text='游戏摄像机')
        l.prop(cfg, 'mouse_look')
        l.prop(cfg, 'camera_source')
        l.prop(cfg, 'camera_control')
        if cfg.player and not cfg.character: l.operator('bp.build_character', icon='OUTLINER_OB_ARMATURE')
        l.prop(cfg, 'script')
        if cfg.perspective == 'THIRD': l.prop(cfg, 'distance')
        if cfg.perspective == 'FIRST':
            l.prop(cfg, 'first_fov')
            l.prop(cfg, 'head_bob')
            if cfg.head_bob: l.prop(cfg, 'head_bob_strength')
        if cfg.perspective == 'MAP':
            l.prop(cfg, 'map_height')
            l.prop(cfg, 'map_scale')
            l.prop(cfg, 'map_angle')
        l.separator()
        for key in ('speed','jump','gravity'): l.prop(cfg, key)
        if cfg.character:
            box = l.box()
            box.label(text='角色动画')
            for key in ('idle_action', 'walk_action', 'run_action', 'jump_action'): box.prop(cfg, key)
        if context.object:
            l.separator()
            l.label(text='选中物体：' + context.object.name)
            l.prop(context.object.bp, 'role')
            l.prop(context.object.bp, 'invisible_in_game')
            for link in context.object.bp.scripts:
                row = l.row(align=True)
                row.prop(link, 'enabled', text='')
                row.prop(link, 'text', text='脚本')
            l.operator('bp.code', text='关联已有代码').mode = 'BIND'
            l.operator('bp.starter_script', text='添加可执行脚本', icon='FILE_SCRIPT')
        l.separator()
        l.label(text='独立游戏代码')
        for link in cfg.files:
            row = l.row(align=True)
            row.prop(link, 'enabled', text='')
            row.prop(link, 'text', text='')
        l.operator('bp.code', text='新建独立代码', icon='ADD').mode = 'NEW'
        l.separator()
        l.operator('bp.check', text='检查项目', icon='CHECKMARK')
        if cfg.error:
            box = l.box()
            box.label(text=cfg.error[:45], icon='ERROR')
            box.operator('bp.errors', text='查看完整错误')
        else:
            l.label(text='Python · 整个场景运行', icon='INFO')

class BPBack(bpy.types.Operator):
    bl_idname = 'bp.back'
    bl_label = '返回场景'
    def execute(self, context):
        context.area.type = 'VIEW_3D'
        return {'FINISHED'}

class BPScriptPanel(bpy.types.Panel):
    bl_label = 'BlendPlay 脚本运行'
    bl_idname = 'BP_PT_script'
    bl_space_type = 'TEXT_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'BlendPlay'
    def draw(self, context):
        layout = self.layout
        layout.operator_context = 'INVOKE_DEFAULT'
        layout.prop(context.scene.bp, 'player')
        layout.prop(context.scene.bp, 'character')
        layout.prop(context.scene, 'camera', text='游戏摄像机')
        layout.prop(context.scene.bp, 'mouse_look')
        layout.prop(context.scene.bp, 'camera_source')
        layout.prop(context.scene.bp, 'script')
        layout.prop(context.scene.bp, 'fullscreen')
        layout.label(text='项目 / Python 游戏入口', icon='FILE_SCRIPT')
        layout.prop(context.scene.bp, 'perspective')
        if context.scene.bp.perspective == 'THIRD': layout.prop(context.scene.bp, 'distance')
        if context.scene.bp.perspective == 'MAP':
            layout.prop(context.scene.bp, 'map_height')
            layout.prop(context.scene.bp, 'map_scale')
            layout.prop(context.scene.bp, 'map_angle')
        for key in ('speed', 'jump', 'gravity', 'sensitivity'): layout.prop(context.scene.bp, key)
        layout.operator('bp.check', icon='CHECKMARK')
        layout.operator('bp.play', text='运行整个游戏', icon='PLAY')
        layout.operator('wm.save_as_mainfile', text='保存游戏工程', icon='FILE_TICK')
        layout.operator('bp.project', text='新建游戏项目', icon='ADD')
        if context.scene.bp.error:
            layout.label(text=context.scene.bp.error[:55], icon='ERROR')
            layout.operator('bp.errors')
        layout.operator('bp.back', icon='VIEW3D')
        layout.label(text='start(game) / update(game, dt) / stop(game)')
        layout.label(text='Esc 退出，返回脚本界面')

def ide_toolbar(layout):
    row = layout.row(align=True)
    row.operator_context = 'INVOKE_DEFAULT'
    row.operator('bp.project', text='新建', icon='ADD')
    row.operator('wm.save_as_mainfile', text='保存', icon='FILE_TICK')
    if ACTIVE: row.operator('bp.stop', text='停止游戏', icon='PAUSE')
    else: row.operator('bp.play', text='运行整个游戏', icon='PLAY')

def script_header(self, context):
    if context.workspace.name.startswith('游戏 IDE'):
        self.layout.label(text='Game.py · Python', icon='FILE_SCRIPT')
    else:
        ide_toolbar(self.layout)

def game_header(self, context):
    if context.workspace.name.startswith('游戏 IDE'):
        ide_toolbar(self.layout)
    else:
        row = self.layout.row(align=True)
        row.operator_context = 'INVOKE_DEFAULT'
        row.operator('bp.edit_script', text='游戏 IDE', icon='CONSOLE')

ORIGINAL_TEXT_HEADER = None

def ide_text_header(self, context):
    if not context.workspace.name.startswith('游戏 IDE'):
        return ORIGINAL_TEXT_HEADER(self, context)
    layout = self.layout
    layout.operator_context = 'INVOKE_DEFAULT'
    layout.label(text='BlendPlay 2.5.1 已启用', icon='CHECKMARK')
    if ACTIVE: layout.operator('bp.stop', text='停止游戏', icon='PAUSE')
    else: layout.operator('bp.play', text='运行整个游戏', icon='PLAY')
    layout.separator()
    layout.operator('bp.code', text='环境代码').mode = 'ENV'
    layout.operator('bp.code', text='物体代码').mode = 'OBJECT'
    layout.operator('bp.starter_script', text='添加脚本', icon='FILE_SCRIPT')
    layout.operator('bp.code', text='新建代码', icon='ADD').mode = 'NEW'
    layout.template_ID(context.space_data, 'text')
    row = layout.row(align=True)
    row.operator('bp.edit_action', text='', icon='COPYDOWN').action = 'COPY'
    row.operator('text.paste', text='', icon='PASTEDOWN')
    layout.menu('BP_MT_edit', text='编辑')
    if context.space_data.text is None: layout.label(text='当前模型没有代码', icon='INFO')

class BPEditAction(bpy.types.Operator):
    bl_idname = 'bp.edit_action'
    bl_label = '代码编辑'
    bl_description = '复制所选代码（支持多行中文）；⌘C / Ctrl+C'
    action: EnumProperty(items=[('COPY','复制','复制所选代码')], default='COPY')
    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'TEXT_EDITOR' and context.space_data.text is not None
    def execute(self, context):
        text = context.space_data.text
        start = (text.current_line_index, text.current_character)
        end = (text.select_end_line_index, text.select_end_character)
        if start == end:
            self.report({'INFO'}, '请先拖选要复制的代码，或使用全选')
            return {'CANCELLED'}
        if start > end: start, end = end, start
        lines = [line.body for line in text.lines]
        if start[0] == end[0]:
            selected = lines[start[0]][start[1]:end[1]]
        else:
            selected = '\n'.join([lines[start[0]][start[1]:],
                                 *lines[start[0]+1:end[0]], lines[end[0]][:end[1]]])
        context.window_manager.clipboard = selected
        return {'FINISHED'}

class BP_MT_edit(bpy.types.Menu):
    bl_label = '编辑代码'
    def draw(self, context):
        self.layout.operator('bp.edit_action', text='复制  ⌘C / Ctrl+C')
        # 直接调用文本编辑器操作，保留原生文本撤销栈。
        for operator, label in [('text.cut','剪切  ⌘X / Ctrl+X'),
                                ('text.paste','粘贴  ⌘V / Ctrl+V'),
                                ('text.select_all','全选  ⌘A / Ctrl+A'),
                                ('ed.undo','撤销  ⌘Z / Ctrl+Z'),
                                ('ed.redo','重做  ⇧⌘Z / Ctrl+Shift+Z')]:
            self.layout.operator(operator, text=label)

EDIT_KEYMAPS = []

class BPBuildCharacter(bpy.types.Operator):
    bl_idname = 'bp.build_character'
    bl_label = '创建人形角色与走路动画'
    bl_options = {'REGISTER', 'UNDO'}
    @classmethod
    def poll(cls, context):
        return context.scene.bp.player is not None and context.scene.bp.character is None and ACTIVE is None and context.mode == 'OBJECT'
    def execute(self, context):
        rig = build_character(context, context.scene.bp.player)
        object_script(rig)
        self.report({'INFO'}, '已创建人形骨骼、蒙皮、待机、走路、奔跑与跳跃动画')
        return {'FINISHED'}

class BPAddGameObject(bpy.types.Operator):
    bl_idname = 'bp.add_game_object'
    bl_label = '添加游戏对象'
    bl_options = {'REGISTER', 'UNDO'}
    kind: EnumProperty(name='对象', items=[('PLAYER','主角',''),('NPC','非玩家角色',''),('AIR_WALL','空气墙',''),('PLATFORM','碰撞平台',''),('COIN','金币',''),('TRIGGER','触发区域',''),('CAMERA','游戏镜头',''),('LIGHT','灯光','')], default='PLAYER')
    name: StringProperty(name='名称')
    position: FloatVectorProperty(name='位置（人物为脚底）', subtype='TRANSLATION', size=3)
    width: FloatProperty(name='宽度', default=1, min=.05, max=1000)
    depth: FloatProperty(name='深度', default=1, min=.05, max=1000)
    height: FloatProperty(name='高度', default=1, min=.05, max=1000)
    shape: EnumProperty(name='造型', items=[('HUMANOID','人形（带动画）','独立碰撞控制器与带骨骼的人物'),('BLOCK','方块',''),('CAPSULE','胶囊形','')], default='HUMANOID')
    perspective: EnumProperty(name='游戏视角', items=[('THIRD','第三人称',''),('FIRST','第一人称',''),('MAP','斜角俯视','')], default='THIRD')
    speed: FloatProperty(name='移动速度', default=5, min=.1, max=100)
    jump: FloatProperty(name='跳跃速度', default=7, min=0, max=50)
    patrol_distance: FloatProperty(name='巡逻距离', default=1, min=0, max=100)
    light_type: EnumProperty(name='灯光类型', items=[('SUN','太阳光',''),('POINT','点光',''),('SPOT','聚光',''),('AREA','面光','')], default='POINT')
    energy: FloatProperty(name='亮度', default=500, min=0, max=100000)
    color: FloatVectorProperty(name='颜色', subtype='COLOR', size=3, min=0, max=1, default=(1, .8, .6))
    lens: FloatProperty(name='焦距', default=40, min=1, max=250)
    make_active: BoolProperty(name='设为当前游戏镜头', default=True)
    add_script: BoolProperty(name='添加可执行脚本', default=True)

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D' and context.mode == 'OBJECT'

    def invoke(self, context, event):
        labels = {'PLAYER':'主角','NPC':'角色','AIR_WALL':'空气墙','PLATFORM':'平台','COIN':'金币','TRIGGER':'触发区域','CAMERA':'游戏镜头','LIGHT':'灯光'}
        self.name = labels[self.kind]
        self.position = context.scene.cursor.location
        self.add_script = self.kind != 'AIR_WALL'
        self.shape = 'HUMANOID' if self.kind == 'PLAYER' else 'CAPSULE'
        if self.kind in {'PLAYER','NPC'}:
            self.width, self.depth, self.height = .8, .8, 1.6
        elif self.kind == 'PLATFORM':
            self.width, self.depth, self.height = 4, 4, .6
        elif self.kind == 'AIR_WALL':
            self.width, self.depth, self.height = 4, .25, 3
        elif self.kind == 'TRIGGER':
            self.width, self.depth, self.height = 3, .4, 2
        elif self.kind == 'LIGHT':
            self.position = context.scene.cursor.location + Vector((0,0,5))
        elif self.kind == 'CAMERA':
            self.position = context.scene.cursor.location + Vector((0,-6,3))
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'name')
        layout.prop(self, 'position')
        if self.kind == 'PLAYER':
            layout.prop(self, 'shape')
        elif self.kind == 'NPC':
            row = layout.row(align=True)
            row.prop_enum(self, 'shape', 'BLOCK')
            row.prop_enum(self, 'shape', 'CAPSULE')
        if self.kind in {'PLAYER','NPC','AIR_WALL','PLATFORM','TRIGGER'}:
            row = layout.row(align=True)
            row.prop(self, 'width');row.prop(self, 'depth');row.prop(self, 'height')
        if self.kind == 'PLAYER':
            layout.prop(self, 'perspective')
            layout.prop(self, 'speed')
            layout.prop(self, 'jump')
        if self.kind == 'NPC': layout.prop(self, 'patrol_distance')
        if self.kind == 'LIGHT':
            layout.prop(self, 'light_type')
            layout.prop(self, 'energy')
            layout.prop(self, 'color')
        if self.kind == 'CAMERA':
            layout.prop(self, 'lens')
            layout.prop(self, 'make_active')
        layout.prop(self, 'add_script')
        if self.kind == 'AIR_WALL': layout.label(text='编辑时显示边框，游戏中隐形但保留碰撞')

    def execute(self, context):
        kind = self.kind
        position = Vector(self.position)
        if kind == 'CAMERA':
            bpy.ops.object.camera_add(location=position)
            obj = context.object
            obj.data.lens = self.lens
            target = context.scene.bp.player.location if context.scene.bp.player else context.scene.cursor.location
            obj.rotation_euler = (Vector(target)-obj.location).to_track_quat('-Z','Y').to_euler()
            if self.make_active: context.scene.camera = obj
        elif kind == 'LIGHT':
            bpy.ops.object.light_add(type=self.light_type, location=position)
            obj = context.object
            obj.data.energy = self.energy
            obj.data.color = self.color
        elif kind == 'COIN':
            bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=.35, location=position)
            obj = context.object
            obj.bp.role = 'COIN'
        else:
            if kind in {'PLAYER','NPC'} and self.shape == 'CAPSULE':
                bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=.5, depth=1, location=position)
            else:
                bpy.ops.mesh.primitive_cube_add(size=1, location=position)
            obj = context.object
            obj.dimensions = (self.width, self.depth, self.height)
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            if kind in {'PLAYER','NPC'} and self.shape == 'CAPSULE':
                bevel = obj.modifiers.new('圆角身体', 'BEVEL')
                bevel.width = min(self.width, self.depth, self.height) * .45
                bevel.segments = 4
                obj.modifiers.new('平滑法线', 'WEIGHTED_NORMAL')
            if kind in {'PLATFORM','AIR_WALL','NPC'}: obj.bp.role = 'SOLID'
            if kind == 'TRIGGER': obj.bp.role = 'TRIGGER'
            if kind in {'PLAYER','NPC'}:
                obj.location.z += self.height/2
            if kind == 'PLAYER':
                context.scene.bp.player = obj
                context.scene.bp.character = None
                context.scene.bp.perspective = self.perspective
                context.scene.bp.speed = self.speed
                context.scene.bp.jump = self.jump
            if kind == 'NPC':
                obj['游戏角色'] = 'NPC'
                obj['巡逻距离'] = self.patrol_distance
            if kind in {'AIR_WALL','TRIGGER'}:
                obj.bp.invisible_in_game = True
                obj.display_type = 'WIRE'
                obj.hide_render = True
        obj.name = self.name.strip() or kind
        if obj.type == 'MESH' and kind not in {'AIR_WALL','TRIGGER'}:
            palette = {'PLAYER':(.15,.65,1),'NPC':(.9,.35,.3),'PLATFORM':(.25,.45,.55),'COIN':(1,.75,.08)}
            mat = bpy.data.materials.new(obj.name + '材质')
            mat.diffuse_color = (*palette.get(kind,(.5,.5,.5)),1)
            obj.data.materials.append(mat)
        if kind == 'PLAYER' and self.shape == 'HUMANOID':
            obj.name = (self.name.strip() or '玩家') + '控制器'
            rig = build_character(context, obj)
            if self.add_script: object_script(rig)
        if self.add_script:
            text = object_script(obj)
            show_code(context.window, text, force=True)
        self.report({'INFO'}, '已添加 ' + obj.name)
        return {'FINISHED'}

class BP_MT_add(bpy.types.Menu):
    bl_label = 'BlendPlay 游戏对象'
    bl_idname = 'BP_MT_add'
    def draw(self, context):
        layout = self.layout
        for kind, label, icon in [('PLAYER','主角','OUTLINER_OB_ARMATURE'),('NPC','非玩家角色','OUTLINER_OB_MESH'),('AIR_WALL','空气墙','MOD_PHYSICS'),('PLATFORM','碰撞平台','MESH_CUBE'),('COIN','金币','MESH_UVSPHERE'),('TRIGGER','触发区域','OUTLINER_OB_EMPTY'),('CAMERA','游戏镜头','OUTLINER_OB_CAMERA'),('LIGHT','灯光','OUTLINER_OB_LIGHT')]:
            layout.operator('bp.add_game_object', text=label, icon=icon).kind = kind

def add_game_menu(self, context):
    if context.mode == 'OBJECT':
        self.layout.separator()
        self.layout.menu('BP_MT_add', text='BlendPlay 游戏对象', icon='PLAY')

class BPStarter(bpy.types.Operator):
    bl_idname = 'bp.starter_script'
    bl_label = '添加可执行脚本'
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        obj = context.view_layer.objects.active
        if obj is None:
            self.report({'WARNING'}, '请先选择物体')
            return {'CANCELLED'}
        text = object_script(obj)
        context.scene.bp.follow_selection = True
        context.scene.bp.file_index = list(bpy.data.texts).index(text)
        show_code(context.window, text, force=True)
        self.report({'INFO'}, '已关联并打开 ' + text.name)
        return {'FINISHED'}

class BPCode(bpy.types.Operator):
    bl_idname = 'bp.code'
    bl_label = '代码文件'
    mode: EnumProperty(items=[('ENV','环境代码',''),('OBJECT','模型代码',''),('NEW','新建代码',''),('BIND','关联模型','')], default='NEW')
    name: StringProperty(name='文件名称', default='新脚本.py')
    template: EnumProperty(name='内容', items=[('BLANK','空白文件',''),('COMPONENT','普通组件模板',''),('PLAYER','玩家控制器模板',''),('NPC','非玩家角色模板',''),('COIN','金币模板',''),('PLATFORM','平台模板',''),('TRIGGER','触发区域模板',''),('CAMERA','镜头脚本',''),('LIGHT','灯光脚本',''),('WORLD','世界环境脚本','')], default='BLANK')
    text_name: StringProperty(name='代码文件')
    obj_name: StringProperty(name='关联模型')
    def invoke(self, context, event):
        if self.mode in {'ENV','OBJECT'}: return self.execute(context)
        active = context.view_layer.objects.active
        self.obj_name = active.name if active and self.mode == 'BIND' else ''
        if context.area.type == 'TEXT_EDITOR' and context.space_data.text: self.text_name = context.space_data.text.name
        return context.window_manager.invoke_props_dialog(self, width=420)
    def draw(self, context):
        if self.mode == 'NEW':
            self.layout.prop(self, 'name')
            self.layout.prop(self, 'template')
        else: self.layout.prop_search(self, 'text_name', bpy.data, 'texts')
        self.layout.prop_search(self, 'obj_name', context.scene, 'objects')
        self.layout.label(text='不关联模型时作为独立游戏组件运行')
    def execute(self, context):
        cfg = context.scene.bp
        if self.mode == 'ENV':
            cfg.follow_selection = True
            text = ensure_script(context.scene)
        elif self.mode == 'OBJECT':
            obj = context.view_layer.objects.active
            if not obj:
                self.report({'WARNING'}, '请先在左侧选择模型')
                return {'CANCELLED'}
            cfg.follow_selection = True
            text = next((link.text for link in obj.bp.scripts if link.text), None)
            if text is None:
                show_code(context.window, None)
                self.report({'INFO'}, '该模型没有代码，请新建文件或关联已有文件')
                return {'FINISHED'}
        else:
            text = bpy.data.texts.get(self.text_name)
            if self.mode == 'NEW':
                text = bpy.data.texts.new(self.name if self.name.endswith('.py') else self.name+'.py')
                source = {'BLANK':'','COMPONENT':COMPONENT_TEMPLATE,'PLAYER':PLAYER_TEMPLATE,'NPC':NPC_TEMPLATE,'COIN':COIN_TEMPLATE,'PLATFORM':PLATFORM_TEMPLATE,'TRIGGER':TRIGGER_TEMPLATE,'CAMERA':CAMERA_TEMPLATE,'LIGHT':LIGHT_TEMPLATE,'WORLD':WORLD_TEMPLATE}[self.template]
                text.write(source)
                text.use_fake_user = True
            if not text:
                self.report({'ERROR'}, '请选择代码文件')
                return {'CANCELLED'}
            obj = context.scene.objects.get(self.obj_name)
            if self.obj_name and not obj:
                self.report({'ERROR'}, '找不到关联模型：' + self.obj_name)
                return {'CANCELLED'}
            links = obj.bp.scripts if obj else cfg.files
            if not any(link.text == text for link in links): links.add().text = text
            cfg.follow_selection = True
        obj = context.view_layer.objects.active
        SELECTIONS[context.window.as_pointer()] = (context.scene.as_pointer(), obj.as_pointer() if obj else 0)
        cfg.file_index = list(bpy.data.texts).index(text)
        show_code(context.window, text, force=True)
        return {'FINISHED'}

class BPImport(bpy.types.Operator, ImportHelper):
    bl_idname = 'bp.import_code'
    bl_label = '导入独立 Python 文件'
    filename_ext = '.py'
    filter_glob: StringProperty(default='*.py', options={'HIDDEN'})
    def execute(self, context):
        try:
            source = Path(self.filepath).read_text(encoding='utf-8-sig')
            compile(source, self.filepath, 'exec')
        except Exception as exc:
            self.report({'ERROR'}, '导入失败：' + str(exc))
            return {'CANCELLED'}
        text = bpy.data.texts.new(Path(self.filepath).name)
        text.write(source)
        text.use_fake_user = True
        context.scene.bp.files.add().text = text
        context.scene.bp.file_index = list(bpy.data.texts).index(text)
        window = context.window
        bpy.app.timers.register(lambda: show_code(window, text), first_interval=.2)
        return {'FINISHED'}

class BPExport(bpy.types.Operator, ExportHelper):
    bl_idname = 'bp.export_code'
    bl_label = '导出独立 Python 文件'
    filename_ext = '.py'
    filter_glob: StringProperty(default='*.py', options={'HIDDEN'})
    def execute(self, context):
        index = context.scene.bp.file_index
        if not 0 <= index < len(bpy.data.texts): return {'CANCELLED'}
        text = bpy.data.texts[index]
        try: Path(self.filepath).write_text(text.as_string(), encoding='utf-8')
        except Exception as exc:
            self.report({'ERROR'}, '导出失败：' + str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, '已导出：' + self.filepath)
        return {'FINISHED'}

class BP_UL_files(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        icon = 'WORLD' if item == context.scene.bp.script else 'FILE_SCRIPT'
        layout.label(text=item.name, icon=icon)
    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        return [0 if t.name == '游戏错误.log' else self.bitflag_filter_item for t in items], []

class BPDetach(bpy.types.Operator):
    bl_idname = 'bp.detach'
    bl_label = '解除代码关联'
    bl_options = {'REGISTER','UNDO'}
    text_name: StringProperty()
    obj_name: StringProperty()
    def execute(self, context):
        obj = context.scene.objects.get(self.obj_name)
        links = obj.bp.scripts if obj else context.scene.bp.files
        for i in reversed(range(len(links))):
            if links[i].text and links[i].text.name == self.text_name: links.remove(i)
        return {'FINISHED'}

class BPLibrary(bpy.types.Panel):
    bl_label = '代码文件'
    bl_idname = 'BP_PT_library'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'world'
    bl_order = -1000
    @classmethod
    def poll(cls, context): return context.workspace.name.startswith('游戏 IDE')
    def draw(self, context):
        l = self.layout
        l.operator_context = 'INVOKE_DEFAULT'
        cfg = context.scene.bp
        l.template_list('BP_UL_files','',bpy.data,'texts',cfg,'file_index',rows=7)
        row = l.row(align=True)
        row.operator('bp.code', text='新建文件', icon='ADD').mode = 'NEW'
        row.operator('bp.code', text='关联模型', icon='LINKED').mode = 'BIND'
        l.operator('bp.code', text='环境代码', icon='WORLD').mode = 'ENV'
        l.operator('bp.starter_script', text='给选中物体添加可执行脚本', icon='FILE_SCRIPT')
        row = l.row(align=True)
        row.operator('bp.import_code', text='导入 .py', icon='IMPORT')
        row.operator('bp.export_code', text='导出 .py', icon='EXPORT')
        if 0 <= cfg.file_index < len(bpy.data.texts):
            text = bpy.data.texts[cfg.file_index]
            l.label(text='当前：' + text.name)
            if text == cfg.script: l.label(text='全局环境入口', icon='WORLD')
            owners = [o for o in context.scene.objects if any(link.text == text for link in o.bp.scripts)]
            for owner in owners:
                row = l.row(align=True)
                row.label(text=owner.name, icon='OBJECT_DATA')
                op = row.operator('bp.detach', text='', icon='X')
                op.obj_name, op.text_name = owner.name, text.name
            if any(link.text == text for link in cfg.files):
                row = l.row(align=True)
                row.label(text='独立游戏组件', icon='FILE_SCRIPT')
                op=row.operator('bp.detach', text='', icon='X')
                op.text_name = text.name
            if not owners and text != cfg.script and not any(link.text == text for link in cfg.files):
                l.label(text='未关联，不参与游戏运行', icon='INFO')

class BPPanel(bpy.types.Panel):
    bl_label='BlendPlay 游戏'
    bl_idname='BP_PT_panel'
    bl_space_type='VIEW_3D'
    bl_region_type='UI'
    bl_category='BlendPlay'
    def draw(self, context):
        layout=self.layout
        layout.operator_context = 'INVOKE_DEFAULT'
        layout.operator('bp.project', text='新建游戏项目')
        layout.prop(context.scene.bp, 'perspective')
        if context.scene.bp.perspective == 'MAP':
            layout.prop(context.scene.bp, 'map_height')
            layout.prop(context.scene.bp, 'map_scale')
            layout.prop(context.scene.bp, 'map_angle')
        layout.prop(context.scene.bp,'player')
        layout.prop(context.scene.bp,'character')
        layout.prop(context.scene,'camera',text='游戏摄像机')
        layout.prop(context.scene.bp,'mouse_look')
        layout.prop(context.scene.bp,'camera_source')
        if context.scene.bp.player and not context.scene.bp.character:
            layout.operator('bp.build_character', icon='OUTLINER_OB_ARMATURE')
        for key in ('speed','jump','gravity'): layout.prop(context.scene.bp,key)
        if context.object: layout.prop(context.object.bp,'role')
        if context.object: layout.prop(context.object.bp,'invisible_in_game')
        layout.menu('BP_MT_add', text='添加游戏对象', icon='ADD')
        layout.operator('bp.edit_script', icon='TEXT')
        layout.prop(context.scene.bp, 'fullscreen')
        layout.operator('bp.play', icon='PLAY')
        layout.label(text='WASD · 空格跳跃 · 鼠标转动视角 · P 暂停 · R 重来 · Esc 退出')
        layout.label(text='用 Ctrl+S 保存为 .blend')

classes=(BPLink,BPSettings,BPObject,BPPlay,BPStop,BPDemo,BPLaunch,BPWelcome,BPProject,BPCheck,BPError,BPEditAction,BP_MT_edit,BPBuildCharacter,BPAddGameObject,BP_MT_add,BPStarter,BPCode,BPImport,BPExport,BP_UL_files,BPDetach,BPLibrary,BPEdit,BPSettingsPanel,BPBack,BPScriptPanel,BPPanel)
def register():
    global ORIGINAL_TEXT_HEADER
    for cls in classes: bpy.utils.register_class(cls)
    bpy.types.Scene.bp=PointerProperty(type=BPSettings)
    bpy.types.Object.bp=PointerProperty(type=BPObject)
    from bl_ui.space_text import TEXT_HT_header
    ORIGINAL_TEXT_HEADER = TEXT_HT_header.draw
    TEXT_HT_header.draw = ide_text_header
    bpy.app.timers.register(selection_sync, first_interval=.2, persistent=True)
    bpy.types.VIEW3D_HT_header.append(game_header)
    bpy.types.VIEW3D_MT_add.append(add_game_menu)
    bpy.app.handlers.load_pre.append(before_file_load)
    bpy.app.handlers.load_post.append(after_file_load)
    after_file_load(None)
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig:
        keymap = keyconfig.keymaps.new(name='Text', space_type='TEXT_EDITOR')
        for key, operator in [('C','bp.edit_action'),('X','text.cut'),('V','text.paste'),('A','text.select_all')]:
            for modifier in ('ctrl','oskey'):
                item = keymap.keymap_items.new(operator, key, 'PRESS', head=True, **{modifier:True})
                EDIT_KEYMAPS.append((keymap,item))
def unregister():
    if ACTIVE: ACTIVE.finish(bpy.context)
    from bl_ui.space_text import TEXT_HT_header
    TEXT_HT_header.draw = ORIGINAL_TEXT_HEADER
    if bpy.app.timers.is_registered(selection_sync): bpy.app.timers.unregister(selection_sync)
    SELECTIONS.clear()
    for keymap,item in EDIT_KEYMAPS: keymap.keymap_items.remove(item)
    EDIT_KEYMAPS.clear()
    bpy.types.VIEW3D_HT_header.remove(game_header)
    bpy.types.VIEW3D_MT_add.remove(add_game_menu)
    if before_file_load in bpy.app.handlers.load_pre: bpy.app.handlers.load_pre.remove(before_file_load)
    if after_file_load in bpy.app.handlers.load_post: bpy.app.handlers.load_post.remove(after_file_load)
    del bpy.types.Object.bp
    del bpy.types.Scene.bp
    for cls in reversed(classes): bpy.utils.unregister_class(cls)
if __name__=='__main__': register()
