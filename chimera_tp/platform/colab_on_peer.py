"""Use the configured peer's own Colab CLI and credentials for a selected script."""

import json
import shlex
import subprocess


_WORKER = """
import json, os, pathlib, shutil, subprocess, sys
path = next((p for p in [shutil.which('colab'), os.getenv('CHIMERA_COLAB_CLI_BIN'),
            str(pathlib.Path.home()/'.local/bin/colab'),
            str(pathlib.Path.home()/'DEV/radar_dashboard/.venv/bin/colab')]
            if p and pathlib.Path(p).is_file() and os.access(p, os.X_OK)), None)
if not path:
    raise RuntimeError('Colab CLI missing on peer')
profile, script, execute = sys.argv[1:]
args = [path, 'run', '--timeout', '180']
if profile in ('T4','L4'):
    args.extend(['--gpu', profile])
if profile == 'CPU_HIGH_MEM':
    args.append('--high-mem')
if script and (not pathlib.Path(script).is_absolute() or not pathlib.Path(script).is_file()):
    raise ValueError('expected a Python script already present on the peer')
if execute == 'yes':
    if not script:
        raise ValueError('a peer script is required')
    os.execv(path, [*args, script])
probe = subprocess.run([path, 'usage'], text=True, capture_output=True, timeout=30, check=True)
print(json.dumps({'usage':[l.strip() for l in probe.stdout.splitlines()
                          if l.startswith(('Current balance:', 'Usage rate:', 'Active assignments:'))],
                  'argv':[*args,script or '<peer-script>'], 'executed':False}))
"""


def headless(profile="CPU", script="", execute=False):
    if profile not in ("CPU", "CPU_HIGH_MEM", "T4", "L4"):
        raise ValueError("unsupported runtime profile")
    remote = shlex.join(["python3", "-I", "-", profile, str(script), "yes" if execute else "no"])
    args = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "svhome", remote]
    if execute:
        proc = subprocess.run(args, input=_WORKER.encode(),
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {"executed": True, "exit_code": proc.returncode}
    proc = subprocess.run(args, input=_WORKER.encode(), capture_output=True, check=True, timeout=40,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return json.loads(proc.stdout)
