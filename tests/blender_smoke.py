# SPDX-License-Identifier: GPL-3.0-or-later
"""Test the extracted engine in a clean scene, never the installed copy."""
import sys
import tempfile
from pathlib import Path
import bpy
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
import blendplay
assert Path(blendplay.__file__).resolve() == root / 'blendplay/__init__.py'
blendplay.register()
bpy.ops.bp.demo()
scene = bpy.context.scene
assert scene.bp.player and scene.bp.character and scene.camera
assert not any('DOORS' in o.name or 'Rush' in o.name or 'Ambush' in o.name for o in scene.objects)
for perspective in ('FIRST', 'THIRD', 'MAP'):
    scene.bp.perspective = perspective
    runtime = blendplay.Runtime(scene)
    start = runtime.player.location.copy()
    runtime.load_script()
    for _ in range(20):
        runtime.pressed = set()
        runtime.step({'W'}, 1/60)
    assert (runtime.player.location-start).length > .1
    runtime.get_key('W')
    runtime.call('stop')
    runtime.reset()
# All internal component text survives a .blend roundtrip.
expected = {text.name: text.as_string() for text in bpy.data.texts}
with tempfile.TemporaryDirectory() as directory:
    path = str(Path(directory) / 'generic-smoke.blend')
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=path, compress=True)
    bpy.ops.wm.open_mainfile(filepath=path)
    assert {text.name: text.as_string() for text in bpy.data.texts} == expected
blendplay.unregister()
print('BLENDPLAY_CLEAN_ENGINE_SMOKE_PASS', flush=True)
