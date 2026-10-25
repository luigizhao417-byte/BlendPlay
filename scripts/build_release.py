# SPDX-License-Identifier: GPL-3.0-or-later
"""Only explicit engine files can enter the installable archive."""
from pathlib import Path
import ast
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MODULES = ('__init__.py', 'character.py', 'template_init.py')

def build(output=None):
    destination = Path(output) if output else ROOT / 'dist' / 'BlendPlay_Addon.zip'
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in MODULES:
            path = ROOT / 'blendplay' / name
            ast.parse(path.read_text(encoding='utf-8'), filename=name)
            archive.write(path, 'blendplay/' + name)
        for name in ('LICENSE', 'README.md'):
            archive.write(ROOT / name, 'blendplay/' + name)
    return destination

if __name__ == '__main__':
    print(build())
