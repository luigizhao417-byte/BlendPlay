# SPDX-License-Identifier: GPL-3.0-or-later
"""Find Blender without downloading anything, then invoke the Blender installer."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

def main():
    root = Path(__file__).resolve().parents[1]
    candidates = [os.environ.get('BLENDER_BIN'), shutil.which('blender'), '/Applications/Blender.app/Contents/MacOS/Blender']
    if os.name == 'nt':
        folder = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Blender Foundation'
        candidates.extend(str(p) for p in sorted(folder.glob('Blender */blender.exe'), reverse=True))
    binary = next((p for p in candidates if p and Path(p).is_file()), None)
    if not binary:
        raise SystemExit('找不到 Blender。请设置 BLENDER_BIN 为 Blender 可执行文件路径。')
    return subprocess.call([binary, '--background', '--factory-startup', '--python-exit-code', '1', '--python', str(root / 'scripts/install.py')])

if __name__ == '__main__':
    sys.exit(main())
