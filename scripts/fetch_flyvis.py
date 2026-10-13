"""Download FlyVis's pretrained networks (3.4 MB) into .cache/flyvis/ and unpack them.

    backend/.venv/bin/python scripts/fetch_flyvis.py

The archive is kept only if its size and SHA-256 match the values below, which are also the checksum
that FlyVis 1.2.0's own download command expects. Install the optional vision lock first
(backend/requirements-vision.lock). FlyVis and its pretrained models are MIT licensed.
"""
import hashlib
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".cache/flyvis"
ARCHIVE = {
    "name": "results_pretrained_models.zip",
    "url": "https://drive.usercontent.google.com/download?id=13cJr2nMn89j-jBAd5RduYRJpBcXwoNrC&export=download",
    "bytes": 3417042,
    "sha256": "71c78d4070556a536b13b23ee3139cd2788aa2a9d07d430a223b4edead281db1",
    "source": "Google Drive folder published by FlyVis (flyvis_cli/download_pretrained_models.py, folder 15_8gPaVVJV6wGAspwkrdN8r-2NxMY4Kj)",
    "license": "MIT",
}


def unpack(archive: Path):
    with zipfile.ZipFile(archive) as zf:
        for name in zf.namelist():
            if name.startswith("/") or ".." in name.split("/") or "\\" in name:
                sys.exit(f"Refusing an unsafe path in the archive: {name}")
        zf.extractall(TARGET)


def main():
    archive = TARGET / "downloads" / ARCHIVE["name"]
    if (TARGET / "results/flow/0000/000/best_chkpt").is_file():
        print("The pretrained FlyVis networks are already unpacked in .cache/flyvis/results/.")
        return
    if not archive.is_file():
        archive.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {ARCHIVE['bytes'] / 1e6:.1f} MB of pretrained FlyVis networks …", flush=True)
        request = urllib.request.Request(ARCHIVE["url"], headers={"User-Agent": "digitalfly-fetch-flyvis"})
        with urllib.request.urlopen(request, timeout=300) as response:
            data = response.read()
        part = archive.with_suffix(".part")
        part.write_bytes(data)
        part.rename(archive)
    data = archive.read_bytes()
    if len(data) != ARCHIVE["bytes"] or hashlib.sha256(data).hexdigest() != ARCHIVE["sha256"]:
        archive.unlink()
        sys.exit("The archive does not match the recorded size and SHA-256; it was deleted.")
    unpack(archive)
    print("Verified and unpacked into .cache/flyvis/results/ (50 networks; DigitalFly uses flow/0000/000).")


if __name__ == "__main__":
    main()
