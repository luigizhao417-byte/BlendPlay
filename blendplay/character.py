# SPDX-License-Identifier: GPL-3.0-or-later
"""可编辑的人形骨骼、蒙皮与真实 Blender 动画片段。"""
import math
import bpy
from mathutils import Vector


def action_curves(action):
    if hasattr(action, 'fcurves'):
        return list(action.fcurves)
    return [curve for layer in action.layers for strip in layer.strips
            for bag in getattr(strip, 'channelbags', ()) for curve in bag.fcurves]


def build_character(context, controller):
    scene = context.scene
    context.view_layer.update()
    height = max(.5, controller.dimensions.z)
    armature = bpy.data.armatures.new(controller.name + '骨骼')
    rig = bpy.data.objects.new(controller.name + '角色', armature)
    scene.collection.objects.link(rig)
    rig.parent = controller
    # 控制器缩放不会拉长人形骨骼；身体跟随控制器平移。
    rig.matrix_parent_inverse = controller.matrix_world.inverted()
    rig.matrix_world.translation = controller.location - Vector((0, 0, height / 2))
    rig['bp_character'] = True
    context.view_layer.objects.active = rig
    controller.select_set(False)
    rig.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    skeleton = [
        ('身体', (0, 0, .48), (0, 0, .82), None),
        ('头', (0, 0, .82), (0, 0, 1), '身体'),
        ('左上臂', (-.22, 0, .77), (-.25, 0, .57), '身体'),
        ('左前臂', (-.25, 0, .57), (-.25, 0, .40), '左上臂'),
        ('右上臂', (.22, 0, .77), (.25, 0, .57), '身体'),
        ('右前臂', (.25, 0, .57), (.25, 0, .40), '右上臂'),
        ('左大腿', (-.105, 0, .48), (-.105, 0, .25), '身体'),
        ('左小腿', (-.105, 0, .25), (-.105, 0, .045), '左大腿'),
        ('右大腿', (.105, 0, .48), (.105, 0, .25), '身体'),
        ('右小腿', (.105, 0, .25), (.105, 0, .045), '右大腿'),
    ]
    for name, head, tail, parent in skeleton:
        bone = armature.edit_bones.new(name)
        bone.head = Vector(head) * height
        bone.tail = Vector(tail) * height
        if parent:
            bone.parent = armature.edit_bones[parent]
    bpy.ops.object.mode_set(mode='OBJECT')

    vertices, faces, assignments, face_materials = [], [], {}, []

    def ellipsoid(center, radii, bone, material=0):
        start = len(vertices)
        rings, sides = 8, 12
        for ring in range(rings + 1):
            latitude = math.pi * ring / rings
            for side in range(sides):
                longitude = 2 * math.pi * side / sides
                point = (center[0] + radii[0] * math.sin(latitude) * math.cos(longitude),
                         center[1] + radii[1] * math.sin(latitude) * math.sin(longitude),
                         center[2] + radii[2] * math.cos(latitude))
                vertices.append(tuple(value * height for value in point))
        assignments.setdefault(bone, []).extend(range(start, len(vertices)))
        for ring in range(rings):
            for side in range(sides):
                nxt = (side + 1) % sides
                faces.append((start + ring * sides + side, start + ring * sides + nxt,
                              start + (ring + 1) * sides + nxt, start + (ring + 1) * sides + side))
                face_materials.append(material)

    ellipsoid((0, 0, .65), (.19, .115, .20), '身体')
    ellipsoid((0, 0, .91), (.105, .095, .11), '头', 1)
    # 面向 +Y，面罩帮助辨认角色朝向。
    ellipsoid((0, .086, .925), (.082, .025, .04), '头', 2)
    for side, sign in [('左', -1), ('右', 1)]:
        ellipsoid((sign * .235, 0, .67), (.055, .055, .115), side + '上臂')
        ellipsoid((sign * .25, 0, .485), (.043, .043, .095), side + '前臂', 1)
        ellipsoid((sign * .105, 0, .365), (.075, .07, .135), side + '大腿', 2)
        ellipsoid((sign * .105, 0, .14), (.052, .052, .115), side + '小腿', 2)
        ellipsoid((sign * .105, .045, .035), (.066, .095, .04), side + '小腿', 2)

    mesh = bpy.data.meshes.new(controller.name + '人形蒙皮')
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    body = bpy.data.objects.new(controller.name + '外观', mesh)
    scene.collection.objects.link(body)
    body.parent = rig
    for name, indices in assignments.items():
        body.vertex_groups.new(name=name).add(indices, 1, 'REPLACE')
    modifier = body.modifiers.new('角色骨骼', 'ARMATURE')
    modifier.object = rig
    for name, color in [('服装', (.08, .58, .85, 1)), ('头部', (.9, .7, .48, 1)), ('靴子与面罩', (.025, .06, .09, 1))]:
        material = bpy.data.materials.new(controller.name + name)
        material.diffuse_color = color
        material.use_nodes = True
        material.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value = color
        mesh.materials.append(material)
    for polygon, index in zip(mesh.polygons, face_materials):
        polygon.material_index = index
        polygon.use_smooth = True

    rig.animation_data_create()
    for bone in rig.pose.bones:
        bone.rotation_mode = 'XYZ'
    for mode, label, length in [('IDLE', '待机', 49), ('WALK', '走路', 25), ('RUN', '奔跑', 17), ('JUMP', '跳跃', 17)]:
        action = bpy.data.actions.new(controller.name + '_' + label)
        action.use_fake_user = True
        rig.animation_data.action = action
        for frame in range(1, length + 1):
            phase = (frame - 1) / (length - 1) * 2 * math.pi
            for bone in rig.pose.bones:
                bone.location = (0, 0, 0)
                bone.rotation_euler = (0, 0, 0)
            if mode in {'WALK', 'RUN'}:
                amplitude = .55 if mode == 'WALK' else .85
                for side, sign in [('左', 1), ('右', -1)]:
                    swing = math.sin(phase) * sign
                    rig.pose.bones[side + '大腿'].rotation_euler.x = swing * amplitude
                    rig.pose.bones[side + '小腿'].rotation_euler.x = -max(0, -swing) * amplitude * .9
                    rig.pose.bones[side + '上臂'].rotation_euler.x = -swing * amplitude * .65
                    rig.pose.bones[side + '前臂'].rotation_euler.x = -.2 if mode == 'WALK' else -.55
                rig.pose.bones['身体'].location.y = abs(math.sin(phase)) * height * .018
                rig.pose.bones['身体'].rotation_euler.z = math.sin(phase) * .035
                rig.pose.bones['身体'].rotation_euler.x = -.04 if mode == 'WALK' else -.14
                rig.pose.bones['头'].rotation_euler.z = -math.sin(phase) * .02
            elif mode == 'JUMP':
                for side in ('左', '右'):
                    rig.pose.bones[side + '大腿'].rotation_euler.x = .35
                    rig.pose.bones[side + '小腿'].rotation_euler.x = -.65
                    rig.pose.bones[side + '上臂'].rotation_euler.x = -.7
            else:
                rig.pose.bones['身体'].location.y = math.sin(phase) * height * .004
            for bone in rig.pose.bones:
                bone.keyframe_insert(data_path='rotation_euler', frame=frame, group=bone.name)
                if bone.name == '身体':
                    bone.keyframe_insert(data_path='location', frame=frame, group=bone.name)
        for curve in action_curves(action):
            for keyframe in curve.keyframe_points:
                keyframe.interpolation = 'LINEAR'
        setattr(scene.bp, mode.lower() + '_action', action)
    rig.animation_data.action = scene.bp.idle_action
    for bone in rig.pose.bones:
        bone.rotation_euler = (0, 0, 0)
        bone.location = (0, 0, 0)
    scene.bp.character = rig
    controller.display_type = 'WIRE'
    controller.bp.invisible_in_game = True
    rig.select_set(False)
    controller.select_set(True)
    context.view_layer.objects.active = controller
    return rig
