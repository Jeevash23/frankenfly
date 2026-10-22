"""Setup checks (scripts/doctor.py) on Python versions and an unwanted frontend build, and byte ranges from a server
that ignores them."""
import importlib.util
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest
from digitalfly.data.downloads import DownloadError, fetch_bytes

ROOT = Path(__file__).resolve().parents[2]


def load_doctor():
    spec = importlib.util.spec_from_file_location("doctor", ROOT / "scripts/doctor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("version, status", [((3, 12, 9), "ok"), ((3, 13, 1), "info"), ((3, 14, 0), "info"),
                                             ((3, 11, 9), "fail"), ((3, 15, 0), "fail")])
def test_doctor_accepts_the_supported_python_versions(version, status, monkeypatch, capsys):
    doctor = load_doctor()
    monkeypatch.setattr(doctor, "VENV_PYTHON", Path(sys.executable))
    monkeypatch.setattr(doctor, "venv", lambda code, *args, **kwargs: {"python": list(version), "installed": {}})
    assert doctor.check_python() is not None
    line = capsys.readouterr().out
    assert line.startswith(f"[{status:^4}] Python") and doctor.failures == (["Python"] if status == "fail" else []), line
    if status == "info":
        assert "FlyVis is unavailable" in line and "PYTHON_BIN=/path/to/python3.12" in line
    if status == "fail":
        assert "3.12, 3.13 or 3.14" in line


def test_doctor_does_not_fail_backend_only_setups_on_a_stale_frontend_build(tmp_path, monkeypatch, capsys):
    doctor = load_doctor()
    (tmp_path / "frontend/dist").mkdir(parents=True)
    (tmp_path / "frontend/src").mkdir()
    (tmp_path / "frontend/dist/index.html").write_text("<html></html>")
    os.utime(tmp_path / "frontend/dist/index.html", (1e9, 1e9))
    (tmp_path / "frontend/src/main.ts").write_text("// newer than the build")
    monkeypatch.setattr(doctor, "ROOT", tmp_path)
    monkeypatch.setattr(doctor, "BACKEND_ONLY", True)
    doctor.check_frontend()
    out = capsys.readouterr().out
    assert doctor.failures == [] and out.startswith("[info] Frontend build") and "--backend-only" in out, out
    monkeypatch.setattr(doctor, "BACKEND_ONLY", False)
    doctor.check_frontend()
    assert doctor.failures == ["Frontend build"]  # without --backend-only a stale build still fails


class WholeFile(BaseHTTPRequestHandler):
    """A server that ignores Range and always sends the whole file."""
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "1000")
        self.end_headers()
        self.wfile.write(bytes(1000))


def test_an_open_byte_range_from_a_server_without_ranges_fails_in_one_line():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), WholeFile)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/data.bin"
    try:
        with pytest.raises(DownloadError, match=r"does not serve byte ranges \(asked for bytes 100-\)\.$"):
            fetch_bytes(url, 100, None, log=None)
        with pytest.raises(DownloadError, match=r"\(asked for bytes 100-199\)\.$"):
            fetch_bytes(url, 100, 200, log=None)
    finally:
        httpd.shutdown()
        httpd.server_close()
