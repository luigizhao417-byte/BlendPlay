# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender“Game 游戏”应用模板：载入游戏工作区后显示视角选择。"""
import bpy
import sys
import importlib

registered_here = False
welcome_invocations = 0


def ensure_blendplay():
    global registered_here
    if hasattr(bpy.types.Scene, 'bp'):
        return True
    addon_path = bpy.utils.user_resource('SCRIPTS', path='addons')
    if addon_path not in sys.path:
        sys.path.insert(0, addon_path)
    module = importlib.import_module('blendplay')
    module.register()
    registered_here = True
    return True


def show_welcome():
    global welcome_invocations
    if bpy.app.background:
        return None
    try:
        ensure_blendplay()
        window = bpy.context.window_manager.windows[0]
        area = next((a for a in window.screen.areas if a.type == 'VIEW_3D'), None)
        if area is None:
            return .5
        with bpy.context.temp_override(window=window, area=area):
            result = bpy.ops.bp.welcome('INVOKE_DEFAULT')
            if 'RUNNING_MODAL' in result:
                welcome_invocations += 1
    except (AttributeError, IndexError, RuntimeError):
        return None
    return None


def register():
    # Blender 应用模板有独立的插件启用状态；从欢迎页创建游戏时主动载入运行器。
    if not bpy.app.timers.is_registered(show_welcome):
        bpy.app.timers.register(show_welcome, first_interval=.6)


def unregister():
    if bpy.app.timers.is_registered(show_welcome):
        bpy.app.timers.unregister(show_welcome)
    if registered_here:
        importlib.import_module('blendplay').unregister()
