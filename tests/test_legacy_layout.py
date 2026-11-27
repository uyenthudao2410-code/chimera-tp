"""Public import paths and object identity across the legacy package boundary."""
from pathlib import Path
import subprocess
import sys
import unittest


class LegacyLayoutTests(unittest.TestCase):
    def test_old_and_new_names_share_one_module_in_either_order(self):
        root = str(Path(__file__).resolve().parents[1])
        program = """
import importlib, pickle, pkgutil, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import chimera_tp
from chimera_tp import legacy
names = sorted(legacy._NAMES)
moved = {'omega_bench', 'omega_compute', 'omega_storage', 'omega_transport', 'singularity_airgap_crypto',
         'singularity_bench', 'singularity_kolmogorov_swarm', 'singularity_time_crdt'}
assert len(names) == 19 and moved <= set(names)
package = Path(chimera_tp.__file__).resolve().parent
assert all((package / 'legacy' / (n + '.py')).is_file() and not (package / (n + '.py')).exists() for n in moved)
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
from chimera_tp import MerkleCrdtShadowTwin, RegeneratingMeshVault
assert MerkleCrdtShadowTwin is legacy.singularity_time_crdt.MerkleCrdtShadowTwin
assert RegeneratingMeshVault is legacy.omega_storage.RegeneratingMeshVault
assert pickle.loads(b'cchimera_tp.singularity_time_crdt\\nMerkleCrdtShadowTwin\\n.') is MerkleCrdtShadowTwin
assert pickle.loads(b'cchimera_tp.omega_storage\\nRegeneratingMeshVault\\n.') is RegeneratingMeshVault
assert pickle.loads(b'cchimera_tp.v9_app_index\\nLiveClusterIndexer\\n.') is from_legacy
"""
        for order in ("old", "new"):
            with self.subTest(order=order):
                subprocess.run([sys.executable, "-I", "-B", "-S", "-c", program, root, order],
                               check=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


if __name__ == "__main__":
    unittest.main()
