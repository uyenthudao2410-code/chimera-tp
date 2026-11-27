"""Isolated svhome checks for Aether. No production ports, mounts or services are used."""

import base64
import json
import shlex
import subprocess


REMOTE = r'''
import base64, hashlib, json, os, shutil, socket, subprocess, tempfile, time, uuid
from pathlib import Path

def run(cmd, **kwargs):
    return subprocess.run(cmd, check=True, capture_output=True, timeout=100, **kwargs).stdout

def socket_activation():
    unit = 'chimera-canary-' + uuid.uuid4().hex[:12]
    with socket.socket() as choose:
        choose.bind(('127.0.0.1', 0))
        port = choose.getsockname()[1]
    worker = """
import socket, time
with socket.socket(fileno=3) as s, s.accept()[0] as c:
    c.settimeout(5)
    c.recv(512)
    c.sendall(b'HTTP/1.0 200 OK\\r\\nContent-Length: 5\\r\\n\\r\\nready')
    time.sleep(1)
"""
    def pid():
        value = run(['systemctl','--user','show',unit+'.service','-p','MainPID','--value']).strip()
        return int(value or '0')
    try:
        run(['systemd-run','--user','--quiet','--collect','--unit='+unit,
             '--socket-property=ListenStream=127.0.0.1:'+str(port),'/usr/bin/python3','-I','-c',worker])
        before = pid()
        with socket.create_connection(('127.0.0.1',port),timeout=5) as client:
            client.sendall(b'GET / HTTP/1.0\r\n\r\n')
            response = client.recv(512)
        after = pid()
        assert before == 0 and after > 0 and response.endswith(b'ready')
        return {'pid_before':before,'worker_started':after>0,'http_status':200}
    finally:
        subprocess.run(['systemctl','--user','stop',unit+'.socket',unit+'.service'],capture_output=True,timeout=10)

def scratch():
    worker = """
import hashlib,json,os
p='/scratch/probe'
data=bytes(range(256))*32768
with open(p,'wb') as f:
    f.write(data)
with open(p,'rb') as f:
    assert hashlib.file_digest(f,'sha256').digest()==hashlib.sha256(data).digest()
st=os.statvfs('/scratch')
assert ' - tmpfs ' in next(l for l in open('/proc/self/mountinfo') if ' /scratch ' in l)
print(json.dumps({'mount_bytes':st.f_frsize*st.f_blocks,'roundtrip_bytes':len(data),'sha256_ok':True}))
"""
    return json.loads(run(['docker','run','--rm','--pull=never','--network','none','--read-only',
                '--cap-drop','ALL','--security-opt=no-new-privileges','--pids-limit','24',
                '--memory','2304m','--memory-swap','2304m','--user','65534:65534',
                '--tmpfs','/scratch:rw,nosuid,nodev,noexec,size=2147483648,mode=1777',
                'python:3.12-slim','python','-I','-B','-c',worker]))

def video():
    with tempfile.TemporaryDirectory(prefix='chimera-codec-') as temp:
        root=Path(temp)
        env=os.environ.copy()
        if subprocess.run(['gst-inspect-1.0','x264enc'],capture_output=True).returncode:
            run(['apt-get','download','gstreamer1.0-plugins-ugly','libx264-165'],cwd=root)
            for pkg in root.glob('*.deb'):
                run(['dpkg-deb','-x',str(pkg),str(root)])
            directory=root/'usr/lib/x86_64-linux-gnu'
            env.update(LD_LIBRARY_PATH=str(directory),GST_PLUGIN_PATH=str(directory/'gstreamer-1.0'),
                       GST_REGISTRY=str(root/'registry.bin'))
        data=run(['gst-launch-1.0','-q','videotestsrc','num-buffers=5','!',
                  'video/x-raw,format=I420,width=320,height=180,framerate=5/1','!',
                  'x264enc','tune=zerolatency','byte-stream=true','!',
                  'video/x-h264,stream-format=byte-stream','!','fdsink','fd=1'],env=env)
        return {'stream':base64.b64encode(data).decode(),'bytes':len(data)}

results={}
for name,func in [('socket_activation',socket_activation),('scratch',scratch),('video',video)]:
    try:
        results[name]=func()
    except Exception as exc:
        detail=getattr(exc,'stderr',b'') or b''
        results[name]={'error':str(exc)[:180],'detail':detail.decode(errors='replace')[-350:]}
print(json.dumps(results))
'''


def main():
    from imageio_ffmpeg import get_ffmpeg_exe

    proc = subprocess.run(["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "svhome",
                           shlex.join(["python3", "-I", "-"])], input=REMOTE.encode(), capture_output=True,
                          check=True, timeout=210)
    results = json.loads(proc.stdout)
    video = results["video"]
    if "stream" in video:
        data = base64.b64decode(video.pop("stream"), validate=True)
        decoded = subprocess.run([get_ffmpeg_exe(), "-v", "error", "-f", "h264", "-i", "pipe:0",
                                  "-f", "framemd5", "pipe:1"], input=data, capture_output=True,
                                 check=True, timeout=20)
        video["frames_decoded_on_windows"] = len([s for s in decoded.stdout.splitlines() if s and s[:1] != b"#"])
    print(json.dumps(results))
    return int(any("error" in v for v in results.values()) or video.get("frames_decoded_on_windows") != 5)


if __name__ == "__main__":
    raise SystemExit(main())
