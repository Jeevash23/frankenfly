"""Resilient downloads (digitalfly.data.downloads) and the data scripts that use them, against a local HTTP server
that can cut transfers short, fail transiently, refuse files and ignore byte ranges."""
import hashlib
import importlib.util
import json
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest
from digitalfly.data import downloads
from digitalfly.data.downloads import DownloadError, download, fetch_bytes

ROOT = Path(__file__).resolve().parents[2]
DATA = bytes(range(256)) * 1024  # 256 KiB


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        server = self.server
        server.requests.append(self.headers.get("Range"))
        plan = server.plan.pop(0) if server.plan else "ok"
        if isinstance(plan, int):
            self.send_error(plan)
            return
        match = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range") or "")
        if match and server.ranges:
            start, end = int(match[1]), int(match[2]) + 1 if match[2] else len(DATA)
            if start >= len(DATA):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{len(DATA)}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = DATA[start:end]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end - 1}/{len(DATA)}")
        else:
            body = DATA
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        # "cut" sends a third of the body, then the connection closes (HTTP/1.0).
        self.wfile.write(body[:len(body) // 3] if plan == "cut" else body)


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.requests, httpd.plan, httpd.ranges = [], [], True
    httpd.url = f"http://127.0.0.1:{httpd.server_address[1]}/data.bin"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def waits(monkeypatch):
    """Record the backoff waits instead of sleeping."""
    seen = []
    monkeypatch.setattr(downloads.time, "sleep", seen.append)
    return seen


def test_an_interrupted_download_resumes_with_a_range_request(server, waits, tmp_path):
    server.plan = ["cut"]
    part = tmp_path / "data.part"
    logged = []
    assert download(server.url, part, len(DATA), log=logged.append) == part and part.read_bytes() == DATA
    assert server.requests == [None, f"bytes={len(DATA) // 3}-"] and waits == [2.0]
    assert "closed after" in logged[0] and "retrying in 2 s" in logged[0]
    # A partial file from an earlier run is resumed; a complete one needs no request at all.
    part.write_bytes(DATA[:1000])
    server.requests.clear()
    assert download(server.url, part, len(DATA)).read_bytes() == DATA and server.requests == ["bytes=1000-"]
    assert download(server.url, part, len(DATA)) and server.requests == ["bytes=1000-"]
    # Without a known size, the server's 416 says the file is already whole.
    assert download(server.url, part).read_bytes() == DATA and server.requests[-1] == f"bytes={len(DATA)}-"


def test_a_server_without_ranges_sends_the_whole_file_again(server, waits, tmp_path):
    server.ranges = False
    part = tmp_path / "data.part"
    part.write_bytes(b"x" * 1000)  # not even the right bytes: replaced, never appended to
    assert download(server.url, part, len(DATA)).read_bytes() == DATA and server.requests == ["bytes=1000-"]
    server.plan, server.requests[:] = ["cut"], []
    assert fetch_bytes(server.url) == DATA and server.requests == [None, f"bytes={len(DATA) // 3}-"]
    with pytest.raises(DownloadError, match="does not serve byte ranges"):
        fetch_bytes(server.url, 10, 20)


def test_byte_ranges_resume_in_memory(server, waits):
    server.plan = ["cut"]
    assert fetch_bytes(server.url, 1000, 4000) == DATA[1000:4000]
    assert server.requests == ["bytes=1000-3999", "bytes=2000-3999"]


def test_transient_errors_back_off_and_permanent_ones_fail_at_once(server, waits, tmp_path):
    server.plan = [503, 503]
    assert fetch_bytes(server.url) == DATA and waits == [2.0, 4.0]
    server.plan, server.requests[:] = [404], []
    with pytest.raises(DownloadError) as missing:
        download(server.url, tmp_path / "x.part")
    assert missing.value.status == 404 and "HTTP 404" in str(missing.value) and len(server.requests) == 1
    with socket.socket() as probe:  # a port nothing listens on
        probe.bind(("127.0.0.1", 0))
        closed = f"http://127.0.0.1:{probe.getsockname()[1]}/x"
    waits.clear()
    with pytest.raises(DownloadError) as unreachable:
        fetch_bytes(closed, retries=3)
    assert waits == [2.0, 4.0, 8.0] and "gave up after 3 retries" in str(unreachable.value)
    assert "\n" not in str(unreachable.value) and unreachable.value.status is None


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fetch_recording_resumes_verifies_and_fails_in_one_line(server, waits, tmp_path, monkeypatch, capsys):
    fetch = load_script("fetch_recording")
    record = {"name": "fly.mat", "url": server.url, "bytes": len(DATA), "md5": hashlib.md5(DATA).hexdigest(),
              "sha256": hashlib.sha256(DATA).hexdigest()}
    manifest = tmp_path / "downloads.json"
    manifest.write_text(json.dumps([record]))
    monkeypatch.setattr(fetch, "RECORDS", manifest)
    monkeypatch.setattr(fetch, "CACHE", tmp_path / "cache")
    server.plan = ["cut"]
    fetch.main(["fly.mat"])
    assert (tmp_path / "cache/fly.mat").read_bytes() == DATA and not (tmp_path / "cache/fly.mat.part").exists()
    assert "Saved and verified" in capsys.readouterr().out
    (tmp_path / "cache/fly.mat").unlink()
    (tmp_path / "cache/fly.mat.part").write_bytes(DATA[:5000])  # left by an interrupted run
    server.requests.clear()
    fetch.main(["fly.mat"])
    assert server.requests == ["bytes=5000-"] and "resuming after" in capsys.readouterr().out
    (tmp_path / "cache/fly.mat").unlink()
    manifest.write_text(json.dumps([{**record, "sha256": "0" * 64}]))
    with pytest.raises(SystemExit, match=r"\(SHA-256 differs\); nothing was kept"):
        fetch.main(["fly.mat"])
    assert not (tmp_path / "cache/fly.mat.part").exists()
    manifest.write_text(json.dumps([record]))
    server.plan = [404]
    with pytest.raises(SystemExit) as failed:
        fetch.main(["fly.mat"])
    assert str(failed.value.code).startswith("Download failed: ") and "HTTP 404" in str(failed.value.code)
    assert "\n" not in str(failed.value.code)


def test_the_circuit_builder_fetch_retries_and_exits_in_one_line(server, waits, tmp_path):
    builder = load_script("build_circuit")
    server.plan = ["cut"]
    assert builder.fetch(server.url, 100, 3100) == DATA[100:3100]
    part = tmp_path / "meta.part"
    assert builder.fetch(server.url, path=part, size=len(DATA)) == part and part.read_bytes() == DATA
    server.plan = [404, 404]
    assert builder.fetch(server.url, missing_ok=True) is None
    with pytest.raises(SystemExit) as failed:
        builder.fetch(server.url)
    assert str(failed.value.code).startswith("Download failed: ") and "\n" not in str(failed.value.code)
