import argparse
import os
from pathlib import Path
import socket
import sys
import threading
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description="Launch the local DigitalFly workbench.")
parser.add_argument("--port", type=int, default=8000)
model_flags = parser.add_mutually_exclusive_group()
model_flags.add_argument("--toy", action="store_true", help="Explicitly select the kinematic toy demo")
model_flags.add_argument("--vision", action="store_true", help="Start with actual compound-eye inputs (requires OpenGL)")
parser.add_argument("--no-render", action="store_true", help="Use the labeled backend-pose arena view")
parser.add_argument("--dev", action="store_true", help="Allow the frontend development server instead of a built UI")
parser.add_argument("--open", action="store_true", help="Open the page in your browser")
parser.add_argument("--config", type=Path, help="Load a saved RunConfig JSON file")
args = parser.parse_args()
if not 1024 <= args.port <= 65535:
    sys.exit("Choose a port from 1024 to 65535.")
with socket.socket() as probe:
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind(("127.0.0.1", args.port))
    except OSError:
        sys.exit(f"Port {args.port} is occupied. Stop your previous DigitalFly server or choose --port 8001. No process was stopped.")
index = ROOT / "frontend/dist/index.html"
if not args.dev:
    if not index.is_file():
        sys.exit("Frontend build missing. Run ./scripts/setup.sh first.")
    sources = [*list((ROOT / "frontend/src").rglob("*")), ROOT / "frontend/package-lock.json", ROOT / "frontend/index.html", ROOT / "frontend/vite.config.ts"]
    if any(path.is_file() and path.stat().st_mtime > index.stat().st_mtime for path in sources):
        sys.exit("Frontend build is stale. Run: npm --prefix frontend run build")
os.environ["DIGITALFLY_PORT"] = str(args.port)
sys.path.insert(0, str(ROOT / "backend/src"))
try:
    import uvicorn
    from digitalfly.main import create_app
    from digitalfly.api.models import RunConfig
except ImportError as exc:
    sys.exit(f"Missing project dependency: {exc}. Run ./scripts/setup.sh.")
url = f"http://127.0.0.1:{5173 if args.dev else args.port}"
print(f"\nDigitalFly · local sensorimotor workbench\n{url}\nOne simulation worker · Ctrl+C to stop\n", flush=True)
if args.open:
    timer = threading.Timer(1, lambda: webbrowser.open(url))
    timer.daemon = True
    timer.start()
try:
    config = RunConfig.model_validate_json(args.config.read_text()) if args.config else RunConfig()
except Exception as exc:
    sys.exit(f"Invalid configuration: {exc}")
if args.toy:
    config.engine = "toy"
    config.sensor_model = "geometric"
elif args.vision:
    config.engine = "flygym"
    config.sensor_model = "vision"
app = create_app(config, render=not args.no_render)
server = uvicorn.Server(uvicorn.Config(app,
            host="127.0.0.1", port=args.port, workers=1, reload=False, log_level="warning",
            ws_max_size=16384, ws_max_queue=4, timeout_graceful_shutdown=15))
app.state.shutdown_callback = lambda: setattr(server, "should_exit", True)
server.run()
