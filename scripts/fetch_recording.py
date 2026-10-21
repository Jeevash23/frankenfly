"""Download a recorded-fly dataset listed in data/recordings/downloads.json into .cache/recordings/.

    backend/.venv/bin/python scripts/fetch_recording.py rayshubskiy2025-a2_d_13.mat

The file is checked against the recorded size, MD5 and SHA-256 before it is kept. Nothing is
downloaded when a verified copy is already cached. Network errors are retried with backoff; an
interrupted download stays in a .part file, and running the command again resumes it (HTTP Range,
where the server supports it). Raw data stays out of version control.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
from digitalfly.data.downloads import DownloadError, download  # noqa: E402

RECORDS = ROOT / "data/recordings/downloads.json"
CACHE = ROOT / ".cache/recordings"


def verify(path, record):
    md5, sha256, size = hashlib.md5(), hashlib.sha256(), 0
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1 << 20):
            md5.update(chunk)
            sha256.update(chunk)
            size += len(chunk)
    problems = []
    if size != record["bytes"]:
        problems.append(f"{size} bytes instead of {record['bytes']}")
    if md5.hexdigest() != record["md5"]:
        problems.append("MD5 differs")
    if sha256.hexdigest() != record["sha256"]:
        problems.append("SHA-256 differs")
    return problems


def shown(path):
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


def main(argv=None):
    records = {r["name"]: r for r in json.loads(RECORDS.read_text())}
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("name", choices=sorted(records))
    parser.add_argument("--offline", action="store_true", help="Only verify an existing copy")
    args = parser.parse_args(argv)
    record = records[args.name]
    path = CACHE / args.name
    if path.is_file():
        problems = verify(path, record)
        if problems:
            sys.exit(f"{shown(path)} does not match the record ({'; '.join(problems)}). Delete it to download again.")
        print(f"{shown(path)} is present and verified ({record['bytes']:,} bytes).")
        return
    if args.offline:
        sys.exit(f"{shown(path)} is missing. Run without --offline to download {record['bytes'] / 1e6:.1f} MB.")
    CACHE.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    done = part.stat().st_size if part.is_file() else 0
    print(f"Downloading {record['bytes'] / 1e6:.1f} MB from {record['url']}"
          + (f", resuming after {done / 1e6:.1f} MB" if done else "") + " …", flush=True)
    try:
        download(record["url"], part, record["bytes"], agent="digitalfly-fetch-recording")
    except DownloadError as exc:
        kept = part.stat().st_size if part.is_file() else 0
        sys.exit(f"Download failed: {exc}."
                 + (f" {kept / 1e6:.1f} MB are kept in {shown(part)}; run the command again to resume." if kept else ""))
    problems = verify(part, record)
    if problems:
        part.unlink()
        sys.exit(f"The download does not match the record ({'; '.join(problems)}); nothing was kept.")
    part.rename(path)
    print(f"Saved and verified {shown(path)}.")


if __name__ == "__main__":
    main()
