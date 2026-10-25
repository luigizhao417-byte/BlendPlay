# SPDX-License-Identifier: GPL-3.0-or-later
"""Run with Blender --background --factory-startup --python scripts/install.py.
Use -- --install-dir PATH --template-dir PATH --no-save-preferences for a sandbox.
"""
import argparse
import shutil
import sys
from pathlib import Path
import bpy

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--install-dir', type=Path)
parser.add_argument('--template-dir', type=Path)
parser.add_argument('--no-save-preferences', action='store_true')
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
addon_dir = args.install_dir or Path(bpy.utils.user_resource('SCRIPTS', path='addons', create=True))
template_dir = args.template_dir or Path(bpy.utils.user_resource('SCRIPTS', path='startup/bl_app_templates_user/Game_游戏', create=True))
package = addon_dir / 'blendplay'
package.mkdir(parents=True, exist_ok=True)
for name in ('__init__.py', 'character.py', 'template_init.py'):
    shutil.copy2(root / 'blendplay' / name, package / name)
shutil.copy2(root / 'LICENSE', package / 'LICENSE')
# This is a disposable background process; never overwrite the user's preferences.
bpy.ops.wm.read_factory_settings(use_empty=True)
sys.path.insert(0, str(addon_dir))
bpy.ops.preferences.addon_enable(module='blendplay')
import blendplay
assert Path(blendplay.__file__).resolve() == (package / '__init__.py').resolve()
# Construct the startup scene only from engine code. No external .blend or assets.
bpy.ops.bp.demo()
for area in bpy.context.window.screen.areas:
    if area.type == 'VIEW_3D':
        area.spaces.active.shading.color_type = 'MATERIAL'
template_dir.mkdir(parents=True, exist_ok=True)
shutil.copy2(root / 'blendplay/template_init.py', template_dir / '__init__.py')
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str((template_dir / 'startup.blend').resolve()), compress=True)
print('BLENDPLAY_INSTALL_OK', blendplay.bl_info['version'])
