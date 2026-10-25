# SPDX-License-Identifier: GPL-3.0-or-later
import ast
import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile
ROOT = Path(__file__).resolve().parents[1]

class DistributionTests(unittest.TestCase):
    def test_engine_modules_are_valid_and_game_independent(self):
        for path in (ROOT / 'blendplay').glob('*.py'):
            source = path.read_text(encoding='utf-8')
            ast.parse(source)
            for excluded in ('Rush', 'Ambush', 'DOORS', '/Users/', 'hotel_v', '完整游戏系统'):
                self.assertNotIn(excluded, source, str(path))

    def test_whitelist_archive(self):
        spec = importlib.util.spec_from_file_location('build_release', ROOT / 'scripts/build_release.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            archive = module.build(Path(directory) / 'addon.zip')
            with zipfile.ZipFile(archive) as z:
                self.assertEqual(set(z.namelist()), {'blendplay/__init__.py', 'blendplay/character.py', 'blendplay/template_init.py', 'blendplay/LICENSE', 'blendplay/README.md'})

    def test_no_game_assets_in_source_tree(self):
        for folder in ('blendplay', 'examples', 'docs', 'scripts', 'tests'):
            for path in (ROOT / folder).rglob('*'):
                if path.is_file() and '__pycache__' not in path.parts:
                    self.assertIn(path.suffix, ('.py', '.md'), str(path))

if __name__ == '__main__':
    unittest.main()
