"""Public import paths and object identity across the legacy package boundary."""
from pathlib import Path
import subprocess
import sys
import unittest


class LegacyLayoutTests(unittest.TestCase):
    def test_old_and_new_names_share_one_module_in_either_order(self):
        root = str(Path(__file__).resolve().parents[1])
        program = """
import importlib, pkgutil, sys
sys.path.insert(0, sys.argv[1])
import chimera_tp
from chimera_tp import legacy
names = sorted(legacy._NAMES)
assert len(names) == 11
assert not any('chimera_tp.legacy.' + n in sys.modules or 'chimera_tp.' + n in sys.modules for n in names)
visible = {m.name for m in pkgutil.iter_modules(chimera_tp.__path__)}
assert set(names) <= visible
importlib.invalidate_caches()
for name in names:
    old = 'chimera_tp.' + name
    new = 'chimera_tp.legacy.' + name
    first, second = (old, new) if sys.argv[2] == 'old' else (new, old)
    a = importlib.import_module(first)
    b = importlib.import_module(second)
    assert a is b and a.__spec__.name == new and a.__package__ == 'chimera_tp.legacy', name
    assert getattr(chimera_tp, name) is b and getattr(legacy, name) is a, name
from chimera_tp import LiveClusterIndexer
from chimera_tp.legacy.v9_app_index import LiveClusterIndexer as from_legacy
assert LiveClusterIndexer is from_legacy
import pickle
assert pickle.loads(b'cchimera_tp.v9_app_index\\nLiveClusterIndexer\\n.') is from_legacy
"""
        for order in ("old", "new"):
            with self.subTest(order=order):
                subprocess.run([sys.executable, "-I", "-B", "-S", "-c", program, root, order],
                               check=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


if __name__ == "__main__":
    unittest.main()
