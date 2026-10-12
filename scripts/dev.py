"""Supervise only the two child processes created for this development session."""
from pathlib import Path
import signal
import socket
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
for port in [8000, 5173]:
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            raise SystemExit(f"Port {port} is occupied; no process was stopped.")
children = []
def stop(signum=None, frame=None):
    raise KeyboardInterrupt
signal.signal(signal.SIGTERM, stop)
try:
    children.append(subprocess.Popen([str(ROOT / "scripts/start.sh"), "--dev"], cwd=ROOT))
    children.append(subprocess.Popen(["npm", "run", "dev"], cwd=ROOT / "frontend", start_new_session=True))
    print("Development UI: http://127.0.0.1:5173 · restart this command after Python edits", flush=True)
    while all(p.poll() is None for p in children):
        time.sleep(.5)
except KeyboardInterrupt:
    pass
finally:
    import os
    for i, child in enumerate(children):
        if child.poll() is None:
            if i == 1:
                os.killpg(child.pid, signal.SIGTERM)
            else:
                child.terminate()
    for child in children:
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
