"""Historical v7 through v12 experiments, loaded on their first explicit import."""

_NAMES = frozenset({
    "omega_bench", "omega_compute", "omega_storage", "omega_transport",
    "singularity_airgap_crypto", "singularity_bench", "singularity_kolmogorov_swarm",
    "singularity_time_crdt",
    "v9_app_index", "v9_bench", "v9_dataplane", "v9_nvme_grid",
    "v10_outlaw_engines", "v10_sovereign_crypto", "v10_sovereign_runtime",
    "v11_autopoietic_systems", "v11_organism_mesh", "v12_bench", "v12_galactic_engines",
})


class _PreviousModuleNames:
    """Resolve moved names only when a lookup reaches the parent package's last path entry."""

    def find_spec(self, fullname, target=None):
        from importlib.machinery import ModuleSpec

        parent, _, name = fullname.rpartition(".")
        if parent == "chimera_tp" and name in _NAMES:
            return ModuleSpec(fullname, self)
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        from importlib import import_module
        import sys

        old_name = module.__spec__.name
        name = old_name.rsplit(".", 1)[1]
        sys.modules[old_name] = import_module(f"{__name__}.{name}")

    def get_code(self, fullname):
        # These engine modules expose APIs and have no __main__ program. Preserve python -m.
        name = fullname.rsplit(".", 1)[1]
        if name not in _NAMES:
            raise ImportError(fullname)
        return compile(f"import {__name__}.{name}", f"<{fullname}>", "exec")

    def iter_modules(self, prefix=""):
        for name in sorted(_NAMES):
            yield prefix + name, False


def _install_previous_names(paths):
    import sys

    entry = paths[0] + "/.legacy-module-names"
    sys.path_importer_cache[entry] = _PreviousModuleNames()
    if entry not in paths:
        paths.append(entry)
